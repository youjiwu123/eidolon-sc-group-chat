"""She ends the conversation (GLOSSARY.md「已结束的对话」): outside calls, the typed turn that
has what the conversation's latest typed turns took off her affinity add up to too much, that
has the user out of line a second time in those turns (this one among them), or that cools
her into a cooldown has her told to say she does not want to talk any more; once it is
recorded, the「她结束了对话」event comes after it in the record and `done` carries it, and,
for a cooldown, till when as ever. Halfway to too much, she warns the user first, once till
it eases, that she will not want to talk should it go on: never of hanging up. From then on
the conversation can only be read: a turn in it is rejected, leaving no record and counting
towards nothing, as is one under way as it is ended elsewhere; a call into it is refused,
and she hangs up one in it as she ends it. Neither the cooldown over nor a reset card opens
it again. The conversation list still shows her last line.

What a call's turns took counts in that call alone, never in the conversation's typed turns,
and neither her hanging up a call nor a cooldown begun in one ends the conversation; turns
recorded before typed turns were counted, a turn the judge model could not judge, count for
nothing, though the latter takes its place among the latest. Off, she never ends one.

Driven through the backend's external API, the judge model faked turn by turn; calls with a
browser over a real WebRTC connection."""

import asyncio
import sqlite3
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from eidolon.config import Settings, UsageLimits
from tests.browser import TIMEOUT, open_browser
from tests.conftest import ClientFactory
from tests.fakes import (
    FAKE_JUDGE,
    FakeClock,
    FakeLLM,
    FakeRandom,
    FakeServiceClients,
    FakeSpeech,
    Judging,
    level,
)
from tests.test_affinity import keep, status
from tests.test_affinity_cooldown import PARTING, UNTIL, ask_before_calling
from tests.test_affinity_prompt import about_now
from tests.test_conversation_events import record, shape
from tests.test_gift_backpack import RESET_CARD
from tests.test_reset_cards import USE
from tests.test_she_hangs_up import HANGING_UP, OUT_OF_LINE, say
from tests.test_she_hangs_up import WARNING as HANG_UP_WARNING
from tests.test_text_turn import done_of, send_turn, start_conversation

REPLY = ["<ja>はい</ja><zh>好的</zh>"]
WARNING = "制作人再这样下去你就不想聊了"
ENDED = "她已经结束了对话"
HURT = level(1)
"""Hurting her a little: six in a row end the conversation, the third warns the user."""
FINE = level(2)


@pytest.fixture
def settings(settings: Settings) -> Settings:
    """With the judge model, and affinity on in `.env`."""
    return replace(settings, judge=FAKE_JUDGE, affinity_and_gifts=True)


def client_judging(
    make_client: ClientFactory, judgings: list[Judging], **kwargs
) -> tuple[httpx.AsyncClient, FakeLLM]:
    """A client whose judge model judges the turns as `judgings` says, one reply for each."""
    clients = FakeServiceClients()
    clients.judge.judgings = list(judgings)
    llm = FakeLLM(*[REPLY] * len(judgings))
    return make_client(llm, clients=clients, clock=FakeClock(), **kwargs), llm


async def say_each(client: httpx.AsyncClient, conversation: str, n: int) -> list[list[dict]]:
    """`n` typed turns, one after another; each one's events."""
    return [await send_turn(client, conversation, f"第{i}句") for i in range(n)]


def ended_by(turn: list[dict]) -> bool:
    return done_of(turn)["ended"] is not None


async def test_hurt_turn_after_turn_she_warns_once_then_ends_the_conversation_after_her_last_line(
    make_client: ClientFactory, settings: Settings
):
    client, llm = client_judging(make_client, [HURT] * 6)
    conversation = await start_conversation(client)

    turns = await say_each(client, conversation, 6)
    recorded = await record(client, conversation)
    listed = (await client.get("/api/conversations/latest")).json()

    assert [WARNING in about_now(llm, n) for n in range(6)] == [False, False, True] + [False] * 3
    assert [PARTING in about_now(llm, n) for n in range(6)] == [False] * 5 + [True]
    assert not any(
        HANG_UP_WARNING in about_now(llm, n) or HANGING_UP in about_now(llm, n) for n in range(6)
    )
    assert [ended_by(turn) for turn in turns] == [False] * 5 + [True]
    assert done_of(turns[-1])["affinity"]["cooldown_until"] is None
    assert shape(recorded)[-3:] == ["user:第5句", "character:好的", "ended"]
    assert done_of(turns[-1])["ended"] == recorded[-1]
    [mano] = listed
    assert mano["last_message"]["role"] == "character"
    assert ended_kept(settings.database_path) == [None] * 5 + ["fed_up"]


