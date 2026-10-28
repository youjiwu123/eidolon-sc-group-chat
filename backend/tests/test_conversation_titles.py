"""Conversation titles (GLOSSARY.md「对话标题」): once a conversation's third turn is recorded,
typed or in a call, the turn's background model names it, after the turn, holding up
nothing, memory on or off, she having ended it in that turn or not; the deployer's model
is held till it is named, replaced meanwhile or not, and a turn on the user's own
background model is named by it. Her conversations list it with its title, which is
never changed after; one the model failed to name, or named with nothing, has none, and
is not named again. The model reads the record up to then, events and all, but no
memories; what it answers is cut down to a title. No one but the user sees it: not she,
nor memory, nor the admin's dashboard, which counts naming as the background model's,
nor the logs; deleting the user deletes it. A database from before titles lists its
conversations untitled.

Driven through the backend's external API, the background model faked."""

import asyncio
import sqlite3
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from eidolon.config import Settings
from eidolon.llm import ChatMessage, LLMError
from tests.browser import Browser
from tests.conftest import ClientFactory
from tests.fakes import (
    FAKE_JUDGE,
    FakeBackgroundLLM,
    FakeClock,
    FakeEmbedder,
    FakeIdentityProvider,
    FakeJudge,
    FakeLLM,
    FakeLLMService,
    FakeReranker,
    FakeServiceClients,
    FakeSpeech,
    level,
)
from tests.test_activity_records import admin_client, dashboard, health
from tests.test_conversation_events import hang_up
from tests.test_delete_account import DELETE, rows_mentioning
from tests.test_live_config import admin_client as live_admin_client
from tests.test_live_config_services import ENV_SETTINGS, NEW_MEMORY, NEW_MEMORY_SETTINGS
from tests.test_live_config_services import MEMORY_LLM as BACKGROUND_CONFIG
from tests.test_own_llm import MEMORY_KEY, MEMORY_LLM, MINE, THINKING
from tests.test_she_ends_conversation import client_judging, ended_by
from tests.test_she_hangs_up import OUT_OF_LINE
from tests.test_she_hangs_up import say as say_in_call
from tests.test_shared_memory import CAT, memorized
from tests.test_text_turn import done_of, send_turn, start_conversation

REPLY = ["<ja>はい</ja><zh>好的</zh>"]
TITLE = "商量周末去看海"


async def listed_titles(client: httpx.AsyncClient, character: str = "mano") -> list[str | None]:
    """The titles of her conversations as she lists them, newest first."""
    res = await client.get("/api/conversations", params={"character_id": character})
    assert res.status_code == 200, res.text
    return [c["title"] for c in res.json()]


def answering(title: str, memories: str = FakeBackgroundLLM.NOTHING) -> Callable[[str], str]:
    """A background model's answer: `title` when asked to name a conversation, else
    `memories`."""
    return lambda prompt: title if "起标题" in prompt else memories


def naming(prompts: list[list[ChatMessage]]) -> list[str]:
    """Of the prompts the background model was given, those asking it to name a
    conversation, each as one text."""
    texts = ["\n".join(m.content for m in prompt) for prompt in prompts]
    return [text for text in texts if "起标题" in text]


def fed(prompt: list[ChatMessage]) -> list[str]:
    """What the background model was given to name the conversation from, line by line."""
    return prompt[-1].content.splitlines()


def give_pudding(database: Path, conversation: str) -> None:
    """Record the user's giving her a pudding in the conversation, now, as giving would."""
    with sqlite3.connect(database) as db:
        db.execute(
            "INSERT INTO conversation_events (conversation_id, kind, created_at, gift_id)"
            " VALUES (?, 'gift', ?, 'pudding')",
            (conversation, datetime.now(UTC).isoformat()),
        )


async def say(client: httpx.AsyncClient, conversation: str, n: int) -> None:
    """`n` typed turns, each done."""
    for i in range(n):
        assert done_of(await send_turn(client, conversation, f"第{i}句"))["type"] == "done"


async def test_the_third_turn_names_the_conversation_once(make_client: ClientFactory):
    background = FakeBackgroundLLM(TITLE, "别的标题")
    client = make_client(FakeLLM(*[REPLY] * 4), background_llm=background)
    conversation = await start_conversation(client)

    await say(client, conversation, 2)
    after_two = await listed_titles(client)
    await say(client, conversation, 1)
    after_three = await listed_titles(client)
    await say(client, conversation, 1)
    after_four = await listed_titles(client)

    assert (after_two, after_three, after_four) == ([None], [TITLE], [TITLE])
    assert len(background.prompts) == 1


