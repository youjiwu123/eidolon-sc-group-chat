"""The dashboard's「好感度」section (GLOSSARY.md「看板」「好感度」): over the dashboard's range,
how many cooldowns began and for how many users, how often what was said was out of line or
tried to dictate her affinity, how the turns were judged across the five levels, and, for
each character, the turns judged (only those recorded), the share of them that lowered it,
her cooldowns, out-of-line and manipulative turns, the calls she hung up and the conversations
she ended, by why (a cooldown, out of line once too often, the latest typed turns hurting her
too much; never a call she hung up). Most lowering first; a character judged fewer than `FEW`
times last, her share not told. Nothing in it says whose any of it was, and where affinity is
off there is no section at all.

Each turn's activity record keeps what the judge model made of it, if the turn was judged and
recorded: its level, whether it was out of line or manipulative, whether it began a cooldown;
nothing said. The judge model's thresholds for the two yes-or-no questions are set in the
admin console's thresholds card, as retrieval's and emotion's are.

Driven through the backend's external API, the judge model faked turn by turn."""

from dataclasses import replace

import httpx
import pytest

from eidolon.config import JevSettings, Settings, UsageLimits
from eidolon.llm import LLMError
from tests.conftest import CharacterConfig, ClientFactory
from tests.fakes import (
    FAKE_JUDGE,
    FakeClock,
    FakeIdentityProvider,
    FakeLLM,
    FakeServiceClients,
    Judging,
    level,
)
from tests.test_activity_records import dashboard
from tests.test_admin_users import ADMIN, admin_beside
from tests.test_affinity import keep
from tests.test_text_turn import close_of, send_turn, start_conversation

REPLY = ["<ja>はい</ja><zh>好的</zh>"]
OUT_OF_LINE = level(1, out_of_line=True)


@pytest.fixture
def characters(characters: CharacterConfig) -> CharacterConfig:
    """Mano and Kogane, and Meguru."""
    return characters.add("meguru", "八宮めぐる", "# 人设\n你是八宮めぐる。")


@pytest.fixture
def settings(settings: Settings) -> Settings:
    """With an admin, the judge model, affinity on in `.env`, and no limits."""
    return replace(
        settings,
        admins=frozenset({ADMIN}),
        judge=FAKE_JUDGE,
        affinity_and_gifts=True,
        usage_limits=UsageLimits(),
    )


async def talk(client: httpx.AsyncClient, conversation: str, times: int) -> None:
    for _ in range(times):
        events = await send_turn(client, conversation, "今天怎么样")
        close_of(events)  # her reply, or why there is none


