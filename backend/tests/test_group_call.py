"""群通话的回合：用户说完一句，群里按判断挑出来的人一位一位接话，每一段都带着说话人和她的
音色送进 TTS；插话会把这一轮剩下的丢掉。"""

from pathlib import Path

import pytest
from pipecat.processors.frameworks.rtvi.frames import RTVIServerMessageFrame

from eidolon import group_chat
from eidolon.call import SegmentCompleteFrame, SegmentTextFrame
from eidolon.characters import Character
from eidolon.group_call import GroupVoicing
from eidolon.store import Store
from tests.fakes import FakeLLM


def speaker(character_id: str, name: str, voice: str) -> Character:
    return Character(
        id=character_id,
        name=name,
        intro="",
        voice_id=voice,
        sheet="",
        avatar=None,
        color="#ffffff",
    )


@pytest.fixture
def roster() -> dict[str, Character]:
    return {
        "mano": speaker("mano", "真乃", "voice-mano"),
        "kogane": speaker("kogane", "恋钟", "voice-kogane"),
    }


@pytest.fixture
def group(tmp_path: Path) -> tuple[Store, str]:
    store = Store(tmp_path / "eidolon.db")
    group_chat.ensure_schema(store._db)
    user = store.create_user("producer")
    created = group_chat.create_group(store, user.id, ("mano", "kogane"))
    yield store, created.id
    store.close()


async def say(
    group: tuple[Store, str], roster: dict[str, Character], said: str, emotions: object = None
) -> list:
    store, group_id = group
    chat = FakeLLM(
        ["<ja>こんばんは</ja><zh>晚上好</zh>"],
        ["<ja>うん、聞こえるよ</ja><zh>嗯，听得见</zh>"],
    )
    voicing = GroupVoicing(
        store=store,
        group=group_chat.get_group(store, group_id),
        roster=roster,
        chat=chat,
        emotions=emotions,
    )
    return [frame async for frame in voicing.say(said)]


class Feelings:
    """A judge that always says the same: happy, sure, no nod."""

    async def answer(self, said: object, min_probability: float | None = None) -> tuple:
        return ("happy", None, 0.92)


async def test_each_segment_is_said_by_one_of_the_group_in_her_voice(group, roster) -> None:
    frames = await say(group, roster, "こんばんは")

    said = [frame for frame in frames if isinstance(frame, SegmentTextFrame)]
    assert said, "没有一段被送进 TTS"
    for frame in said:
        assert frame.speaker in {"mano", "kogane"}
        assert frame.voice == f"voice-{frame.speaker}"


async def test_each_reply_is_numbered_on_its_own_and_its_segments_completed(group, roster) -> None:
    frames = await say(group, roster, "こんばんは")

    said = [frame for frame in frames if isinstance(frame, SegmentTextFrame)]
    numbers = sorted({frame.reply for frame in said})
    assert numbers == list(range(1, len(numbers) + 1))
    for number in numbers:
        segments = [frame.segment for frame in said if frame.reply == number]
        assert segments == list(range(len(segments)))
        completed = [
            frame.segment
            for frame in frames
            if isinstance(frame, SegmentCompleteFrame) and frame.reply == number
        ]
        assert completed == segments


async def test_the_user_and_her_replies_are_written_into_the_group(group, roster) -> None:
    store, group_id = group
    frames = await say(group, roster, "こんばんは")

    history = group_chat.messages_of(store, group_id)
    assert history[0].role == "user"
    assert history[0].segments[0].zh == "こんばんは"
    replies_in_history = history[1:]
    assert 1 <= len(replies_in_history) <= 2
    assert all(message.role == "character" for message in replies_in_history)
    replies = {
        frame.speaker for frame in frames if isinstance(frame, SegmentTextFrame)
    }
    assert replies_in_history[0].speaker_id in replies


def messages(frames: list, kind: str) -> list[dict]:
    return [
        frame.data
        for frame in frames
        if isinstance(frame, RTVIServerMessageFrame) and frame.data.get("type") == kind
    ]


async def test_each_line_is_sent_before_its_audio(group, roster) -> None:
    frames = await say(group, roster, "こんばんは")

    lines = messages(frames, "line")
    assert lines, "没有一句台词被送到浏览器"
    for line in lines:
        assert line["speaker"] in roster
        assert line["ja"]
        first_audio = next(
            index
            for index, frame in enumerate(frames)
            if isinstance(frame, SegmentTextFrame) and frame.reply == line["reply"]
        )
        line_at = frames.index(next(f for f in frames if isinstance(f, RTVIServerMessageFrame) and f.data == line))
        assert line_at < first_audio


async def test_the_line_carries_her_mood_when_it_can_be_judged(group, roster) -> None:
    frames = await say(group, roster, "こんばんは", Feelings())

    feelings = messages(frames, "emotion")
    assert feelings, "没有一句带着语气"
    for feeling in feelings:
        assert feeling["speaker"] in roster
        assert feeling["emotion"] == "happy"
        assert feeling["strength"] > 0.6

    lines = messages(frames, "line")
    assert [line["speaker"] for line in lines] == [feeling["speaker"] for feeling in feelings]
