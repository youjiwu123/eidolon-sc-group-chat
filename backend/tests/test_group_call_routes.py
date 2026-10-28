"""群通话的两个接口：不在自己的群里就是 404；部署没有通话的 key 时是 503（准入先拒绝，
根本走不到 WebRTC）。通话本身（真的接上、换人换声）在 `test_group_call.py` 和浏览器验收里。"""

from tests.conftest import ClientFactory
from tests.fakes import FakeLLM


async def test_a_group_call_into_someone_elses_group_is_not_found(make_client: ClientFactory) -> None:
    producer = make_client(FakeLLM())
    other = make_client(FakeLLM(), user="other")
    theirs = await other.post("/api/groups", json={"character_ids": ["mano", "kogane"]})
    assert theirs.status_code in (200, 201)

    res = await producer.post(
        f"/api/groups/{theirs.json()['id']}/call",
        json={"sdp": "v=0", "type": "offer"},
    )

    assert res.status_code == 404


async def test_a_group_call_without_call_keys_is_unavailable(make_client: ClientFactory) -> None:
    client = make_client(FakeLLM(), voice_configured=False)
    created = await client.post("/api/groups", json={"character_ids": ["mano", "kogane"]})
    assert created.status_code in (200, 201)

    res = await client.post(
        f"/api/groups/{created.json()['id']}/call",
        json={"sdp": "v=0", "type": "offer"},
    )

    # 测试的部署没有语音的 key：准入拒绝，返回 503，而不是去建 WebRTC
    assert res.status_code == 503
