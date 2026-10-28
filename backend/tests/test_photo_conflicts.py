"""The check that drops photo tags conflicting with the scene, before a photo is generated."""

import pytest

from eidolon.characters import Character
from eidolon.llm import LLMError
from eidolon.photo_prompt import (
    analyze_conflicts,
    image_prompt,
    parse_conflict,
    read_tag,
)
from tests.fakes import FakeLLM


def character() -> Character:
    return Character(
        id="mano",
        name="櫻木真乃",
        intro="",
        voice_id="voice",
        sheet="",
        avatar=None,
        color="#ffffff",
        photo_tag="sakuragi mano",
        photo_appearance="brown hair, medium hair, brown eyes",
    )


TAG = (
    "shot: selfie\nframing: upper body\nplace: cafe, sparkle\noutfit: casual\n"
    "action: smile, sparkling"
)


def test_only_the_tags_asked_are_read_from_the_answer():
    assert parse_conflict('{"drop": ["Sparkle", "starry_sky", "sparkle"]}') == (
        "sparkle",
        "starry sky",
    )
    assert parse_conflict('好的：\n```json\n{"drop": []}\n```') == ()


@pytest.mark.parametrize(
    "answer", ["", "没有冲突", "[]", '{"drop": "sparkle"}', '{"memories": []}', "{"]
)
def test_an_answer_that_is_not_the_json_object_is_none(answer: str):
    assert parse_conflict(answer) is None


def test_the_tags_dropped_leave_her_fields_and_style_but_not_who_she_is():
    tag = read_tag(TAG)
    prompt = image_prompt(
        character(), tag, "artist:someone, watercolor, sparkle", ("sparkle", "sparkling")
    )

    assert "sparkle" not in prompt.positive
    assert "sparkling" not in prompt.positive
    assert "cafe" in prompt.positive
    assert "watercolor" in prompt.positive
    assert prompt.positive.startswith("1girl, solo, sakuragi mano, idolmaster shiny colors")
    assert "brown hair, medium hair, brown eyes" in prompt.positive
    assert "rating:general" in prompt.positive
    assert "masterpiece" in prompt.positive


async def test_the_chat_model_is_asked_and_its_drops_come_back():
    chat = FakeLLM(['{"drop": ["sparkle"]}'])

    assert await analyze_conflicts(
        chat, character(), read_tag(TAG), "artist:someone, sparkle", TAG
    ) == ("sparkle",)
    assert len(chat.prompts) == 1
    asked = "\n".join(message.content for message in chat.prompts[0])
    assert "cafe" in asked and "sparkle" in asked and "她写的原文" in asked


async def test_a_failing_check_keeps_the_photo_going():
    chat = FakeLLM(LLMError("the chat model is down"))

    assert await analyze_conflicts(chat, character(), read_tag(TAG), "", TAG) == ()
