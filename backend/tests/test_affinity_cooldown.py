"""A cooldown (GLOSSARY.md「冷却」): as her affinity falls to 0 she does not want to talk to
the producer for a while. The turn that will take it there tells her to reply and then make
it clear, her own way, that she does not want to go on; from then on, until it has
recovered to the thaw line, turns and new calls with her are refused, 409 with when it ends,
before the limit and the activity record are asked: they count towards nothing and are not
recorded. Once over she is cold, and falling to 0 again begins another. Each character is apart; off, nothing is
refused, whatever is kept.

Driven through the backend's external API, the judge model faked turn by turn and the clock
moved by hand; calls with a browser over a real WebRTC connection."""

from dataclasses import replace
from datetime import timedelta

import httpx
import pytest

from eidolon.config import Settings, UsageLimits
from tests.browser import open_browser
from tests.conftest import ClientFactory
from tests.fakes import (
    FAKE_JUDGE,
    START,
    FakeClock,
    FakeIdentityProvider,
    FakeLLM,
    FakeServiceClients,
    FakeSpeech,
    level,
)
from tests.test_activity_records import dashboard
from tests.test_admin_users import ADMIN, admin_beside
from tests.test_affinity import keep, status
from tests.test_affinity_prompt import about_now
from tests.test_rate_limit import post_turn
from tests.test_text_turn import done_of, send_turn, start_conversation

REPLY = ["<ja>はい</ja><zh>好的</zh>"]
PARTING = "这句话之后你暂时不想再和制作人说话了。先回应，再用你自己的方式表明你现在不想聊下去。"
UNTIL = (START + timedelta(days=1)).isoformat()
"""When a cooldown begun at 0 as the tests begin ends."""


@pytest.fixture
def settings(settings: Settings) -> Settings:
    """With an admin, the judge model, affinity on in `.env`, and one turn and one call an
    hour."""
    return replace(
        settings,
        admins=frozenset({ADMIN}),
        judge=FAKE_JUDGE,
        affinity_and_gifts=True,
        usage_limits=UsageLimits(turns_per_hour=1, calls_per_hour=1),
    )


def ask_before_calling(client: httpx.AsyncClient, conversation_id: str):
    return client.get("/api/ice-servers", params={"conversation": conversation_id})


def refused(res: httpx.Response, until: str = UNTIL) -> None:
    """Refused as in a cooldown that ends `until`, by default one begun at 0 as the tests
    begin."""
    assert res.status_code == 409, res.text
    assert res.json()["cooldown_until"] == until
    assert res.json()["detail"]


async def test_the_turn_that_takes_it_to_0_has_her_part_and_begins_a_cooldown(
    make_client: ClientFactory, settings: Settings
):
    clock = FakeClock()
    clients = FakeServiceClients()
    clients.judge.judgings = [level(0), level(0)]
    llm = FakeLLM(REPLY, REPLY)
    unlimited = replace(settings, usage_limits=UsageLimits())
    client = make_client(llm, clients=clients, clock=clock, settings=unlimited)
    other = await start_conversation(client, "kogane")
    keep(settings.database_path, "producer", 45, clock.now, character="kogane")
    conversation = await start_conversation(client)
    keep(settings.database_path, "producer", 5, clock.now)

    staying = await send_turn(client, other, "随便你")
    parting = await send_turn(client, conversation, "随便你")

    assert PARTING not in about_now(llm, 0)
    assert done_of(staying)["affinity"]["cooldown_until"] is None
    assert PARTING in about_now(llm, 1)
    assert "挂断电话" not in about_now(llm, 1)  # that is for calls alone
    assert done_of(parting)["message"]["affinity"]["cooldown"] is True
    assert done_of(parting)["affinity"]["cooldown_until"] == UNTIL


async def test_in_a_cooldown_turns_and_calls_are_refused_counting_towards_nothing_until_it_ends(
    make_client: ClientFactory,
    settings: Settings,
    github: FakeIdentityProvider,
    speech: FakeSpeech,
):
    clock = FakeClock()
    clients = FakeServiceClients()
    clients.judge.judgings = [level(1, out_of_line=True), level(0)]
    llm = FakeLLM(REPLY, REPLY)
    client = make_client(llm, clients=clients, clock=clock)
    conversation = await start_conversation(client)
    # Just short of the thaw line: it ends in under 15 minutes, within the hour of the limit.
    keep(settings.database_path, "producer", 9.9, clock.now, cooling=True)
    until = (clock.now + timedelta(days=0.01)).isoformat()

    async with admin_beside(client, github) as admin:
        turn = await post_turn(client, conversation)
        asked = await ask_before_calling(client, conversation)
        async with open_browser() as browser:
            call = await browser.call(client, conversation_id=conversation)
        board = await dashboard(admin)

        clock.advance(minutes=15)
        thawed = (await status(client)).json()
        # Had the refused turn counted, the hour's one turn would be used up.
        again = await send_turn(client, conversation, "你这个废物")
        clock.advance(hours=1)
        fell_again = await send_turn(client, conversation, "随便你")
        cooling_again = await post_turn(client, conversation)

    for res in (turn, asked, call):
        refused(res, until)
    assert board["turns"]["total"] == 0
    assert board["calls"]["total"] == 0
    assert speech.stts == []
    assert thawed == {"tier": "cold", "cooldown_until": None}
    assert done_of(again)["type"] == "done"
    assert done_of(fell_again)["message"]["affinity"]["cooldown"] is True
    assert cooling_again.status_code == 409
    assert len(llm.prompts) == 2


async def test_a_cooldown_is_hers_alone(make_client: ClientFactory, settings: Settings):
    client = make_client(FakeLLM(REPLY), clock=FakeClock())
    other = await start_conversation(client, "kogane")
    keep(settings.database_path, "producer", 0, START, cooling=True)

    events = await send_turn(client, other, "在吗")

    assert done_of(events)["type"] == "done"


async def test_off_nothing_is_refused_whatever_is_kept(
    make_client: ClientFactory, settings: Settings
):
    client = make_client(
        FakeLLM(REPLY),
        settings=replace(settings, affinity_and_gifts=False),
        clock=FakeClock(),
    )
    conversation = await start_conversation(client)
    keep(settings.database_path, "producer", 0, START, cooling=True)

    asked = await ask_before_calling(client, conversation)
    events = await send_turn(client, conversation, "在吗")

    assert asked.status_code == 200
    assert done_of(events)["type"] == "done"
