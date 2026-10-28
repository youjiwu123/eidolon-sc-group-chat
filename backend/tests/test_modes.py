"""特殊档等模式：表在 `characters/modes.toml`，加载器在 `modes.py`，只有好感最高档
（love）且用户选中的 id 存在时才追加它的 prompt；空串、未知 id、其他档位都一个字不加。
文字回合和通话回合走同一段 prompt。"""

from dataclasses import replace
from pathlib import Path

import pytest

from eidolon.config import Settings
from eidolon.modes import load_modes
from tests.conftest import CharacterConfig, ClientFactory
from tests.fakes import (
    FAKE_JUDGE,
    FakeClock,
    FakeLLM,
    FakeServiceClients,
    context_of,
    level,
)
from tests.test_affinity import keep
from tests.test_affinity_prompt import about_now
from tests.test_call_turns import MANO_REPLY, CallUnderTest, spoken
from tests.test_text_turn import send_turn, start_conversation

SPECIAL_MARK = "你现在处在和制作人的「特殊档」"
STERN_MARK = "你现在对制作人很严厉，像一个不近人情的教官"
SUCCUBUS_MARK = "你现在以「夜之魅魔」的样子出现在制作人面前"

MODE_TABLE = """\
[[modes]]
id = "special"
name = "特殊档"
description = "特殊档的说明"
prompt = \"\"\"你现在处在和制作人的「特殊档」：测试用的固定文案。
- 第二条。\"\"\"

[[modes]]
id = "stern"
name = "教官"
description = "教官的说明"
prompt = \"\"\"你现在对制作人很严厉，像一个不近人情的教官：测试用的固定文案。\"\"\"

[[modes]]
id = "succubus"
name = "夜之魅魔"
description = "夜之魅魔的说明"
prompt = \"\"\"你现在以「夜之魅魔」的样子出现在制作人面前：测试用的固定文案。\"\"\"
"""
"""A small mode table: the tests look for the beginnings, not the whole prompts."""


@pytest.fixture
def modes(characters: CharacterConfig) -> Path:
    path = characters.directory / "modes.toml"
    path.write_text(MODE_TABLE, encoding="utf-8")
    return path


@pytest.fixture
def settings(settings: Settings) -> Settings:
    """With the judge model, and affinity on in `.env`."""
    return replace(settings, judge=FAKE_JUDGE, affinity_and_gifts=True)


def test_a_missing_mode_table_is_an_empty_table(tmp_path: Path):
    assert load_modes(tmp_path / "modes.toml") == {}


def test_a_broken_mode_table_says_which_file_and_why(tmp_path: Path):
    path = tmp_path / "modes.toml"
    path.write_text('[[modes]]\nid = "special"\nname = "特殊档"\n', encoding="utf-8")

    with pytest.raises(RuntimeError, match="缺少 prompt"):
        load_modes(path)


def test_a_duplicate_mode_id_is_refused(tmp_path: Path):
    path = tmp_path / "modes.toml"
    path.write_text(
        MODE_TABLE
        + '\n[[modes]]\nid = "special"\nname = "又一个"\nprompt = "重复"\n',
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="id「special」重复"):
        load_modes(path)


def test_modes_load_by_id_with_their_text(modes: Path):
    loaded = load_modes(modes)

    assert list(loaded) == ["special", "stern", "succubus"]
    assert loaded["special"].name == "特殊档"
    assert loaded["special"].description == "特殊档的说明"
    assert loaded["special"].prompt.startswith(SPECIAL_MARK)
    assert loaded["stern"].prompt.startswith(STERN_MARK)
    assert loaded["succubus"].prompt.startswith(SUCCUBUS_MARK)


def test_the_repository_table_has_the_deployments_modes():
    loaded = load_modes(Path(__file__).parents[2] / "characters" / "modes.toml")

    assert {"special", "stern", "succubus"} <= set(loaded)
    assert loaded["special"].prompt.startswith(SPECIAL_MARK)
    assert "被写出来的角色" in loaded["special"].prompt
    assert loaded["stern"].prompt.startswith(STERN_MARK)
    assert loaded["succubus"].prompt.startswith(SUCCUBUS_MARK)
    # 部署者自己定的那句（当初的「不描写身体、不写露骨内容」被改成相反的写法了）。
    assert "会描写身体、也会写露骨内容" in loaded["succubus"].prompt


async def prompted(
    make_client: ClientFactory,
    settings: Settings,
    *,
    mode: str,
    kept: float,
) -> str:
    """One typed turn, her affinity `kept` as it begins, the profile's mode `mode`; what
    the prompt says about now."""
    llm = FakeLLM("<ja>はい</ja><zh>好的</zh>")
    clients = FakeServiceClients()
    clients.judge.judgings = [level(2)]
    clock = FakeClock()
    client = make_client(llm, clients=clients, clock=clock, settings=settings)
    await client.put("/api/characters/mano/modes", json={"enabled": [mode] if mode else []})
    conversation = await start_conversation(client)
    keep(settings.database_path, "producer", kept, clock.now)
    await send_turn(client, conversation, "你今天怎么这么凶")
    return about_now(llm)


@pytest.mark.parametrize(
    ("mode", "kept", "mark"),
    [
        ("special", 110, SPECIAL_MARK),
        ("special", 60, SPECIAL_MARK),  # 好感各档都追加，不再只有爱意档
        ("special", 10, SPECIAL_MARK),
        ("", 110, None),
        ("stern", 110, STERN_MARK),
    ],
    ids=[
        "special-at-love",
        "special-at-close",
        "special-at-cold",
        "empty-at-love",
        "stern-at-love",
    ],
)
async def test_a_typed_turn_gets_only_an_existing_mode_and_at_any_tier(
    make_client: ClientFactory,
    settings: Settings,
    modes: Path,
    mode: str,
    kept: float,
    mark: str | None,
):
    section = await prompted(make_client, settings, mode=mode, kept=kept)

    assert (mark in section) if mark else ("特殊档" not in section and "教官" not in section)


async def test_a_call_gets_the_mode_too(
    make_client: ClientFactory, settings: Settings, modes: Path
):
    llm = FakeLLM(MANO_REPLY)
    client = make_client(llm, clock=FakeClock(), settings=settings)
    await client.put("/api/characters/mano/modes", json={"enabled": ["special"]})
    conversation = await start_conversation(client)
    keep(settings.database_path, "producer", 110, FakeClock().now)
    call = CallUnderTest(settings, client, conversation)
    try:
        await call.run(llm, [spoken("你今天怎么这么凶")], affinity=[level(2)])
    finally:
        call.close()

    assert SPECIAL_MARK in context_of(llm.prompts[-1])


async def test_the_modes_endpoint_lists_names_and_descriptions_not_prompts(
    make_client: ClientFactory, modes: Path
):
    res = await make_client(FakeLLM()).get("/api/modes")

    assert res.status_code == 200
    assert res.json() == [
        {"id": "special", "name": "特殊档", "description": "特殊档的说明"},
        {"id": "stern", "name": "教官", "description": "教官的说明"},
        {"id": "succubus", "name": "夜之魅魔", "description": "夜之魅魔的说明"},
    ]
    assert "测试用的固定文案" not in res.text
