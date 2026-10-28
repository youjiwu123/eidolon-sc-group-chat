"""锁定好感度（后台「调整好感度」对话框里的锁）：锁着的时候回合和礼物都不动它，她也不会因为
好感度分开或挂断；解开以后照旧。管理员自己设值仍然照常（那正是这个对话框的用处）。
"""

from dataclasses import replace

import httpx
import pytest

from eidolon.config import Settings
from tests.conftest import ClientFactory
from tests.fakes import (
    FAKE_JUDGE,
    FakeClock,
    FakeIdentityProvider,
    FakeLLM,
    FakeServiceClients,
    level,
)
from tests.test_admin_users import ADMIN, admin_beside, admin_client
from tests.test_affinity_turns import value
from tests.test_conversation_events import record, shape
from tests.test_delete_account import user_id
from tests.test_text_turn import done_of, send_turn, start_conversation

REPLY = ["<ja>はい</ja><zh>好的</zh>"]
OUT_OF_LINE = level(0, out_of_line=True)


@pytest.fixture
def settings(settings: Settings) -> Settings:
    """With an admin, the judge model and affinity on."""
    return replace(
        settings, admins=frozenset({ADMIN}), judge=FAKE_JUDGE, affinity_and_gifts=True
    )


async def lock_at(
    admin: httpx.AsyncClient, uid: str, at: float, *, locked: bool = True
) -> dict:
    """Set her affinity with the producer and lock it (or unlock it)."""
    res = await admin.put(
        f"/api/admin/users/{uid}/affinity",
        json={"character_id": "mano", "value": at, "locked": locked},
    )
    assert res.status_code == 200, res.text
    return res.json()


async def test_a_locked_affinity_does_not_move_with_what_she_hears(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    clients = FakeServiceClients()
    clients.judge.judgings = [level(0)]  # 平时这一步会掉 2
    client = make_client(FakeLLM(REPLY), clients=clients, clock=FakeClock())
    conversation = await start_conversation(client)
    uid = user_id(settings.database_path, "producer")
    async with admin_beside(client, github) as admin:
        assert (await lock_at(admin, uid, 45))["locked"] is True

    events = await send_turn(client, conversation, "你这个废物")

    assert done_of(events)["message"]["affinity"] is None  # 没有变化可显示
    assert value(settings.database_path) == 45
    # 也没有进冷却。
    assert (await client.get("/api/characters/mano/affinity")).json()["cooldown_until"] is None


async def test_unlocking_lets_what_she_hears_move_it_again(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    clients = FakeServiceClients()
    clients.judge.judgings = [level(0), level(0)]
    client = make_client(FakeLLM(REPLY, REPLY), clients=clients, clock=FakeClock())
    conversation = await start_conversation(client)
    uid = user_id(settings.database_path, "producer")
    async with admin_beside(client, github) as admin:
        await lock_at(admin, uid, 45)
    await send_turn(client, conversation, "你这个废物")
    assert value(settings.database_path) == 45

    async with admin_beside(client, github) as admin:
        assert (await lock_at(admin, uid, 45, locked=False))["locked"] is False
    await send_turn(client, conversation, "你这个废物")

    assert value(settings.database_path) == 40.0  # level 0 那一步 −5


async def test_a_locked_conversation_is_never_ended_by_her(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    clients = FakeServiceClients()
    clients.judge.judgings = [OUT_OF_LINE] * 3
    client = make_client(FakeLLM(*[REPLY] * 3), clients=clients, clock=FakeClock())
    conversation = await start_conversation(client)
    uid = user_id(settings.database_path, "producer")
    async with admin_beside(client, github) as admin:
        await lock_at(admin, uid, 45)

    for _ in range(3):
        events = await send_turn(client, conversation, "你这个废物")
        assert done_of(events)["ended"] is None

    assert "ended" not in shape(await record(client, conversation))


async def test_a_gift_and_a_reset_card_do_not_move_a_locked_affinity(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    client = make_client(FakeLLM(), clock=FakeClock())
    uid = user_id(settings.database_path, "producer")
    async with admin_beside(client, github) as admin:
        await lock_at(admin, uid, 10)  # 冷淡档，重置卡平时会把她拉回 50
    backend = client._transport.app.state.backend
    seen: list[object] = []

    backend.affinities.receive_gift(uid, "mano", "common", True, seen.append)
    assert backend.affinities.reset(uid, ["mano"]) == []

    assert value(settings.database_path) == 10
    assert seen == [None]  # 连「涨了」都不告诉浏览器


async def test_the_admin_api_reads_and_sets_the_lock(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    make_client(FakeLLM())  # 先有 producer 这个用户
    admin = await admin_client(make_client, github)
    uid = user_id(settings.database_path, "producer")
    listed = (await admin.get(f"/api/admin/users/{uid}/affinity")).json()["affinities"]

    assert {one["locked"] for one in listed} == {False}
    assert (await lock_at(admin, uid, 45))["locked"] is True
    assert (await admin.get(f"/api/admin/users/{uid}/affinity")).json()["affinities"][0][
        "locked"
    ] is True
    # 只设值、不说锁的请求，锁原样留着。
    kept = await admin.put(
        f"/api/admin/users/{uid}/affinity", json={"character_id": "mano", "value": 50}
    )
    assert kept.json()["locked"] is True
    assert (await lock_at(admin, uid, 50, locked=False))["locked"] is False
