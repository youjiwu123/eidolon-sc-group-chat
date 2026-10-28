"""Speech recognition on Alibaba Cloud Model Studio (阿里云百炼), against a fake DashScope
over a real WebSocket: the frames the service sends on as it hears the user, the audio it
sends DashScope, the region a key is found in, and the failures that leave it unusable."""

from collections.abc import Sequence

import pytest
from pipecat.frames.frames import (
    CancelFrame,
    ErrorFrame,
    Frame,
    InputAudioRawFrame,
    InterimTranscriptionFrame,
    ProposedUserStartedSpeakingFrame,
    ProposedUserStoppedSpeakingFrame,
    TranscriptionFrame,
)
from pipecat.pipeline.worker import PipelineParams
from pipecat.tests.utils import SleepFrame, run_test

import eidolon.bailian
from eidolon.bailian import BailianCheckFailed, BailianSTTService, find_region
from eidolon.config import DEFAULT_BAILIAN_STT_MODEL, BailianRegion
from tests.fakes import FakeDashScope, sentence

KEY = "sk-dashscope"

HEARD = (
    ProposedUserStartedSpeakingFrame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
    ProposedUserStoppedSpeakingFrame,
)


def service(dashscope: FakeDashScope, region: BailianRegion | None = None) -> BailianSTTService:
    """The service on `KEY`, connecting to `dashscope` (see the fixture)."""
    return BailianSTTService(api_key=KEY, model=DEFAULT_BAILIAN_STT_MODEL, region=region)


async def hear(
    stt: BailianSTTService, frames: Sequence[Frame] = (), sample_rate: int = 16000
) -> tuple[list[Frame], list[ErrorFrame]]:
    """Run the service until DashScope has said all it is to say; returns the frames it
    sent on that tell what it heard, and the errors it reported."""
    down, up = await run_test(
        stt,
        frames_to_send=[*frames, SleepFrame(0.3)],
        pipeline_params=PipelineParams(audio_in_sample_rate=sample_rate),
    )
    return [f for f in down if isinstance(f, HEARD)], [f for f in up if isinstance(f, ErrorFrame)]


def described(frames: Sequence[Frame]) -> list[tuple[str, str | None]]:
    return [(type(f).__name__, getattr(f, "text", None)) for f in frames]


def audio(milliseconds: int, sample_rate: int = 16000) -> InputAudioRawFrame:
    samples = sample_rate * milliseconds // 1000
    return InputAudioRawFrame(b"\x01\x00" * samples, sample_rate, 1)


async def test_the_first_words_heard_start_an_utterance_and_its_sentence_ends_it(
    dashscope: FakeDashScope,
):
    dashscope.keys[KEY] = "beijing"
    dashscope.sentences = [
        sentence("", sentence_begin=True),  # DashScope heard a voice, but no words yet
        sentence("现"),
        sentence("", sentence_id=0, heartbeat=True),
        sentence("现在"),
        sentence("现在好。", end=True),
    ]

    heard, errors = await hear(service(dashscope))

    assert described(heard) == [
        ("ProposedUserStartedSpeakingFrame", None),
        ("InterimTranscriptionFrame", "现"),
        ("InterimTranscriptionFrame", "现在"),
        ("TranscriptionFrame", "现在好。"),
        ("ProposedUserStoppedSpeakingFrame", None),
    ]
    assert errors == []


async def test_each_sentence_of_an_utterance_is_a_transcription_of_its_own(
    dashscope: FakeDashScope,
):
    dashscope.keys[KEY] = "beijing"
    dashscope.sentences = [
        sentence("晚上好", sentence_id=1),
        sentence("晚上好。", end=True, sentence_id=1),
        sentence("", sentence_id=2, sentence_begin=True),
        sentence("聞こえて", sentence_id=2),
        sentence("聞こえてますか？", end=True, sentence_id=2),
    ]

    heard, _ = await hear(service(dashscope))

    assert [type(f) for f in heard] == [*HEARD, *HEARD]
    assert [f.text for f in heard if isinstance(f, TranscriptionFrame)] == [
        "晚上好。", "聞こえてますか？"
    ]


