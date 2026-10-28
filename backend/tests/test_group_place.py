"""群聊的地点：页首选一个场景，整个群下一句起就知道自己在哪儿；取消就回到没说地点。
不是自己的群一律 404。"""

import httpx

from tests.conftest import ClientFactory
from tests.fakes import FakeLLM


async def make_group(client: httpx.AsyncClient) -> str:
    res = await client.post("/api/groups", json={"character_ids": ["mano", "kogane"]})
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def test_a_chosen_place_is_returned_and_can_be_cleared(
    make_client: ClientFactory,
) -> None:
    client = make_client(FakeLLM())
    group = await make_group(client)

    picked = await client.put(f"/api/groups/{group}/place", json={"scene_id": "lounge"})

    assert picked.status_code == 200
    assert picked.json() == {
        "scene": {
            "id": "lounge",
            "name": "事务所休息室",
            "image_url": "/api/scenes/lounge",
        }
    }
    assert (await client.get(f"/api/groups/{group}/place")).json() == picked.json()

    cleared = await client.put(f"/api/groups/{group}/place", json={"scene_id": None})

    assert cleared.status_code == 200
    assert cleared.json() == {"scene": None}
    assert (await client.get(f"/api/groups/{group}/place")).json() == {"scene": None}


async def test_an_unknown_place_is_not_found(make_client: ClientFactory) -> None:
    client = make_client(FakeLLM())
    group = await make_group(client)

    res = await client.put(f"/api/groups/{group}/place", json={"scene_id": "moon"})

    assert res.status_code == 404
    assert (await client.get(f"/api/groups/{group}/place")).json() == {"scene": None}


async def test_another_users_group_place_is_not_found(make_client: ClientFactory) -> None:
    producer = make_client(FakeLLM())
    other = make_client(FakeLLM(), user="other")
    theirs = await make_group(other)

    got = await producer.get(f"/api/groups/{theirs}/place")
    put = await producer.put(
        f"/api/groups/{theirs}/place", json={"scene_id": "lounge"}
    )

    assert got.status_code == 404
    assert put.status_code == 404
    assert (await other.get(f"/api/groups/{theirs}/place")).json() == {"scene": None}
