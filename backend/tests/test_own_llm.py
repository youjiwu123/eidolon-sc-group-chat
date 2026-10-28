"""Bringing your own LLM: tried once, without being kept, before the browser keeps it; then
brought with each of the user's text turns and calls, which it plays the character and
writes down memories on instead of the deployer's; memories on another model of the user's
own, if they bring one with it, tried and brought as it is. It fails loudly rather than falling
back to the deployer's key. The server keeps none, nor needs `EIDOLON_SECRET_KEY` for them;
those it kept before are deleted."""

import asyncio
import sqlite3
from dataclasses import replace

import httpcore
import httpx
import pytest

from eidolon.config import ChatModelSettings, LLMSettings, Settings, UsageLimits
from eidolon.llm import ChatMessage, LLMError
from eidolon.own_keys import ProviderLLMService, PublicOnlyBackend
from tests.browser import Browser
from tests.conftest import ClientFactory
from tests.fakes import (
    DEPLOYER_KEY,
    FakeBackgroundLLM,
    FakeEmbedder,
    FakeJudge,
    FakeLLM,
    FakeLLMService,
    FakeReranker,
    FakeSpeech,
)
from tests.test_delete_account import rows_mentioning
from tests.test_shared_memory import CAT, memorized
from tests.test_text_turn import done_of, send_turn, start_conversation

REPLY = ["<ja>はいっ</ja><zh>好的</zh>"]
MINE = "sk-my-own-key-1234"
LLM = {
    "base_url": "https://llm.example.com/v1",
    "api_key": MINE,
    "model": "my-model",
    "protocol": "chat-completions",
}


THINKING = LLM | {
    "reasoning_effort": "high",
    "call_reasoning_effort": "none",
    "extra_body": {"enable_thinking": True},
}
"""An own LLM set to think hard in text turns, and not at all in calls."""


async def check_llm(client: httpx.AsyncClient, **changes: object) -> httpx.Response:
    return await client.post("/api/account/keys/llm/check", json=LLM | changes)


async def test_an_own_llm_is_tried_and_not_kept(
    make_client: ClientFactory, own_llm: FakeLLMService, settings: Settings
):
    client = make_client(FakeLLM())

    checked = await check_llm(client, base_url=" https://llm.example.com/v1 ", model=" my-model ")

    assert checked.status_code == 200
    assert checked.json() == {"base_url": "https://llm.example.com/v1", "model": "my-model"}
    assert [(s.text.api_key, s.text.base_url, s.text.model) for s in own_llm.checked] == [
        (MINE, "https://llm.example.com/v1", "my-model")
    ]
    assert MINE not in checked.text
    assert rows_mentioning(settings.database_path, "my-model") == {}


async def test_a_turn_bringing_an_own_llm_plays_on_it_and_one_bringing_none_on_the_deployers(
    make_client: ClientFactory, own_llm: FakeLLMService
):
    deployers = FakeLLM(REPLY)
    own_llm.llm = FakeLLM(REPLY)
    client = make_client(deployers)
    conversation_id = await start_conversation(client)

    on_own = await send_turn(client, conversation_id, "在吗", own_llm=LLM)

    assert done_of(on_own)["type"] == "done"
    assert own_llm.llm.keys == [MINE]
    assert own_llm.opened[-1].base_url == "https://llm.example.com/v1"
    assert own_llm.opened[-1].model == "my-model"
    # Kept by a page from before efforts were, it sends none: the model's own default holds.
    assert own_llm.efforts == [None] and own_llm.opened[-1].extra_body is None
    assert deployers.keys == []

    on_deployers = await send_turn(client, conversation_id, "在吗")

    assert done_of(on_deployers)["type"] == "done"
    assert deployers.keys == [DEPLOYER_KEY]
    assert own_llm.llm.keys == [MINE]