async def test_once_ended_turns_are_rejected_counting_towards_nothing_and_calls_refused(
    make_client: ClientFactory, settings: Settings
):
    # Seven turns an hour: the six that end it, and one more, in a new conversation.
    client, llm = client_judging(
        make_client, [HURT] * 6 + [FINE],
        settings=replace(settings, usage_limits=UsageLimits(turns_per_hour=7)),
    )
    conversation = await start_conversation(client)
    await say_each(client, conversation, 6)

    rejected = await send_turn(client, conversation, "对不起")
    asked = await ask_before_calling(client, conversation)
    async with open_browser() as browser:
        call = await browser.call(client, conversation_id=conversation)
    recorded = await record(client, conversation)
    elsewhere = await send_turn(client, await start_conversation(client), "重新开始吧")

    assert [e["type"] for e in rejected] == ["user", "error"]
    assert rejected[-1]["message"] == ENDED
    assert shape(recorded)[-1] == "ended"
    assert len(recorded) == 13
    for refused in (asked, call):
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"] == ENDED
    assert done_of(elsewhere)["type"] == "done"
    assert len(llm.prompts) == 7


async def test_only_the_latest_eight_typed_turns_count_so_now_and_then_she_never_ends_it(
    make_client: ClientFactory, settings: Settings
):
    # Hurt every other turn: twelve in all, but never more than eight in eight turns.
    client, llm = client_judging(make_client, [HURT if n % 2 == 0 else FINE for n in range(11)])
    conversation = await start_conversation(client)

    turns = await say_each(client, conversation, 11)

    assert not any(ended_by(turn) for turn in turns)
    assert [n for n in range(11) if WARNING in about_now(llm, n)] == [4]
    assert "ended" not in shape(await record(client, conversation))


async def test_she_warns_again_only_once_it_has_eased_below_halfway(
    make_client: ClientFactory, settings: Settings
):
    # Six off her affinity in the latest eight all along, never below, as the ninth hurts.
    client, llm = client_judging(make_client, [HURT] * 3 + [FINE] * 5 + [HURT])
    conversation = await start_conversation(client)

    await say_each(client, conversation, 9)

    assert [n for n in range(9) if WARNING in about_now(llm, n)] == [2]


async def test_a_turn_not_judged_ends_nothing_but_takes_its_place_among_the_latest(
    make_client: ClientFactory, settings: Settings
):
    failing = Judging(fails=True)
    # Five that hurt, three not judged, one that hurts: ten in the latest eight, not twelve.
    client, llm = client_judging(make_client, [HURT] * 5 + [failing] * 3 + [HURT])
    conversation = await start_conversation(client)

    turns = await say_each(client, conversation, 9)

    assert all(done_of(turn)["type"] == "done" for turn in turns)
    assert not any(ended_by(turn) for turn in turns)
    assert not any(PARTING in about_now(llm, n) for n in range(9))


async def test_turns_from_before_typed_turns_were_counted_count_for_nothing(
    make_client: ClientFactory, settings: Settings
):
    client, _ = client_judging(make_client, [HURT] * 6)
    conversation = await start_conversation(client)
    said_long_ago(settings.database_path, conversation, 8)

    turns = await say_each(client, conversation, 6)

    assert [ended_by(turn) for turn in turns] == [False] * 5 + [True]


async def test_a_calls_turns_count_in_it_alone_and_her_hanging_up_leaves_the_conversation_open(
    make_client: ClientFactory, settings: Settings, speech: FakeSpeech
):
    # Out of line twice in the call (twenty off her affinity), then hurt a little typing.
    client, llm = client_judging(make_client, [OUT_OF_LINE, OUT_OF_LINE, HURT])
    conversation = await start_conversation(client)

    async with open_browser() as browser:
        await browser.call(client, conversation_id=conversation)
        await browser.connect()
        await say(speech, browser, "你这个废物")
        await say(speech, browser, "废物")
        await browser.next_server_message("ended")
        await browser.hung_up()
    async with asyncio.timeout(TIMEOUT):
        while "hung_up" not in shape(await record(client, conversation)):
            await asyncio.sleep(0.05)
    typed = await send_turn(client, conversation, "刚才说过头了")

    assert done_of(typed)["type"] == "done"
    assert not ended_by(typed)
    assert WARNING not in about_now(llm)
    assert "ended" not in shape(await record(client, conversation))


