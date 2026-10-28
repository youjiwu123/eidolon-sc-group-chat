"""Group calls (DESIGN.md「群聊语音房」的下一步): what the user says in a call is answered by
several of the group, one after another, each segment voiced in the voice of the one who says
it — `call.SegmentTextFrame` carries `speaker` and `voice`, so `call.FishTTS` switches voice by
itself and the browser's `segment-playing` message says who speaks.

`GroupVoicing` is the turn itself, as the frames that voice it (no pipeline needed, so it can be
tested on its own); `GroupTurns` is the thin frame processor a call's pipeline would use in place
of `call.CallTurns`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Mapping

from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    Frame,
    InterruptionFrame,
    LLMFullResponseStartFrame,
    TranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.processors.frameworks.rtvi.frames import RTVIServerMessageFrame

from eidolon import group_chat
from eidolon.call import SegmentCompleteFrame, SegmentTextFrame
from eidolon.emotion import EmotionJudging, SaidSegment, SegmentToJudge
from eidolon.characters import Character
from eidolon.group_chat import Group
from eidolon.reply_format import Segment
from eidolon.store import Store

log = logging.getLogger(__name__)


class GroupVoicing:
    """What the group says to what the user said, as the frames that voice it, in order.

    The user's words go into the group's history first, then the judge picks who answers (the
    same `group_chat.choose_speakers` a text turn uses); each of them is generated once, and
    every segment is pushed as `SegmentTextFrame` tagged with her and her voice, followed by
    `SegmentCompleteFrame` so TTS voices it at once. Replies are numbered from 1 within the
    call, as a single call's are."""

    def __init__(
        self,
        store: Store,
        group: Group,
        roster: Mapping[str, Character],
        chat: object,
        picker: object | None = None,
        emotions: EmotionJudging | None = None,
    ) -> None:
        self._store = store
        self._group = group
        self._roster = roster
        self._chat = chat
        self._picker = picker
        self._emotions = emotions
        self._reply = 0

    async def say(self, said: str) -> AsyncIterator[Frame]:
        members = [self._roster[cid] for cid in self._group.participants if cid in self._roster]
        if not members:
            return
        group_chat.append_message(self._store, self._group.id, "user", (Segment("", said),))
        history = group_chat.messages_of(self._store, self._group.id)
        speakers = await group_chat.choose_speakers(members, history, said, self._picker)  # type: ignore[arg-type]
        for speaker in speakers:
            try:
                segments = await group_chat.speak(speaker, members, history, said, self._chat)  # type: ignore[arg-type]
            except Exception:
                log.exception("群通话：%s 没能接话", speaker.id)
                continue
            if not segments:
                continue
            message = group_chat.append_message(
                self._store, self._group.id, "character", segments, speaker.id
            )
            history.append(message)
            self._reply += 1
            # 浏览器那边一个格子一位：先说这一句是谁说的、说了什么（字幕），再说给 TTS。
            yield RTVIServerMessageFrame(
                data={
                    "type": "line",
                    "reply": self._reply,
                    "speaker": speaker.id,
                    "ja": " ".join(segment.ja for segment in segments),
                    "zh": "".join(segment.zh for segment in segments),
                }
            )
            yield LLMFullResponseStartFrame()
            for index, segment in enumerate(segments):
                yield SegmentTextFrame(
                    segment.ja,
                    self._reply,
                    index,
                    speaker=speaker.id,
                    voice=speaker.voice_id,
                )
                yield SegmentCompleteFrame(self._reply, index)
            if self._emotions is not None:
                # 这一段她是什么语气：先把她的声音推进去，再赶着判一下，判出来再把表情发给格子
                # （判不出、超时就不发，她那边还是上一张脸）。判得慢也不耽误她开口。
                judged = await self._emotions.answer(
                    SegmentToJudge(
                        character=speaker,
                        user_said=said,
                        before=(),
                        segment=SaidSegment(
                            ja="\n".join(segment.ja for segment in segments),
                            zh="".join(segment.zh for segment in segments),
                        ),
                    ),
                    0.3,
                )
                if judged is not None:
                    emotion, nod, strength = judged
                    yield RTVIServerMessageFrame(
                        data={
                            "type": "emotion",
                            "reply": self._reply,
                            "speaker": speaker.id,
                            "emotion": emotion,
                            "nod": nod,
                            "strength": round(strength, 2),
                        }
                    )


class GroupTurns(FrameProcessor):
    """A group call's turns: what the user says is answered by the group, one speaker after
    another. Talking over her drops the rest of that turn and takes up the new words."""

    def __init__(
        self,
        voicing: GroupVoicing,
        max_turns: int | None = None,
        on_exhausted: object | None = None,
    ) -> None:
        super().__init__()
        self._voicing = voicing
        self._turn: asyncio.Task[None] | None = None
        self._turns = 0
        self._max_turns = max_turns
        self._on_exhausted = on_exhausted

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TranscriptionFrame):
            self._turns += 1
            if self._max_turns is not None and self._turns > self._max_turns:
                # 这通电话的回合用完了：不再接话，交给通话自己去挂断
                await self._stop_turn()
                if self._on_exhausted is not None:
                    await self._on_exhausted()  # type: ignore[operator]
                return
            await self._stop_turn()
            self._turn = self.create_task(self._say(frame.text))
        elif isinstance(frame, InterruptionFrame):
            await self._stop_turn()
            await self.push_frame(frame, direction)
        elif isinstance(frame, (EndFrame, CancelFrame)):
            await self._stop_turn()
            await self.push_frame(frame, direction)
        else:
            await self.push_frame(frame, direction)

    async def _say(self, said: str) -> None:
        async for frame in self._voicing.say(said):
            await self.push_frame(frame)

    async def _stop_turn(self) -> None:
        turn, self._turn = self._turn, None
        if turn is None or turn.done():
            return
        await self.cancel_task(turn)