async def test_a_turn_from_a_page_from_before_bringing_own_llm_is_told_to_refresh(
    make_client: ClientFactory, own_llm: FakeLLMService, settings: Settings
):
    own_llm.llm = FakeLLM(REPLY)
    deployers = FakeLLM(REPLY)
    one_turn = replace(settings, usage_limits=UsageLimits(turns_per_hour=1))
    client = make_client(deployers, settings=one_turn)
    conversation_id = await start_conversation(client)

    refused = await client.post(
        f"/api/conversations/{conversation_id}/turns", json={"text": "在吗", "own_llm": LLM}
    )

    assert refused.status_code == 422
    assert "刷新" in refused.json()["detail"]
    assert MINE not in refused.text
    assert own_llm.llm.keys == [] and deployers.keys == []
    # Not counted: the one turn the limit allows is still there.
    assert done_of(await send_turn(client, conversation_id, "在吗"))["type"] == "done"


async def test_the_users_own_llm_writes_down_their_memories(
    make_client: ClientFactory, own_llm: FakeLLMService
):
    own_llm.llm = FakeLLM(REPLY, [memorized(CAT)])
    deployers_background = FakeBackgroundLLM()
    client = make_client(
        FakeLLM(), retrieval_judge=FakeJudge(), embedder=FakeEmbedder(), reranker=FakeReranker("制作人"),
        background_llm=deployers_background,
    )

    await send_turn(client, await start_conversation(client), "我家的猫叫小白哦", own_llm=THINKING)

    assert [m["text"] for m in (await client.get("/api/memories")).json()] == [CAT]
    assert own_llm.llm.keys == [MINE, MINE]
    assert deployers_background.prompts == []
    # Both at its text effort, with its extra body.
    assert own_llm.efforts == ["high", "high"]
    assert {str(s.extra_body) for s in own_llm.opened} == {"{'enable_thinking': True}"}


async def test_a_failing_own_llm_fails_the_turn_without_the_deployers_key_or_counting_it(
    make_client: ClientFactory, own_llm: FakeLLMService, settings: Settings
):
    own_llm.llm = FakeLLM(LLMError("402 Payment Required: insufficient balance"), REPLY)
    deployers = FakeLLM(REPLY)
    one_turn = replace(settings, usage_limits=UsageLimits(turns_per_hour=1))
    client = make_client(deployers, settings=one_turn)
    conversation_id = await start_conversation(client)

    failed = await send_turn(client, conversation_id, "在吗", own_llm=LLM)
    again = await send_turn(client, conversation_id, "在吗", own_llm=LLM)

    assert failed[-1]["type"] == "error"
    assert "你的LLM密钥调用失败" in failed[-1]["message"]
    assert "402 Payment Required" in failed[-1]["message"]
    assert deployers.keys == []
    # The next turn goes on. Turns on an own LLM never count, so with the limit of one this
    # does not show the failed turn was given back (test_rate_limit does).
    assert done_of(again)["type"] == "done"
    messages = await client.get(f"/api/conversations/{conversation_id}/messages")
    assert len(messages.json()) == 2


async def test_without_a_secret_key_users_still_bring_their_own(
    make_client: ClientFactory, settings: Settings, own_llm: FakeLLMService
):
    own_llm.llm = FakeLLM(REPLY)
    client = make_client(FakeLLM(), settings=replace(settings, secret_key=None))

    checked = await check_llm(client)
    turn = await send_turn(client, await start_conversation(client), "在吗", own_llm=LLM)

    assert checked.status_code == 200
    assert done_of(turn)["type"] == "done"
    assert own_llm.llm.keys == [MINE]


async def test_keys_the_server_kept_before_are_deleted(
    make_client: ClientFactory, settings: Settings
):
    make_client(FakeLLM())
    with sqlite3.connect(settings.database_path) as db:  # as they were kept, encrypted
        db.execute("CREATE TABLE own_keys (user_id TEXT, service TEXT, secret BLOB)")
        db.execute("INSERT INTO own_keys VALUES ('someone', 'llm', x'00ff')")

    make_client(FakeLLM())

    with sqlite3.connect(settings.database_path) as db:
        tables = {name for (name,) in db.execute("SELECT name FROM sqlite_master")}
    assert "own_keys" not in tables