async def test_naming_holds_up_no_reply(make_client: ClientFactory):
    gate = asyncio.Event()
    client = make_client(FakeLLM(*[REPLY] * 3), background_llm=FakeBackgroundLLM(TITLE, gate=gate))
    conversation = await start_conversation(client)
    await say(client, conversation, 2)

    third = await send_turn(client, conversation, "第三句")  # done with the model still naming
    gate.set()

    assert third[-1]["type"] == "done"
    assert await listed_titles(client) == [TITLE]


async def test_the_model_reads_the_first_turns_in_order_with_their_events_and_her_subtitles(
    make_client: ClientFactory, settings: Settings
):
    background = FakeBackgroundLLM(TITLE)
    cued = ["<ja>[happily] いいですね</ja><zh>[happily] 好啊</zh>"]
    client = make_client(FakeLLM(cued, REPLY, REPLY, REPLY), background_llm=background)
    conversation = await start_conversation(client)

    await send_turn(client, conversation, "我想去看海")
    hang_up(settings.database_path, conversation)
    await send_turn(client, conversation, "海" * 200)
    give_pudding(settings.database_path, conversation)
    await send_turn(client, conversation, "第三句")
    await listed_titles(client)
    await send_turn(client, conversation, "第四句")

    [prompt] = background.prompts
    assert prompt[0].role == "system" and "起标题" in prompt[0].content
    assert fed(prompt) == [
        "# 制作人和櫻木真乃的对话",
        "制作人：我想去看海",
        "櫻木真乃：好啊",
        "（櫻木真乃挂断了电话）",
        f"制作人：{'海' * 150}…",
        "櫻木真乃：好的",
        "（制作人送给櫻木真乃一份布丁）",
        "制作人：第三句",
        "櫻木真乃：好的",
    ]


async def test_with_memory_on_it_is_named_from_no_memories_and_neither_she_nor_memory_reads_it(
    make_client: ClientFactory, caplog: pytest.LogCaptureFixture
):
    llm = FakeLLM(*[REPLY] * 4)
    background = FakeBackgroundLLM(*[answering(TITLE, memorized(CAT))] * 5)
    client = make_client(
        llm, retrieval_judge=FakeJudge("memories"), embedder=FakeEmbedder(),
        reranker=FakeReranker("制作人"), background_llm=background,
    )
    conversation = await start_conversation(client)
    await say(client, conversation, 3)
    titled = await listed_titles(client)

    await say(client, conversation, 1)

    assert titled == [TITLE]
    assert [m["text"] for m in (await client.get("/api/memories")).json()] == [CAT]
    [named] = naming(background.prompts)
    assert CAT not in named
    # Her prompts, and what memory read after it was named, never carry it; nor do the logs.
    prompts = [*llm.prompts, *background.prompts]
    assert not any(TITLE in m.content for prompt in prompts for m in prompt)
    assert TITLE not in caplog.text


async def test_she_ending_the_conversation_in_its_third_turn_names_it_all_the_same(
    make_client: ClientFactory, settings: Settings
):
    background = FakeBackgroundLLM(TITLE)
    client, _ = client_judging(
        make_client, [level(2), OUT_OF_LINE, OUT_OF_LINE], background_llm=background,
        settings=replace(settings, judge=FAKE_JUDGE, affinity_and_gifts=True),
    )
    conversation = await start_conversation(client)

    turns = [await send_turn(client, conversation, f"第{i}句") for i in range(3)]

    assert ended_by(turns[-1])
    assert await listed_titles(client) == [TITLE]
    [prompt] = background.prompts
    assert fed(prompt)[-1] == "（櫻木真乃结束了对话）"


async def test_a_turn_in_a_call_counts_among_the_three(
    make_client: ClientFactory, speech: FakeSpeech, browser: Browser
):
    background = FakeBackgroundLLM(TITLE)
    client = make_client(FakeLLM(*[REPLY] * 3), background_llm=background)
    conversation = await start_conversation(client)
    await say(client, conversation, 2)
    await browser.call(client, conversation_id=conversation)
    await browser.connect()

    in_call = await say_in_call(speech, browser, "我想去看海")

    assert in_call[-1]["type"] == "done"
    assert await listed_titles(client) == [TITLE]
    [prompt] = background.prompts
    assert fed(prompt)[-2] == "制作人：我想去看海"


@pytest.mark.parametrize(
    ("answer", "title"),
    [
        ('标题："约好去看《海的声音》演唱会"！\n这段对话主要在聊……', "约好去看海的声音演唱会"),
        ("  \n一起商量周末要去哪片海边看日出，吃什么", "一起商量周末要去哪片海边看日出"),  # cut, then stripped
    ],
)
async def test_the_answer_is_cut_down_to_a_title(
    make_client: ClientFactory, answer: str, title: str
):
    client = make_client(FakeLLM(*[REPLY] * 3), background_llm=FakeBackgroundLLM(answer))
    conversation = await start_conversation(client)

    await say(client, conversation, 3)

    assert await listed_titles(client) == [title]