async def test_a_sentence_ending_with_words_never_heard_before_starts_and_ends_an_utterance(
    dashscope: FakeDashScope,
):
    dashscope.keys[KEY] = "beijing"
    dashscope.sentences = [sentence("", sentence_begin=True), sentence("嗯。", end=True)]

    heard, _ = await hear(service(dashscope))

    assert described(heard) == [
        ("ProposedUserStartedSpeakingFrame", None),
        ("TranscriptionFrame", "嗯。"),
        ("ProposedUserStoppedSpeakingFrame", None),
    ]


async def test_a_sentence_without_words_is_no_utterance(dashscope: FakeDashScope):
    dashscope.keys[KEY] = "beijing"
    dashscope.sentences = [  # a cough, as far-field recognition hears one
        sentence("", sentence_begin=True),
        sentence("", end=True, stash={"sentence_id": 2, "text": "", "begin_time": -1}),
        sentence("", sentence_id=0, heartbeat=True),
        sentence(" 。", end=True),
    ]

    heard, errors = await hear(service(dashscope))

    assert heard == []
    assert errors == []


async def test_words_that_come_to_nothing_end_the_utterance_without_a_transcription(
    dashscope: FakeDashScope,
):
    dashscope.keys[KEY] = "beijing"
    dashscope.sentences = [sentence("嗯"), sentence("。", end=True)]

    heard, _ = await hear(service(dashscope))

    assert described(heard) == [
        ("ProposedUserStartedSpeakingFrame", None),
        ("InterimTranscriptionFrame", "嗯"),
        ("ProposedUserStoppedSpeakingFrame", None),
    ]


async def test_the_task_asks_for_the_measured_recognition_and_is_finished_at_the_end(
    dashscope: FakeDashScope,
):
    dashscope.keys[KEY] = "beijing"

    await hear(service(dashscope))

    [task] = dashscope.tasks
    assert task.run_task["header"]["action"] == "run-task"
    assert task.run_task["header"]["streaming"] == "duplex"
    payload = task.run_task["payload"]
    assert payload["model"] == DEFAULT_BAILIAN_STT_MODEL
    assert (payload["task_group"], payload["task"], payload["function"]) == (
        "audio", "asr", "recognition"
    )
    assert payload["parameters"] == {
        "format": "pcm",
        "sample_rate": 16000,
        "language_hints": ["zh", "ja"],
        "heartbeat": True,
    }
    assert task.finished


async def test_audio_reaches_dashscope_in_packets_of_100_ms(dashscope: FakeDashScope):
    dashscope.keys[KEY] = "beijing"

    await hear(service(dashscope), [audio(20) for _ in range(12)])

    [task] = dashscope.tasks
    assert [len(packet) for packet in task.audio] == [3200, 3200, 1280]  # the rest, at the end


async def test_audio_is_resampled_to_16_khz(dashscope: FakeDashScope):
    dashscope.keys[KEY] = "beijing"

    await hear(service(dashscope), [audio(20, 48000) for _ in range(50)], sample_rate=48000)

    [task] = dashscope.tasks
    sent = sum(len(packet) for packet in task.audio)
    assert 30000 <= sent <= 32000  # one second at 16 kHz, less what the resampler holds back
    assert all(len(packet) == 3200 for packet in task.audio[:-1])