async def test_trying_needs_a_plausible_key(make_client: ClientFactory, own_llm: FakeLLMService):
    client = make_client(FakeLLM())

    for bad in ({"api_key": "short"}, {"api_key": "has space in it"}, {"model": ""},
                {"protocol": "grpc"}):
        assert (await check_llm(client, **bad)).status_code == 422, bad
    assert own_llm.checked == []


async def test_a_call_uses_the_users_own_llm(
    make_client: ClientFactory, own_llm: FakeLLMService, speech: FakeSpeech, browser: Browser
):
    own_llm.llm = FakeLLM(REPLY)
    deployers = FakeLLM()
    client = make_client(deployers)
    await browser.call(
        client, conversation_id=await start_conversation(client), own_keys={"llm": LLM}
    )
    await browser.connect()

    await speech.stts[-1].hear("你好")
    messages = await browser.turn()

    assert messages[-1]["type"] == "done"
    assert own_llm.llm.keys == [MINE]
    assert deployers.keys == []


async def test_a_call_on_an_own_llm_talks_at_its_call_effort_and_writes_down_memories_at_its_text_one(
    make_client: ClientFactory, own_llm: FakeLLMService, speech: FakeSpeech, browser: Browser
):
    own_llm.llm = FakeLLM(REPLY, [memorized(CAT)])
    client = make_client(
        FakeLLM(), retrieval_judge=FakeJudge(), embedder=FakeEmbedder(), reranker=FakeReranker("制作人"),
    )
    await browser.call(
        client, conversation_id=await start_conversation(client), own_keys={"llm": THINKING}
    )
    await browser.connect()

    await speech.stts[-1].hear("我家的猫叫小白哦")
    assert (await browser.turn())[-1]["type"] == "done"
    async with asyncio.timeout(5):  # written down after the turn
        while len(own_llm.efforts) < 2:
            await asyncio.sleep(0.01)

    assert own_llm.efforts == ["none", "high"]
    assert {str(s.extra_body) for s in own_llm.opened} == {"{'enable_thinking': True}"}


SET_WRONGLY = [
    {"extra_body": {"messages": [], "enable_thinking": False}},
    {"protocol": "anthropic", "call_reasoning_effort": "minimal"},
]


@pytest.mark.parametrize("wrong", SET_WRONGLY)
async def test_a_turn_or_call_bringing_an_own_llm_set_wrongly_is_refused_not_sent(
    make_client: ClientFactory, own_llm: FakeLLMService, browser: Browser, wrong: dict
):
    deployers = FakeLLM(REPLY)
    client = make_client(deployers)
    conversation_id = await start_conversation(client)

    turn = await client.post(
        f"/api/conversations/{conversation_id}/turns",
        json={"text": "在吗", "own_keys": {"llm": LLM | wrong}},
    )
    call = await browser.call(
        client, conversation_id=conversation_id, own_keys={"llm": LLM | wrong}
    )

    assert turn.status_code == 422 and call.status_code == 422
    assert own_llm.opened == [] and deployers.keys == []


async def test_trying_an_own_llm_tries_its_text_and_call_efforts(
    make_client: ClientFactory, own_llm: FakeLLMService
):
    client = make_client(FakeLLM())

    tried = await check_llm(client, reasoning_effort="high", call_reasoning_effort="none")

    assert tried.status_code == 200
    assert own_llm.efforts_checked == ["high", "none"]


async def test_trying_an_own_llm_says_which_effort_the_service_refused(
    make_client: ClientFactory, own_llm: FakeLLMService
):
    own_llm.refused_efforts["none"] = f"模型返回 400: Invalid reasoning_effort for key {MINE}"
    client = make_client(FakeLLM())

    refused = await check_llm(client, reasoning_effort="high", call_reasoning_effort="none")

    assert refused.status_code == 422
    assert refused.json()["detail"] == (
        "试调失败：通话的思考强度『关闭』被服务拒绝：模型返回 400: Invalid reasoning_effort for key ***"
    )


