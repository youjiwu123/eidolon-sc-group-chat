"""The adult-content switch and its age gate (docs/explicit.md).

The switch is deployer-level: `.env`'s `EIDOLON_EXPLICIT_CONTENT`, overridable in the admin
console, never a user setting. The age gate is code, not data: a character whose `age`
is under 18, or whose age is unknown, is kept out whatever the switch says. No line at
all is written for a minor, neither the adult one nor the default "do not write it" one.
"""

from dataclasses import replace
from pathlib import Path

import pytest

from eidolon.characters import Character, CharacterConfigError, load_characters
from eidolon.config import Settings
from eidolon.engine import ConversationEngine
from eidolon.explicit import ALLOWED_PROMPT, DEFAULT_PROMPT, explicit_prompt
from tests.conftest import ClientFactory
from tests.fakes import FakeLLM

REPO_CHARACTERS = Path(__file__).parents[2] / "characters"

AGES = {
    "mano": 16, "hiori": 15, "meguru": 16, "kogane": 19, "mamimi": 18,
    "sakuya": 18, "yuika": 19, "kiriko": 17, "toru": 17, "madoka": 17,
    "koito": 16, "hinana": 15, "nichika": 16, "mikoto": 24, "asahi": 14,
    "fuyuko": 19, "mei": 18, "kaho": 12, "chiyoko": 17, "juri": 17,
    "rinze": 16, "natsuha": 20, "amana": 17, "tenka": 17, "chiyuki": 23,
    "luca": 20, "hana": 18, "haruki": 17, "hazuki": 22,
}
"""The ages read from `characters/facts/<id>.md`'s 「基本信息」, checked against the
official setting."""


def character(cid: str, age: int | None) -> Character:
    return Character(
        id=cid, name="测试", intro="", voice_id="voice", sheet="", avatar=None,
        color="#ffffff", age=age,
    )


def write_character(tmp_path: Path, extra: str = "") -> Path:
    """A minimal character configuration, with `extra` appended to its one entry."""
    directory = tmp_path / "characters"
    (directory / "sheets").mkdir(parents=True)
    (directory / "sheets" / "test.md").write_text("# 人设", encoding="utf-8")
    path = directory / "characters.toml"
    path.write_text(
        '[[characters]]\nid = "test"\nname = "テスト"\nintro = ""\n'
        'voice_id = "voice"\nsheet = "sheets/test.md"\ncolor = "#ffffff"\n' + extra,
        encoding="utf-8",
    )
    return path


def test_a_minor_gets_no_explicit_prompt_even_when_the_switch_is_on():
    """The key case: age 16 and allowed, yet no line at all."""
    assert explicit_prompt(character("hiori", 16), allowed=True) is None


def test_an_unknown_age_gets_no_explicit_prompt():
    assert explicit_prompt(character("someone", None), allowed=True) is None


def test_an_adult_is_told_not_to_write_it_when_the_switch_is_off():
    prompt = explicit_prompt(character("chiyuki", 23), allowed=False)
    assert prompt is not None and "不写性描写" in prompt


def test_an_adult_is_told_the_adult_setting_when_the_switch_is_on():
    prompt = explicit_prompt(character("chiyuki", 23), allowed=True)
    assert prompt is not None and "成人向" in prompt


def test_mamimi_is_an_adult_and_an_edited_adult_age_still_gets_the_line():
    """Facts say 18; an adult age of 30 is allowed too."""
    assert explicit_prompt(character("mamimi", 18), allowed=True) == ALLOWED_PROMPT
    assert explicit_prompt(character("mamimi", 30), allowed=True) == ALLOWED_PROMPT


def test_the_switch_is_off_by_default_and_env_one_turns_it_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CHAT_LLM_BASE_URL", "https://llm.example.com/v1")
    monkeypatch.setenv("CHAT_LLM_API_KEY", "sk-deployer")
    monkeypatch.setenv("CHAT_LLM_MODEL", "deployer-model")
    monkeypatch.delenv("EIDOLON_EXPLICIT_CONTENT", raising=False)

    assert Settings.from_env().explicit_content is False

    monkeypatch.setenv("EIDOLON_EXPLICIT_CONTENT", "1")
    assert Settings.from_env().explicit_content is True

    monkeypatch.setenv("EIDOLON_EXPLICIT_CONTENT", "0")
    assert Settings.from_env().explicit_content is False


async def test_the_admin_config_override_wins_over_env(
    make_client: ClientFactory, settings: Settings
):
    """The admin console may override `.env`, as for the other deployer-level switches."""
    client = make_client(FakeLLM(), settings=replace(settings, explicit_content=False))
    backend = client._transport.app.state.backend  # pyright: ignore[reportAttributeAccessIssue]

    assert backend.config.explicit_content is False
    await backend.config.save("explicit_content", {"enabled": True})
    assert backend.config.explicit_content is True

    await backend.config.restore("explicit_content")
    assert backend.config.explicit_content is False


def test_age_is_read_as_an_integer(tmp_path: Path):
    loaded = load_characters(write_character(tmp_path, "age = 22\n"))

    assert loaded["test"].age == 22


def test_a_missing_age_is_unknown(tmp_path: Path):
    loaded = load_characters(write_character(tmp_path))

    assert loaded["test"].age is None


@pytest.mark.parametrize("value", ["0", "-1", '"16"', "true"])
def test_an_invalid_age_is_refused_saying_what_is_wrong(tmp_path: Path, value: str):
    with pytest.raises(CharacterConfigError, match="age"):
        load_characters(write_character(tmp_path, f"age = {value}\n"))


def test_every_repository_character_has_the_age_her_facts_say():
    loaded = load_characters(REPO_CHARACTERS / "characters.toml")

    assert len(loaded) == 29
    assert {cid: c.age for cid, c in loaded.items()} == AGES
    assert explicit_prompt(character("hazuki", 22), allowed=False) == DEFAULT_PROMPT


def test_the_turn_prompt_carries_the_line_before_what_closing_found():
    engine = object.__new__(ConversationEngine)
    engine._explicit_content = lambda: True

    prompt = engine._prompt(
        character("chiyuki", 23), None, "producer", [], {}, ["this turn"], ["closing"], "hello",
        None,
    )

    context = prompt[-2].content
    assert "成人向" in context
    assert context.index("成人向") < context.index("closing")


def test_a_minor_turn_prompt_gets_no_adult_line_even_with_the_switch_on():
    engine = object.__new__(ConversationEngine)
    engine._explicit_content = lambda: True

    prompt = engine._prompt(
        character("kaho", 12), None, "producer", [], {}, ["this turn"], ["closing"], "hello",
        None,
    )

    context = prompt[-2].content
    assert "成人向" not in context
    assert "不写性描写" not in context