async def test_off_she_never_ends_it(make_client: ClientFactory, settings: Settings):
    client, llm = client_judging(
        make_client, [HURT] * 6, settings=replace(settings, affinity_and_gifts=False)
    )
    conversation = await start_conversation(client)

    turns = await say_each(client, conversation, 6)

    assert all(done_of(turn)["type"] == "done" and done_of(turn)["ended"] is None for turn in turns)
    assert not any(WARNING in about_now(llm, n) for n in range(6))
    assert "ended" not in shape(await record(client, conversation))


async def test_out_of_line_a_second_time_in_the_latest_eight_typed_turns_she_ends_it(
    make_client: ClientFactory, settings: Settings
):
    client, llm = client_judging(make_client, [OUT_OF_LINE] + [FINE] * 6 + [OUT_OF_LINE])
    conversation = await start_conversation(client)

    turns = await say_each(client, conversation, 8)

    assert [ended_by(turn) for turn in turns] == [False] * 7 + [True]
    assert PARTING in about_now(llm, 7)
    assert shape(await record(client, conversation))[-1] == "ended"
    assert ended_kept(settings.database_path) == [None] * 7 + ["out_of_line"]


async def test_out_of_line_more_than_eight_typed_turns_ago_is_not_counted(
    make_client: ClientFactory, settings: Settings
):
    client, llm = client_judging(make_client, [OUT_OF_LINE] + [FINE] * 7 + [OUT_OF_LINE])
    conversation = await start_conversation(client)

    turns = await say_each(client, conversation, 9)

    assert not any(ended_by(turn) for turn in turns)
    assert not any(PARTING in about_now(llm, n) for n in range(9))


async def test_the_turn_that_cools_her_ends_it_saying_till_when_and_the_cooldown_over_it_stays_ended(
    make_client: ClientFactory, settings: Settings
):
    clock = FakeClock()
    clients = FakeServiceClients()
    clients.judge.judgings = [level(0), FINE]
    llm = FakeLLM(REPLY, REPLY)
    client = make_client(llm, clients=clients, clock=clock)
    other = await start_conversation(client)
    conversation = await start_conversation(client)
    keep(settings.database_path, "producer", 5, clock.now)

    done = done_of(await send_turn(client, conversation, "随便你"))
    recorded = await record(client, conversation)
    clock.advance(days=2)
    rejected = await send_turn(client, conversation, "对不起")
    elsewhere = await send_turn(client, other, "还在吗")

    assert done["ended"] == recorded[-1]
    assert done["affinity"]["cooldown_until"] == UNTIL
    assert PARTING in about_now(llm, 0)
    assert shape(recorded) == ["user:随便你", "character:好的", "ended"]
    assert ended_kept(settings.database_path)[0] == "cooldown"
    assert rejected[-1] == {"type": "error", "message": ENDED}
    assert done_of(elsewhere)["type"] == "done"
    assert "ended" not in shape(await record(client, other))


async def test_a_reset_card_does_not_open_it_again(make_client: ClientFactory, settings: Settings):
    clock = FakeClock()
    clients = FakeServiceClients()
    clients.judge.judgings = [level(0)]
    client = make_client(
        FakeLLM(REPLY), clients=clients, clock=clock, random=FakeRandom(RESET_CARD)
    )
    assert (await client.get("/api/gifts")).status_code == 200
    assert (await client.post("/api/gifts/draws", json={"all": True})).status_code == 200
    conversation = await start_conversation(client)
    keep(settings.database_path, "producer", 5, clock.now)
    await send_turn(client, conversation, "随便你")

    used = await client.post(USE)
    rejected = await send_turn(client, conversation, "对不起")
    asked = await ask_before_calling(client, conversation)

    assert used.status_code == 200, used.text
    assert (await status(client)).json()["cooldown_until"] is None
    assert rejected[-1] == {"type": "error", "message": ENDED}
    assert asked.status_code == 409
    assert asked.json()["detail"] == ENDED


async def test_cooling_her_in_a_call_ends_no_conversation(
    make_client: ClientFactory, settings: Settings, speech: FakeSpeech
):
    clock = FakeClock()
    clients = FakeServiceClients()
    clients.judge.judgings = [level(0), FINE]
    llm = FakeLLM(REPLY, REPLY)
    client = make_client(llm, clients=clients, clock=clock)
    conversation = await start_conversation(client)
    keep(settings.database_path, "producer", 5, clock.now)

    async with open_browser() as browser:
        await browser.call(client, conversation_id=conversation)
        await browser.connect()
        await say(speech, browser, "随便你")
        ended = await browser.next_server_message("ended")
        await browser.hung_up()
    clock.advance(days=2)
    typed = await send_turn(client, conversation, "刚才说过头了")

    assert ended["reason"] == "cooldown"
    assert done_of(typed)["type"] == "done"
    assert not ended_by(typed)
    assert "ended" not in shape(await record(client, conversation))