async def test_the_section_sums_up_the_judged_turns_and_ranks_the_characters_by_how_many(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    clock = FakeClock()
    clients = FakeServiceClients()
    clients.judge.judgings = [
        # Mano: 20 judged, 2 lowering (10%), 1 raising (5%), one that would have but tried to
        # dictate it; one judged but failed, one the judge failed on.
        *[level(1)] * 2, level(3, manipulation=True), level(4), *[level(2)] * 16,
        level(0), Judging(fails=True),
        # Kogane: 20 judged, 5 lowering (25%), the last out of line, cooling her and ending the
        # conversation.
        *[level(1)] * 4, *[level(2)] * 15, OUT_OF_LINE,
        # Meguru: once, cooling her too; too few to tell a share.
        level(0),
    ]
    replies = [REPLY] * 20 + [LLMError("对话模型返回 500"), REPLY] + [REPLY] * 21
    client = make_client(FakeLLM(*replies), clients=clients, clock=clock)
    mano = await start_conversation(client, "mano")
    kogane = await start_conversation(client, "kogane")
    meguru = await start_conversation(client, "meguru")

    async with admin_beside(client, github) as admin:
        await talk(client, mano, 22)
        await talk(client, kogane, 19)
        keep(settings.database_path, "producer", 5, clock.now, character="kogane")
        await talk(client, kogane, 1)
        keep(settings.database_path, "producer", 3, clock.now, character="meguru")
        await talk(client, meguru, 1)
        board = await dashboard(admin)

    section = board["affinity"]
    assert section == {
        "cooldowns": 2,
        "cooled_users": 1,
        "out_of_line": 1,
        "manipulation": 1,
        "levels": [1, 7, 31, 1, 1],
        "characters": [
            # As many judged as Mano, but she ended a conversation.
            {
                "character_id": "kogane", "name": "月岡恋鐘", "judged": 20,
                "raised_share": 0.0, "lowered_share": 0.25, "cooldowns": 1, "she_ended": 1,
            },
            {
                "character_id": "mano", "name": "櫻木真乃", "judged": 20,
                "raised_share": 0.05, "lowered_share": 0.1, "cooldowns": 0, "she_ended": 0,
            },
            {
                "character_id": "meguru", "name": "八宮めぐる", "judged": 1,
                "raised_share": None, "lowered_share": None, "cooldowns": 1, "she_ended": 1,
            },
        ],
    }
    assert board["turns"]["by_result"]["failed"] == 1


async def test_the_conversations_she_ended_are_counted_whatever_for(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    # Those she ended as she cooled are counted in the test above.
    clients = FakeServiceClients()
    # Hurt turn after turn in one conversation, out of line twice in another.
    clients.judge.judgings = [*[level(1)] * 6, OUT_OF_LINE, OUT_OF_LINE]
    client = make_client(FakeLLM(*[REPLY] * 8), clients=clients, clock=FakeClock())

    async with admin_beside(client, github) as admin:
        await talk(client, await start_conversation(client), 6)
        await talk(client, await start_conversation(client), 2)
        board = await dashboard(admin)

    [mano] = board["affinity"]["characters"]
    assert mano["she_ended"] == 2


async def test_the_section_follows_the_dashboards_range(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    clock = FakeClock()
    clients = FakeServiceClients()
    clients.judge.judgings = [level(4), level(0)]
    client = make_client(FakeLLM(REPLY, REPLY), clients=clients, clock=clock)
    conversation = await start_conversation(client)

    async with admin_beside(client, github) as admin:
        await talk(client, conversation, 1)
        clock.advance(days=2)
        await talk(client, conversation, 1)
        day = (await dashboard(admin, "24h"))["affinity"]
        week = (await dashboard(admin, "7d"))["affinity"]

    assert day["levels"] == [1, 0, 0, 0, 0]
    assert week["levels"] == [1, 0, 0, 0, 1]


@pytest.mark.parametrize("judge", [FAKE_JUDGE, None])
async def test_with_affinity_off_there_is_no_section(
    make_client: ClientFactory,
    settings: Settings,
    github: FakeIdentityProvider,
    judge: JevSettings | None,
):
    off = replace(settings, affinity_and_gifts=judge is None, judge=judge)
    client = make_client(FakeLLM(REPLY), clients=FakeServiceClients(), settings=off)
    conversation = await start_conversation(client)

    async with admin_beside(client, github) as admin:
        await talk(client, conversation, 1)
        board = await dashboard(admin)

    assert board["turns"]["total"] == 1
    assert board["affinity"] is None


JUDGE = "/api/admin/config/judge"
JUDGE_THRESHOLDS = "/api/admin/config/judge_thresholds"
JEV = {"recall": 0.5, "emotion": 0.5, "out_of_line": 0.7, "manipulation": 0.4, "photo": 0.5}
CLEF_FLASH = {
    "recall": 0.7, "emotion": 0.4, "out_of_line": 0.6, "manipulation": 0.6, "photo": 0.8
}


def judging(out_of_line: float, manipulation: float) -> Judging:
    """A turn that makes her very happy, how likely it is out of line or dictates her
    affinity as given."""

    class Probable(Judging):
        def answers(self) -> dict:
            answers = super().answers()
            for question, p in (("out_of_line", out_of_line), ("manipulation", manipulation)):
                answers[question] = {"noul": p}
            return answers

    return Probable({4: 1.0})


async def test_the_affinity_thresholds_are_set_restored_and_cleared_with_another_judge_model(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    clients = FakeServiceClients()
    # Neither by Jev's (0.7, 0.4) thresholds; both by those saved (0.6, 0.3); then neither
    # again, back to Jev's; then out of line by Clef-flash's 0.6, the saved ones cleared.
    clients.judge.judgings = [judging(0.65, 0.35)] * 4
    client = make_client(FakeLLM(*[REPLY] * 4), clients=clients)
    conversation = await start_conversation(client)

    async with admin_beside(client, github) as admin:
        await talk(client, conversation, 1)
        saved = await admin.put(
            JUDGE_THRESHOLDS, json=JEV | {"out_of_line": 0.6, "manipulation": 0.3}
        )
        assert saved.status_code == 200, saved.text
        await talk(client, conversation, 1)
        restored = await admin.delete(JUDGE_THRESHOLDS)
        assert restored.status_code == 200, restored.text
        await talk(client, conversation, 1)
        resaved = await admin.put(JUDGE_THRESHOLDS, json=JEV | {"out_of_line": 0.9})
        assert resaved.status_code == 200, resaved.text
        changed = await admin.put(JUDGE, json={
            "provider": "cloudflare", "api_key": "cf-token", "model": "clef-flash",
            "account_id": "account-1", "emotion_timeout": 1.5,
        })
        assert changed.status_code == 200, changed.text
        await talk(client, conversation, 1)
        board = await dashboard(admin)

    thresholds = saved.json()["judge_thresholds"]
    assert thresholds["env"] == JEV
    assert thresholds["effective"] == JEV | {"out_of_line": 0.6, "manipulation": 0.3}
    assert restored.json()["judge_thresholds"]["status"] == "env"
    cleared = changed.json()["judge_thresholds"]
    assert cleared["status"] == "env" and cleared["effective"] == CLEF_FLASH
    section = board["affinity"]
    assert (section["out_of_line"], section["manipulation"]) == (2, 1)
    assert section["levels"] == [0, 0, 0, 0, 4]

