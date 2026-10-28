"""A call's speech service voicing more than one character: each segment can be said in a
different voice, which is what a group call needs — Fish Audio takes the voice with the
session it opens, so a session opened for another voice is dropped and the next segment
opens its own."""

from typing import Any

import ormsgpack
from pipecat.services.fish.tts import FishAudioTTSService

from eidolon.call import FishTTS, SegmentTextFrame, segment_playing


class FakeSocket:
    """A Fish Audio connection that keeps the voice each session was started for."""

    def __init__(self, started: list[dict[str, Any]]) -> None:
        self.started = started
        self.closed = False

    async def send(self, payload: bytes) -> None:
        message = ormsgpack.unpackb(payload)
        if isinstance(message, dict) and message.get("event") == "start":
            self.started.append(message["request"])

    async def close(self) -> None:
        self.closed = True


def service(started: list[dict[str, Any]], voice: str = "voice-a") -> FishTTS:
    """Her speech service, its connections kept in `started` instead of going to Fish Audio."""
    speech = FishTTS(
        api_key="k",
        sample_rate=24000,
        settings=FishAudioTTSService.Settings(voice=voice, model="drama-3"),
    )

    async def connect(url: str, additional_headers: dict[str, str] | None = None) -> FakeSocket:
        return FakeSocket(started)

    speech._websocket_connect = connect  # type: ignore[method-assign]
    return speech


async def test_a_session_starts_with_her_own_voice() -> None:
    started: list[dict[str, Any]] = []

    await service(started)._open()

    assert started[-1]["reference_id"] == "voice-a"


async def test_speaking_as_another_character_opens_the_next_session_in_their_voice() -> None:
    started: list[dict[str, Any]] = []
    speech = service(started)

    await speech.speak_as("voice-b")
    await speech._open()

    assert started[-1]["reference_id"] == "voice-b"


async def test_a_spare_opened_for_another_voice_is_dropped() -> None:
    import asyncio

    started: list[dict[str, Any]] = []
    speech = service(started)

    spare = asyncio.create_task(speech._open())
    await spare
    speech._spare = spare

    await speech.speak_as("voice-c")

    assert speech._spare is None
    await speech._open()
    assert started[-1]["reference_id"] == "voice-c"


async def test_the_segment_being_voiced_is_left_alone() -> None:
    started: list[dict[str, Any]] = []
    speech = service(started)
    session = FakeSocket(started)
    speech._session = session  # type: ignore[assignment]

    await speech.speak_as("voice-d")

    assert session.closed is False
    assert speech._settings.voice == "voice-d"


def test_a_segment_carries_its_speaker_and_her_voice() -> None:
    frame = SegmentTextFrame(text="こんばんは", reply=1, segment=0, speaker="mano", voice="voice-a")

    assert (frame.speaker, frame.voice) == ("mano", "voice-a")
    # 单聊的段不带说话人：还是通话那位角色自己的声音
    assert SegmentTextFrame(text="こんばんは", reply=1, segment=0).speaker is None


def test_segment_playing_tells_the_browser_who_speaks() -> None:
    data = segment_playing(2, 1, speaker="kogane").message["data"]

    assert data["type"] == "segment-playing"
    assert data["speaker"] == "kogane"
    # 没有说话人时消息和以前一模一样，不多一个字段
    assert "speaker" not in segment_playing(2, 1).message["data"]
