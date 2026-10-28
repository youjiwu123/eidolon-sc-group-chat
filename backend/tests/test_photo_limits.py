"""How many photos a user may have her send (GLOSSARY.md「限额」「照片」): five an hour unless
the deployer or an admin says otherwise, counted apart from turns and calls. A turn asking
for one only checks there is one left; with none, she is told she cannot send one now, any
tag she writes is dropped, and the user is told when to ask again (`photos-used-up`). A
photo is counted only as it begins generating; used up meanwhile, it is not sent, saying
why. One not sent is given back; one sent with a reply that is gone is not.

Driven through the backend's external API, the judge model finding every turn asks for a
photo, the image service faked at its transport, and a clock the tests control."""

import asyncio
import sqlite3
from dataclasses import replace
from datetime import timedelta

import pytest

from eidolon.config import Settings, UsageLimits
from eidolon.photos import CANNOT_SEND, USED_UP
from eidolon.usage import UsageKind, UsageLimiter
from tests.conftest import ClientFactory
from tests.fakes import (
    HANG,
    START,
    FakeClock,
    FakeIdentityProvider,
    FakeImageService,
    FakeLLM,
    FakeLLMService,
    FakeServiceClients,
    context_of,
)
from tests.test_admin_users import ADMIN, admin_client, find
from tests.test_live_config import CONFIG, recorded
from tests.test_live_config import admin_client as live_admin_client
from tests.test_live_config_limits import LIMITS
from tests.test_own_llm import LLM
from tests.test_photo_failures import ASKED, record_of, until
from tests.test_photos import (  # noqa: F401  (`settings`, with the deployer's image generation)
    REPLY,
    SELFIE,
    WORDS,
    asking,
    photo_events,
    settings,
    settled,
)
from tests.test_user_limits import set_limits
from tests.test_text_turn import leave_turn, send_turn, start_conversation


def used_up(events: list[dict]) -> list[dict]:
    return [e for e in events if e["type"] == "photos-used-up"]


async def test_five_photos_an_hour_then_she_cannot_and_the_user_is_told_when_to_ask_again(
    make_client: ClientFactory, settings: Settings
):
    clock = FakeClock()
    image = FakeImageService()
    llm = FakeLLM(*[REPLY] * 7)
    client = make_client(llm, clients=asking(), clock=clock, image_transport=image.transport())
    conversation = await start_conversation(client)

    for _ in range(5):
        [photo] = photo_events(await send_turn(client, conversation, ASKED))
        assert (await settled(client, photo["id"]))["status"] == "ready"
        clock.advance(minutes=10)
    refused = await send_turn(client, conversation, ASKED)
    record = await record_of(client, conversation)

    assert photo_events(refused) == []
    assert used_up(refused) == [
        {"type": "photos-used-up", "retry_at": (START + timedelta(hours=1)).isoformat()}
    ]
    assert [e["type"] for e in refused if e["type"] != "emotion"][-2:] == ["photos-used-up", "done"]
    assert USED_UP in context_of(llm.prompts[5])
    assert len(image.requests) == 5  # her tag was dropped
    assert "photo" not in record[-1]
    assert record[-1]["ja"] == "はい、どうぞ"

    clock.advance(minutes=10)
    again = await send_turn(client, conversation, ASKED)
    assert len(photo_events(again)) == 1
    assert used_up(again) == []


def photos_an_hour(settings: Settings, photos: int | None) -> Settings:
    return replace(settings, usage_limits=UsageLimits(photos_per_hour=photos))


async def test_a_turn_asking_takes_none_unless_she_sends_one(
    make_client: ClientFactory, settings: Settings
):
    image = FakeImageService()
    llm = FakeLLM([WORDS], REPLY, REPLY)
    client = make_client(
        llm, clients=asking(), settings=photos_an_hour(settings, 1), clock=FakeClock(),
        image_transport=image.transport(),
    )
    conversation = await start_conversation(client)

    declined = await send_turn(client, conversation, ASKED)
    sent = await send_turn(client, conversation, ASKED)
    refused = await send_turn(client, conversation, ASKED)

    assert (photo_events(declined), used_up(declined)) == ([], [])
    assert len(photo_events(sent)) == 1 and used_up(sent) == []
    assert photo_events(refused) == [] and len(used_up(refused)) == 1


async def test_a_photo_not_sent_is_given_back(make_client: ClientFactory, settings: Settings):
    image = FakeImageService()
    image.status = 503
    client = make_client(
        FakeLLM(REPLY, REPLY), clients=asking(), settings=photos_an_hour(settings, 1),
        clock=FakeClock(), image_transport=image.transport(),
    )
    conversation = await start_conversation(client)

    [failed] = photo_events(await send_turn(client, conversation, ASKED))
    assert await settled(client, failed["id"]) == {"status": "failed", "reason": "service_error"}
    image.status = None
    again = await send_turn(client, conversation, ASKED)

    assert used_up(again) == []
    [photo] = photo_events(again)
    assert (await settled(client, photo["id"]))["status"] == "ready"


async def test_one_sent_with_a_reply_never_recorded_is_not_given_back(
    make_client: ClientFactory, settings: Settings
):
    image = FakeImageService()
    image.gate = asyncio.Event()
    client = make_client(
        FakeLLM([f"<photo>{SELFIE}</photo>", HANG], REPLY), clients=asking(),
        settings=photos_an_hour(settings, 1), clock=FakeClock(),
        image_transport=image.transport(),
    )
    conversation = await start_conversation(client)

    await leave_turn(client, conversation, ASKED, after="photo")
    image.gate.set()
    await until(lambda: recorded(client, "image"))
    await asyncio.sleep(0.05)
    refused = await send_turn(client, conversation, ASKED)

    assert photo_events(refused) == [] and len(used_up(refused)) == 1