class EndedElsewhere(FakeLLM):
    """Replies as a `FakeLLM` does, `end` called once it has, as another tab might end the
    conversation meanwhile."""

    def __init__(self, end: Callable[[], None], *replies: list[str]) -> None:
        super().__init__(*replies)
        self._end = end

    async def stream_with(self, *args, **kwargs):
        async for chunk in super().stream_with(*args, **kwargs):
            yield chunk
        self._end()


async def test_a_turn_under_way_as_it_is_ended_elsewhere_is_rejected_and_counts_towards_nothing(
    make_client: ClientFactory, settings: Settings
):
    ending: list[str] = []  # the conversation ended as the model replies, while there is one
    clients = FakeServiceClients()
    clients.judge.judgings = [HURT, FINE]
    llm = EndedElsewhere(lambda: end(settings.database_path, *ending), REPLY, REPLY)
    client = make_client(
        llm, clients=clients, clock=FakeClock(),
        settings=replace(settings, usage_limits=UsageLimits(turns_per_hour=1)),
    )
    conversation = await start_conversation(client)
    ending.append(conversation)

    turn = await send_turn(client, conversation, "随便你")
    recorded = await record(client, conversation)
    ending.clear()
    elsewhere = await send_turn(client, await start_conversation(client), "重新开始吧")

    assert turn[-1] == {"type": "error", "message": ENDED}
    assert shape(recorded) == ["ended"]
    assert (await status(client)).json()["tier"] == "trust"
    assert done_of(elsewhere)["type"] == "done"


async def test_a_call_in_it_as_she_ends_it_she_hangs_up_telling_it_she_ended_it(
    make_client: ClientFactory, settings: Settings, speech: FakeSpeech
):
    client, _ = client_judging(make_client, [OUT_OF_LINE, OUT_OF_LINE])
    conversation = await start_conversation(client)

    async with open_browser() as browser:
        await browser.call(client, conversation_id=conversation)
        await browser.connect()
        typed = await say_each(client, conversation, 2)
        ended = await browser.next_server_message("ended")
        await browser.hung_up()
    recorded = await record(client, conversation)

    assert ended_by(typed[-1])
    assert ended["reason"] == "she_hung_up"
    assert ended["event"] == recorded[-1]
    assert shape(recorded)[-1] == "ended"
    assert "hung_up" not in shape(recorded)
    assert call_ended_by(settings.database_path) == ["character_hung_up"]


def said_long_ago(database: Path, conversation: str, turns: int) -> None:
    """Have the conversation open with `turns` turns, as recorded before typed turns' were
    counted."""
    at = datetime(2026, 1, 1, tzinfo=UTC).isoformat()
    with sqlite3.connect(database) as db:
        for _ in range(turns):
            db.execute(
                "INSERT INTO messages (conversation_id, role, text, created_at)"
                " VALUES (?, 'user', '很久以前', ?)",
                (conversation, at),
            )
            db.execute(
                "INSERT INTO messages (conversation_id, role, ja, zh, segments, created_at)"
                " VALUES (?, 'character', 'はい', '好的', '[]', ?)",
                (conversation, at),
            )


def ended_kept(database: Path) -> list[str | None]:
    """Why she ended the conversation after each turn, as its activity record keeps it,
    oldest first."""
    with sqlite3.connect(database) as db:
        rows = db.execute(
            "SELECT ended_conversation FROM activity_records WHERE kind = 'turn' ORDER BY id"
        ).fetchall()
    return [reason for (reason,) in rows]



def end(database: Path, conversation: str | None = None) -> None:
    """Have her end the conversation, if one is given, as recorded elsewhere."""
    if conversation is None:
        return
    with sqlite3.connect(database) as db:
        db.execute(
            "INSERT INTO conversation_events (conversation_id, kind, created_at)"
            " VALUES (?, 'ended', ?)",
            (conversation, datetime.now(UTC).isoformat()),
        )


def call_ended_by(database: Path) -> list[str]:
    """Why each call ended, as its activity record keeps it, oldest first."""
    with sqlite3.connect(database) as db:
        rows = db.execute(
            "SELECT end_reason FROM activity_records WHERE kind = 'call' ORDER BY id"
        ).fetchall()
    return [reason for (reason,) in rows]