async def test_silence_is_sent_while_no_audio_comes(
    dashscope: FakeDashScope, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(eidolon.bailian, "KEEPALIVE_TIMEOUT", 0.1)
    dashscope.keys[KEY] = "beijing"

    await hear(service(dashscope), [SleepFrame(0.5)])

    [task] = dashscope.tasks
    assert len(task.audio) >= 2
    assert all(packet == bytes(3200) for packet in task.audio)


async def test_a_key_refused_in_beijing_is_tried_in_singapore(dashscope: FakeDashScope):
    dashscope.keys[KEY] = "singapore"
    dashscope.sentences = [sentence("你好。", end=True)]

    heard, errors = await hear(stt := service(dashscope))

    assert dashscope.handshakes == ["beijing", "singapore"]
    assert [task.region for task in dashscope.tasks] == ["singapore"]
    assert [f.text for f in heard if isinstance(f, TranscriptionFrame)] == ["你好。"]
    assert errors == []
    assert stt.is_usable


async def test_a_key_whose_region_is_known_goes_straight_there(dashscope: FakeDashScope):
    dashscope.keys[KEY] = "singapore"

    await hear(service(dashscope, region="singapore"))

    assert dashscope.handshakes == ["singapore"]


async def test_a_key_refused_in_both_regions_leaves_the_service_unusable(
    dashscope: FakeDashScope,
):
    heard, errors = await hear(stt := service(dashscope))

    assert dashscope.handshakes == ["beijing", "singapore"]
    assert heard == []
    assert errors and "401" in errors[-1].error
    assert not stt.is_usable


async def test_dashscope_down_as_the_call_starts_leaves_the_service_unusable(
    dashscope: FakeDashScope,
):
    dashscope.down = True

    _, errors = await hear(stt := service(dashscope))

    assert errors
    assert not stt.is_usable


async def test_a_task_is_told_to_finish_when_the_call_is_cut_short(dashscope: FakeDashScope):
    dashscope.keys[KEY] = "beijing"

    await run_test(
        service(dashscope), frames_to_send=[SleepFrame(0.2), CancelFrame()], send_end_frame=False
    )

    [task] = dashscope.tasks
    assert task.finished


async def test_a_failed_task_leaves_the_service_unusable(dashscope: FakeDashScope):
    dashscope.keys[KEY] = "beijing"
    dashscope.failure = ("CLIENT_ERROR", "request timeout after 23 seconds.")

    _, errors = await hear(stt := service(dashscope))

    assert errors and "request timeout after 23 seconds." in errors[-1].error
    assert not stt.is_usable


async def test_a_model_not_enabled_leaves_the_service_unusable(dashscope: FakeDashScope):
    dashscope.keys[KEY] = "beijing"
    dashscope.not_enabled.add(DEFAULT_BAILIAN_STT_MODEL)

    _, errors = await hear(stt := service(dashscope))

    assert errors and DEFAULT_BAILIAN_STT_MODEL in errors[-1].error
    assert not stt.is_usable


# Trying a key, as the server starts with the deployer's: a task started and finished,
# with no audio sent, says the key works there and the model is enabled.


@pytest.mark.parametrize("region", ["beijing", "singapore"])
async def test_a_key_is_found_in_its_region(dashscope: FakeDashScope, region: str):
    dashscope.keys[KEY] = region  # pyright: ignore[reportArgumentType]

    found = await find_region(KEY, DEFAULT_BAILIAN_STT_MODEL, )

    assert found == region
    [task] = dashscope.tasks
    assert task.finished and task.audio == []


async def test_a_key_refused_in_both_regions_is_no_key(dashscope: FakeDashScope):
    with pytest.raises(BailianCheckFailed, match="北京、新加坡") as caught:
        await find_region(KEY, DEFAULT_BAILIAN_STT_MODEL, )

    assert "401" in str(caught.value)
    assert dashscope.tasks == []


async def test_a_model_not_enabled_says_where_to_enable_it(dashscope: FakeDashScope):
    dashscope.keys[KEY] = "singapore"
    dashscope.not_enabled.add(DEFAULT_BAILIAN_STT_MODEL)

    with pytest.raises(BailianCheckFailed) as caught:
        await find_region(KEY, DEFAULT_BAILIAN_STT_MODEL, )

    assert f"去阿里云百炼控制台开通 {DEFAULT_BAILIAN_STT_MODEL}" in str(caught.value)
    assert "ModelNotFound" in str(caught.value)


async def test_dashscope_down_is_said_so(dashscope: FakeDashScope):
    dashscope.down = True

    with pytest.raises(BailianCheckFailed, match="连不上阿里云百炼"):
        await find_region(KEY, DEFAULT_BAILIAN_STT_MODEL)