@pytest.mark.parametrize("answer", [LLMError("模型返回 503: 我想去看海"), "「」。"])
async def test_a_conversation_not_named_has_no_title_and_is_not_named_again(
    make_client: ClientFactory, caplog: pytest.LogCaptureFixture, answer: str | Exception
):
    background = FakeBackgroundLLM(answer, TITLE)
    client = make_client(FakeLLM(*[REPLY] * 4), background_llm=background)
    conversation = await start_conversation(client)

    await send_turn(client, conversation, "我想去看海")
    await say(client, conversation, 1)
    third = await send_turn(client, conversation, "第三句")
    after_three = await listed_titles(client)
    await say(client, conversation, 1)

    assert third[-1]["type"] == "done"
    assert (after_three, await listed_titles(client)) == ([None], [None])
    assert len(background.prompts) == 1
    assert "naming conversation" in caplog.text or "named conversation" in caplog.text
    assert "看海" not in caplog.text


async def test_a_turn_on_an_own_background_model_is_named_by_it(
    make_client: ClientFactory, own_llm: FakeLLMService
):
    own_llm.llm = FakeLLM(REPLY, REPLY, REPLY, [TITLE])
    deployers_background = FakeBackgroundLLM()
    client = make_client(FakeLLM(), background_llm=deployers_background)
    conversation = await start_conversation(client)
    own_keys = {"llm": THINKING, "memory_llm": MEMORY_LLM}

    for text in ["第一句", "第二句", "第三句"]:
        assert done_of(await send_turn(client, conversation, text, own_keys=own_keys))["type"] == "done"

    assert await listed_titles(client) == [TITLE]
    assert own_llm.llm.keys == [MINE, MINE, MINE, MEMORY_KEY]
    assert own_llm.efforts[-1] == "low"  # its own effort
    assert deployers_background.prompts == []


async def test_the_deployers_background_model_replaced_while_naming_is_closed_once_named(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    clients = FakeServiceClients(FakeLLM(*[REPLY] * 3))
    gate = asyncio.Event()
    clients.background = FakeBackgroundLLM(TITLE, gate=gate)
    admins = replace(settings, admins=frozenset({("github", "1001")}))
    client = await live_admin_client(make_client, admins, github, clients)
    conversation = await start_conversation(client)
    assert (await client.put(BACKGROUND_CONFIG, json=NEW_MEMORY)).status_code == 200
    await say(client, conversation, 3)  # named after the third, with memory off

    other = NEW_MEMORY | {"api_key": "sk-other-key-9999"}
    assert (await client.put(BACKGROUND_CONFIG, json=other)).status_code == 200
    closed_while_naming = list(clients.closed)
    gate.set()
    titles = await listed_titles(client)

    assert NEW_MEMORY_SETTINGS not in closed_while_naming
    assert titles == [TITLE]
    assert clients.closed == [ENV_SETTINGS, NEW_MEMORY_SETTINGS]


async def test_the_dashboard_counts_naming_as_the_background_models_and_never_shows_a_title(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    clock = FakeClock()
    client = make_client(FakeLLM(*[REPLY] * 3), clock=clock, background_llm=FakeBackgroundLLM(TITLE))
    admin = await admin_client(
        make_client, github, clock,
        settings=replace(settings, admins=frozenset({("github", "1001")})),
    )
    conversation = await start_conversation(client)
    await say(client, conversation, 3)
    assert await listed_titles(client) == [TITLE]

    board = await dashboard(admin)

    background = health(board, "memory_llm")
    assert background is not None and (background["calls"], background["errors"]) == (1, 0)
    assert TITLE not in str(board)


async def test_deleting_the_user_deletes_the_titles_of_their_conversations(
    make_client: ClientFactory, settings: Settings
):
    client = make_client(FakeLLM(*[REPLY] * 3), background_llm=FakeBackgroundLLM(TITLE))
    await say(client, await start_conversation(client), 3)
    assert await listed_titles(client) == [TITLE]

    assert (await client.post("/api/account/delete", json=DELETE)).status_code == 204

    assert rows_mentioning(settings.database_path, TITLE) == {}


async def test_a_database_from_before_titles_lists_its_conversations_untitled_and_names_new_turns(
    make_client: ClientFactory, settings: Settings
):
    client = make_client(FakeLLM(REPLY))
    old = await start_conversation(client)
    await say(client, old, 1)
    with sqlite3.connect(settings.database_path) as db:  # as the table was before titles
        db.execute("ALTER TABLE conversations DROP COLUMN title")

    reopened = make_client(FakeLLM(REPLY, REPLY), background_llm=FakeBackgroundLLM(TITLE))
    untitled = await listed_titles(reopened)
    await say(reopened, old, 2)

    assert (untitled, await listed_titles(reopened)) == ([None], [TITLE])
