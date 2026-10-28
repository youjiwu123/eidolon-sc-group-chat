"""特殊档按角色各一份（`character_modes`，`/api/characters/<id>/modes`）。

每个角色开哪几个是她自己的：同一位用户给 mano 开了夜之魅魔，给 kogane 开的教官与她无关，
关掉一个不碰另一个。提示词在好感各档都追加（不再只有爱意档），而且只追加她自己开着的；模式表
里没有的 id 拒收（422），没有这个角色是 404，档案里旧的那个全局 `special_mode` 不再进提示词。
"""

from dataclasses import replace
from pathlib import Path

import pytest

from eidolon.config import Settings
from tests.conftest import CharacterConfig, ClientFactory
from tests.fakes import FAKE_JUDGE, FakeClock, FakeLLM, FakeServiceClients, level
from tests.test_affinity import keep
from tests.test_affinity_prompt import about_now
from tests.test_modes import MODE_TABLE, SPECIAL_MARK, STERN_MARK, SUCCUBUS_MARK
from tests.test_text_turn import send_turn, start_conversation


@pytest.fixture
def modes(characters: CharacterConfig) -> Path:
    path = characters.directory / "modes.toml"
    path.write_text(MODE_TABLE, encoding="utf-8")
    return path


@pytest.fixture
def settings(settings: Settings) -> Settings:
    """With the judge model, and affinity on in `.env`."""
    return replace(settings, judge=FAKE_JUDGE, affinity_and_gifts=True)


async def modes_of(client, character: str) -> list[str]:
    res = await client.get(f"/api/characters/{character}/modes")
    assert res.status_code == 200
    return res.json()["enabled"]


async def prompted(
    make_client: ClientFactory,
    settings: Settings,
    *,
    character: str = "mano",
    kept: float = 110.0,
) -> str:
    """One typed turn with her, her affinity `kept` as it begins; what the prompt says of now."""
    llm = FakeLLM("<ja>はい</ja><zh>好的</zh>")
    clients = FakeServiceClients()
    clients.judge.judgings = [level(2)]
    clock = FakeClock()
    client = make_client(llm, clients=clients, clock=clock, settings=settings)
    conversation = await start_conversation(client, character)
    keep(settings.database_path, "producer", kept, clock.now, character=character)
    await send_turn(client, conversation, "你今天怎么这么凶")
    return about_now(llm)


async def test_each_character_has_her_own_modes(
    make_client: ClientFactory, settings: Settings, modes: Path
):
    client = make_client(FakeLLM(), settings=settings)

    await client.put("/api/characters/mano/modes", json={"enabled": ["succubus"]})
    await client.put("/api/characters/kogane/modes", json={"enabled": ["stern"]})

    assert await modes_of(client, "mano") == ["succubus"]
    assert await modes_of(client, "kogane") == ["stern"]

    # 关掉一个不碰另一个。
    await client.put("/api/characters/mano/modes", json={"enabled": []})
    assert await modes_of(client, "mano") == []
    assert await modes_of(client, "kogane") == ["stern"]


async def test_a_turn_reads_only_her_own_modes_at_love(
    make_client: ClientFactory, settings: Settings, modes: Path
):
    client = make_client(FakeLLM(), settings=settings)
    await client.put("/api/characters/mano/modes", json={"enabled": ["succubus"]})
    await client.put("/api/characters/kogane/modes", json={"enabled": ["special"]})

    section = await prompted(make_client, settings)

    assert SUCCUBUS_MARK in section
    assert SPECIAL_MARK not in section
    assert STERN_MARK not in section


async def test_a_turn_below_love_reads_them_too(
    make_client: ClientFactory, settings: Settings, modes: Path
):
    client = make_client(FakeLLM(), settings=settings)
    await client.put("/api/characters/mano/modes", json={"enabled": ["succubus"]})

    section = await prompted(make_client, settings, kept=60.0)

    # 好感各档都追加：亲近档照样读到她自己开的那个。
    assert SUCCUBUS_MARK in section


async def test_two_modes_at_once_follow_the_tables_order(
    make_client: ClientFactory, settings: Settings, modes: Path
):
    client = make_client(FakeLLM(), settings=settings)
    await client.put(
        "/api/characters/mano/modes", json={"enabled": ["succubus", "special"]}
    )

    section = await prompted(make_client, settings)

    assert SPECIAL_MARK in section and SUCCUBUS_MARK in section
    assert section.index(SPECIAL_MARK) < section.index(SUCCUBUS_MARK)


async def test_a_mode_the_table_does_not_have_is_refused(
    make_client: ClientFactory, settings: Settings, modes: Path
):
    client = make_client(FakeLLM(), settings=settings)

    res = await client.put("/api/characters/mano/modes", json={"enabled": ["nope"]})

    assert res.status_code == 422
    assert await modes_of(client, "mano") == []


async def test_no_such_character_is_a_404(
    make_client: ClientFactory, settings: Settings, modes: Path
):
    client = make_client(FakeLLM(), settings=settings)

    res = await client.put("/api/characters/nobody/modes", json={"enabled": ["special"]})

    assert res.status_code == 404


async def test_the_old_profile_mode_no_longer_reaches_the_prompt(
    make_client: ClientFactory, settings: Settings, modes: Path
):
    """The profile's one `special_mode` is kept for the shape alone; each character's own."""
    llm = FakeLLM("<ja>はい</ja><zh>好的</zh>")
    clients = FakeServiceClients()
    clients.judge.judgings = [level(2)]
    clock = FakeClock()
    client = make_client(llm, clients=clients, clock=clock, settings=settings)
    await client.put("/api/profile", json={"special_mode": "succubus"})
    conversation = await start_conversation(client)
    keep(settings.database_path, "producer", 110, clock.now)

    await send_turn(client, conversation, "你今天怎么这么凶")

    assert SUCCUBUS_MARK not in about_now(llm)
