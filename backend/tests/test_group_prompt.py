"""群聊的提示词：轮到她时，只有她自己开着的特殊档进提示词，别人的不进来；文字回合的
「动作和心声」约定也照旧告诉她。"""

from eidolon import group_chat
from eidolon.characters import Character
from eidolon.reply_format import MODE_FIRST, TEXT_ACTIONS


def speaker(character_id: str, name: str) -> Character:
    return Character(
        id=character_id,
        name=name,
        intro="",
        voice_id=f"voice-{character_id}",
        sheet=f"{name} 的人设",
        avatar=None,
        color="#ffffff",
    )


def prompt_of(
    who: Character,
    members: list[Character],
    modes: dict[str, str],
    place: str | None = None,
) -> str:
    messages = group_chat.group_prompt(who, members, [], "你好", modes=modes, place=place)
    return messages[0].content


def test_a_mode_goes_to_the_one_who_has_it_on_and_comes_last():
    mano, kogane = speaker("mano", "真乃"), speaker("kogane", "恋钟")
    modes = {"mano": "你现在是夜之魅魔。", "kogane": "你现在是教官。"}

    content = prompt_of(mano, [mano, kogane], modes)

    assert MODE_FIRST in content
    assert "你现在是夜之魅魔。" in content
    assert "你现在是教官。" not in content
    # 群里要读的东西多，档放在最后才压得住；动作约定在它前面。
    assert content.index(TEXT_ACTIONS) < content.index("你现在是夜之魅魔。")
    assert content.rstrip().endswith("你现在是夜之魅魔。")
    # 开着档的时候不讲群里的客套，只留「别替别人说话」这些必须的。
    assert "压过群里的客套" in content
    assert "一轮通常一两句" not in content


def test_a_mode_speaker_still_does_not_speak_for_others():
    mano, kogane = speaker("mano", "真乃"), speaker("kogane", "恋钟")
    modes = {"mano": "你现在是夜之魅魔。"}

    content = prompt_of(mano, [mano, kogane], modes)

    assert "不要在回复里替任何人说话" in content
    assert "不要在回复里替任何人说话" in prompt_of(mano, [mano, kogane], {})


def test_without_a_mode_nothing_of_it_is_said_but_actions_still_are():
    mano, kogane = speaker("mano", "真乃"), speaker("kogane", "恋钟")

    content = prompt_of(mano, [mano, kogane], {})

    assert MODE_FIRST not in content
    assert TEXT_ACTIONS in content


def test_a_thought_reaches_only_the_one_who_can_read_minds():
    mano = speaker("mano", "真乃")
    kogane = speaker("kogane", "恋钟")
    thought = "其实我今天特别难过"

    def prompt_for(who, modes):
        messages = group_chat.group_prompt(
            who, [mano, kogane], [], f"“{thought}”", modes=modes
        )
        return "\n".join(message.content for message in messages)

    # mano 的档写明她能听见心声；kogane 没有。
    reading_mode = {"mano": "你听得见制作人心里的话：他用“”写的心声，你能听见。"}
    assert thought in prompt_for(mano, reading_mode)
    assert thought not in prompt_for(kogane, reading_mode)
    assert "他张了张嘴，没有出声" in prompt_for(kogane, reading_mode)


def test_a_place_is_said_in_the_system_prompt():
    mano, kogane = speaker("mano", "真乃"), speaker("kogane", "恋钟")
    place = "你们现在在「事务所休息室」（沙发、茶水间）。"

    messages = group_chat.group_prompt(
        mano, [mano, kogane], [], "你好", modes={}, place=place
    )

    assert messages[0].role == "system"
    assert place in messages[0].content
    # 它是一整句现成的话，不和别的段落黏在一起。
    assert place in messages[0].content.split("\n\n")


def test_without_a_place_nothing_of_it_is_said():
    mano, kogane = speaker("mano", "真乃"), speaker("kogane", "恋钟")
    place = "你们现在在「事务所休息室」（沙发、茶水间）。"

    assert place not in prompt_of(mano, [mano, kogane], {})