async def test_one_whose_photos_are_used_up_elsewhere_meanwhile_is_not_sent_saying_so(
    make_client: ClientFactory, settings: Settings
):
    image = FakeImageService()
    client = make_client(
        FakeLLM(["", *REPLY], ["", *REPLY], delay=0.1), clients=asking(),
        settings=photos_an_hour(settings, 1), clock=FakeClock(),
        image_transport=image.transport(),
    )
    conversation = await start_conversation(client)

    # On two devices at once, each turn checking before either photo begins.
    both = await asyncio.gather(
        send_turn(client, conversation, ASKED), send_turn(client, conversation, ASKED)
    )
    photos = [photo for events in both for photo in photo_events(events)]
    came_out = sorted(
        [await settled(client, photo["id"]) for photo in photos], key=lambda s: s["status"]
    )

    assert [used_up(events) for events in both] == [[], []]
    assert came_out == [
        {"status": "failed", "reason": "used_up"},
        {"status": "ready", "reason": None},
    ]
    assert len(image.requests) == 1


async def test_one_whose_count_cannot_be_taken_is_not_left_being_generated(
    make_client: ClientFactory, settings: Settings, monkeypatch: pytest.MonkeyPatch
):
    image = FakeImageService()
    client = make_client(
        FakeLLM(REPLY), clients=asking(), clock=FakeClock(), image_transport=image.transport()
    )
    conversation = await start_conversation(client)

    take = UsageLimiter.take

    def broken(self: UsageLimiter, user_id: str, kind: UsageKind, *args, **kwargs):
        if kind == "photo":
            raise sqlite3.OperationalError("database is locked")
        return take(self, user_id, kind, *args, **kwargs)

    monkeypatch.setattr(UsageLimiter, "take", broken)
    [photo] = photo_events(await send_turn(client, conversation, ASKED))

    assert await settled(client, photo["id"]) == {"status": "failed", "reason": "service_error"}
    assert image.requests == []


async def test_a_turn_on_the_users_own_llm_still_counts_her_photo(
    make_client: ClientFactory, settings: Settings, own_llm: FakeLLMService
):
    own_llm.llm = FakeLLM(REPLY, REPLY)
    client = make_client(
        FakeLLM(), clients=asking(), settings=photos_an_hour(settings, 1), clock=FakeClock(),
        image_transport=FakeImageService().transport(),
    )
    conversation = await start_conversation(client)

    sent = await send_turn(client, conversation, ASKED, own_llm=LLM)
    refused = await send_turn(client, conversation, ASKED, own_llm=LLM)

    assert len(photo_events(sent)) == 1
    assert photo_events(refused) == [] and len(used_up(refused)) == 1


@pytest.mark.parametrize(
    ("own", "deployments", "photos"),
    [(1, None, 1), ("unlimited", 1, 3), (0, None, 0)],
)
async def test_an_admin_may_set_a_users_own_photos_an_hour(
    make_client: ClientFactory,
    settings: Settings,
    github: FakeIdentityProvider,
    own: int | str,
    deployments: int | None,
    photos: int,
):
    settings = replace(photos_an_hour(settings, deployments), admins=frozenset({ADMIN}))
    admin = await admin_client(make_client, github, settings=settings)
    image = FakeImageService()
    clients = asking()
    llm = FakeLLM(*[REPLY] * 3)
    producer = make_client(
        llm, clients=clients, settings=settings, clock=FakeClock(),
        image_transport=image.transport(),
    )
    conversation = await start_conversation(producer)
    producer_id = (await find(admin, "producer"))["id"]

    shown = await set_limits(admin, producer_id, photos_per_hour=own)
    turns = [await send_turn(producer, conversation, ASKED) for _ in range(3)]

    assert shown["limits"]["photos_per_hour"] == own
    assert (shown["limits"]["turns_per_hour"], shown["limits"]["calls_per_hour"]) == (None, None)
    assert [len(photo_events(events)) for events in turns] == [1] * photos + [0] * (3 - photos)
    if own == 0:  # as if there were no photos: she knows she cannot send one
        assert clients.judge.photo_asked == []
        assert CANNOT_SEND in context_of(llm.prompts[0])
        assert [used_up(events) for events in turns] == [[], [], []]
    else:
        assert [len(used_up(events)) for events in turns] == [0] * photos + [1] * (3 - photos)


async def test_the_photos_an_hour_saved_in_the_admin_console_hold_from_the_next_turn(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    image = FakeImageService()
    clients = FakeServiceClients(FakeLLM(*[REPLY] * 3))
    clients.judge.photo = 1.0
    client = await live_admin_client(
        lambda *a, **k: make_client(
            *a, clock=FakeClock(), image_transport=image.transport(), **k
        ),
        replace(settings, admins=frozenset({("github", "1001")})), github, clients,
    )
    conversation = await start_conversation(client)
    before = (await client.get(CONFIG)).json()["limits"]

    saved = await client.put(LIMITS, json=before["env"] | {"photos_per_hour": 1})
    sent = await send_turn(client, conversation, ASKED)
    refused = await send_turn(client, conversation, ASKED)
    unlimited = await client.put(LIMITS, json=before["env"] | {"photos_per_hour": 0})
    again = await send_turn(client, conversation, ASKED)

    assert before["env"]["photos_per_hour"] == 5
    assert saved.status_code == 200, saved.text
    assert saved.json()["limits"]["override"] == {"photos_per_hour": 1}
    assert len(photo_events(sent)) == 1
    assert photo_events(refused) == [] and len(used_up(refused)) == 1
    assert unlimited.json()["limits"]["effective"]["photos_per_hour"] == 0
    assert len(photo_events(again)) == 1