async def test_trying_an_own_llm_with_an_extra_body_that_would_break_the_request_says_why(
    make_client: ClientFactory, own_llm: FakeLLMService
):
    client = make_client(FakeLLM())

    refused = await check_llm(client, extra_body={"model": "x", "tools": [], "thinking": {}})
    not_object = await check_llm(client, extra_body="enable_thinking")

    assert refused.status_code == 422 and not_object.status_code == 422
    assert "「model」、「tools」" in refused.json()["detail"][0]["msg"]
    assert "JSON 对象" in not_object.json()["detail"][0]["msg"]
    assert own_llm.checked == []


MEMORY_KEY = "sk-my-memory-key-5678"
MEMORY_LLM = {
    "base_url": "https://cheap.example.com/v1",
    "api_key": MEMORY_KEY,
    "model": "cheap-model",
    "protocol": "chat-completions",
    "reasoning_effort": "low",
    "extra_body": {"thinking": {"type": "disabled"}},
}
"""A cheaper model of the user's own for writing down their memories, at an effort and with
an extra body of its own."""


async def check_memory_llm(client: httpx.AsyncClient, **changes: object) -> httpx.Response:
    return await client.post("/api/account/keys/memory-llm/check", json=MEMORY_LLM | changes)


async def test_an_own_memory_llm_writes_down_memories_while_the_own_llm_plays(
    make_client: ClientFactory, own_llm: FakeLLMService
):
    own_llm.llm = FakeLLM(REPLY, [memorized(CAT)])
    deployers_background = FakeBackgroundLLM()
    client = make_client(
        FakeLLM(), retrieval_judge=FakeJudge(), embedder=FakeEmbedder(), reranker=FakeReranker("制作人"),
        background_llm=deployers_background,
    )

    await send_turn(
        client, await start_conversation(client), "我家的猫叫小白哦",
        own_keys={"llm": THINKING, "memory_llm": MEMORY_LLM},
    )

    assert [m["text"] for m in (await client.get("/api/memories")).json()] == [CAT]
    assert own_llm.llm.keys == [MINE, MEMORY_KEY]
    assert deployers_background.prompts == []
    # Each at its own effort, with its own extra body: not the own LLM's text effort.
    assert own_llm.efforts == ["high", "low"]
    assert [(s.base_url, s.model, s.extra_body) for s in own_llm.opened] == [
        ("https://llm.example.com/v1", "my-model", {"enable_thinking": True}),
        ("https://cheap.example.com/v1", "cheap-model", {"thinking": {"type": "disabled"}}),
    ]


async def test_a_call_on_an_own_llm_writes_down_memories_on_an_own_memory_llm(
    make_client: ClientFactory, own_llm: FakeLLMService, speech: FakeSpeech, browser: Browser
):
    own_llm.llm = FakeLLM(REPLY, [memorized(CAT)])
    client = make_client(
        FakeLLM(), retrieval_judge=FakeJudge(), embedder=FakeEmbedder(), reranker=FakeReranker("制作人"),
    )
    await browser.call(
        client, conversation_id=await start_conversation(client),
        own_keys={"llm": THINKING, "memory_llm": MEMORY_LLM},
    )
    await browser.connect()

    await speech.stts[-1].hear("我家的猫叫小白哦")
    assert (await browser.turn())[-1]["type"] == "done"
    async with asyncio.timeout(5):  # written down after the turn
        while len(own_llm.efforts) < 2:
            await asyncio.sleep(0.01)

    assert own_llm.llm.keys == [MINE, MEMORY_KEY]
    assert own_llm.efforts == ["none", "low"]


@pytest.mark.parametrize(
    "own_keys",
    [
        {"memory_llm": MEMORY_LLM},
        # Checked as their own LLM is (see the test of it set wrongly).
        {"llm": LLM, "memory_llm": MEMORY_LLM | {"extra_body": {"messages": []}}},
    ],
    ids=["without-an-own-llm", "set-wrongly"],
)
async def test_a_turn_or_call_bringing_an_own_memory_llm_alone_or_set_wrongly_is_refused_not_sent(
    make_client: ClientFactory, own_llm: FakeLLMService, browser: Browser, own_keys: dict
):
    deployers = FakeLLM(REPLY)
    client = make_client(deployers)
    conversation_id = await start_conversation(client)

    turn = await client.post(
        f"/api/conversations/{conversation_id}/turns", json={"text": "在吗", "own_keys": own_keys}
    )
    call = await browser.call(client, conversation_id=conversation_id, own_keys=own_keys)

    assert turn.status_code == 422 and call.status_code == 422
    assert own_llm.opened == [] and deployers.keys == []


async def test_an_own_memory_llm_is_tried_once_at_its_effort_and_not_kept(
    make_client: ClientFactory, own_llm: FakeLLMService, settings: Settings
):
    client = make_client(FakeLLM())

    checked = await check_memory_llm(client, model=" cheap-model ")

    assert checked.status_code == 200
    assert checked.json() == {"base_url": "https://cheap.example.com/v1", "model": "cheap-model"}
    assert [(s.text.api_key, s.text.extra_body) for s in own_llm.checked] == [
        (MEMORY_KEY, {"thinking": {"type": "disabled"}})
    ]
    assert own_llm.efforts_checked == ["low"]
    assert MEMORY_KEY not in checked.text
    assert rows_mentioning(settings.database_path, "cheap-model") == {}


async def test_trying_an_own_memory_llm_says_it_was_that_one_that_failed(
    make_client: ClientFactory, own_llm: FakeLLMService
):
    client = make_client(FakeLLM())

    own_llm.refused_efforts["low"] = f"模型返回 400: Invalid reasoning_effort for key {MEMORY_KEY}"
    refused_effort = await check_memory_llm(client)
    own_llm.rejects[MEMORY_KEY] = f"401 Unauthorized: bad key {MEMORY_KEY}"
    rejected = await check_memory_llm(client)

    assert refused_effort.status_code == 422 and rejected.status_code == 422
    assert refused_effort.json()["detail"] == (
        "试调失败：后台模型：思考强度『低』被服务拒绝：模型返回 400: Invalid reasoning_effort for key ***"
    )
    assert rejected.json()["detail"] == "试调失败：后台模型：401 Unauthorized: bad key ***"


@pytest.mark.parametrize(
    "base_url",
    ["http://llm.example.com/v1", "https://127.0.0.1:8000/v1", "https://localhost/v1",
     "https://[::1]/v1", "https://169.254.169.254/latest", "https://10.0.0.8/v1"],
)
async def test_a_public_deployment_tries_only_llms_on_the_public_internet(base_url: str):
    service = ProviderLLMService(public_only=True)
    try:
        with pytest.raises(LLMError, match="https|公网地址"):
            await service.check(ChatModelSettings(LLMSettings(base_url, MINE, "m")))
    finally:
        await service.aclose()


class FakeNetwork(httpcore.AsyncNetworkBackend):
    """Records where it was asked to connect, and connects nowhere."""

    def __init__(self) -> None:
        self.connected: list[str] = []

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):  # type: ignore[override]
        self.connected.append(host)
        raise httpcore.ConnectError("fake network")


async def test_every_connection_to_an_own_llm_goes_to_the_public_address_it_checked():
    answers = [["93.184.216.34"], ["127.0.0.1"]]  # the name is rebound after the first check

    async def resolver(host: str, port: int) -> list[str]:
        return answers.pop(0)

    network = FakeNetwork()
    backend = PublicOnlyBackend(network, resolver)

    with pytest.raises(httpcore.ConnectError, match="fake network"):
        await backend.connect_tcp("llm.example.com", 443)
    with pytest.raises(httpcore.ConnectError, match="不是公网地址"):
        await backend.connect_tcp("llm.example.com", 443)

    assert network.connected == ["93.184.216.34"]  # the checked address, never the name


async def test_a_public_deployment_never_reaches_a_private_address_on_an_own_llm_a_turn_brings():
    service = ProviderLLMService(public_only=True)
    llm = service.open(LLMSettings("https://localhost:9/v1", MINE, "m"))  # brought, not tried
    try:
        with pytest.raises(LLMError, match="不是公网地址"):
            async for _ in llm.stream([ChatMessage("user", "hi")]):
                pass
    finally:
        await service.aclose()
