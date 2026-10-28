"""Text conversation turns, driven through the backend's external API."""

import asyncio
import json

import httpx

from eidolon.llm import ChatMessage
from eidolon.reply_format import FORMAT_INSTRUCTIONS
from tests.conftest import MANO_SHEET, ClientFactory
from tests.fakes import FakeJudge, FakeLLM, feeling, system_of


async def start_conversation(client: httpx.AsyncClient, character: str = "mano") -> str:
    res = await client.post("/api/conversations", json={"character_id": character})
    assert res.status_code == 201
    return res.json()["id"]


async def send_turn(
    client: httpx.AsyncClient,
    conversation_id: str,
    text: str,
    own_llm: dict | None = None,
    *,
    own_keys: dict | None = None,
) -> list[dict]:
    """Send a text turn, bringing the user's `own_keys` if given, or else their `own_llm`
    alone (as `own_keys`, which turns and calls bring alike), and collect the server-sent
    events it streams back."""
    events: list[dict] = []
    own_keys = own_keys or ({"llm": own_llm} if own_llm else None)
    body = {"text": text} | ({"own_keys": own_keys} if own_keys else {})
    async with client.stream(
        "POST", f"/api/conversations/{conversation_id}/turns", json=body
    ) as res:
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/event-stream")
        async for line in res.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line.removeprefix("data: ")))
    return events


def close_of(events: list[dict]) -> dict:
    """The event that closes a turn, `done` or `error`: her reply as the turn records it, or
    why there is none. When the deployer has a judge model, an `emotion` event follows `done`
    (DESIGN.md「对话页的立绘小人」), so the last event is not the closing one."""
    for event in reversed(events):
        if event["type"] in ("done", "error"):
            return event
    raise AssertionError(f"这一回合没有收尾：{[e['type'] for e in events]}")


def done_of(events: list[dict]) -> dict:
    """The `done` event of a turn: her reply, as the turn closes and records it (see
    `close_of`). An `error` fails the test."""
    closed = close_of(events)
    assert closed["type"] == "done", closed
    return closed


async def leave_turn(
    client: httpx.AsyncClient, conversation_id: str, text: str, *, after: str
) -> list[dict]:
    """Send a text turn and leave, closing the page, as soon as an event of type `after`
    arrives; the events that came by then.

    Closing `client.stream(...)` early never reaches the app: httpx's ASGITransport runs
    the app to the end first. So this drives the app as uvicorn does, on ASGI spec 2.3,
    where the streaming response listens for `http.disconnect` and cancels the stream."""
    request = client.build_request(
        "POST", f"/api/conversations/{conversation_id}/turns", json={"text": text}
    )
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": request.method,
        "scheme": "http",
        "path": request.url.path,
        "raw_path": request.url.raw_path,
        "query_string": b"",
        "headers": [(name.lower(), value) for name, value in request.headers.raw],
        "server": ("test", 80),
        "client": ("127.0.0.1", 50000),
        "root_path": "",
    }
    events: list[dict] = []
    left = asyncio.Event()
    sent = False

    async def receive() -> dict:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": request.content, "more_body": False}
        await left.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        if message["type"] == "http.response.start":
            assert message["status"] == 200
        for line in message.get("body", b"").decode().splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line.removeprefix("data: ")))
                if events[-1]["type"] == after:
                    left.set()

    app = client._transport.app  # pyright: ignore[reportAttributeAccessIssue]
    await asyncio.wait_for(app(scope, receive, send), timeout=5)
    return events


async def test_reply_streams_japanese_and_chinese_subtitle(make_client: ClientFactory):
    llm = FakeLLM(["<ja>こんにちは、プロデューサーさん！</ja><zh>你好，制作人！</zh>"])
    client = make_client(llm)
    conversation_id = await start_conversation(client)

    events = await send_turn(client, conversation_id, "你好呀")

    assert events[0] == {"type": "user", "text": "你好呀"}
    done = done_of(events)
    assert done["message"]["ja"] == "こんにちは、プロデューサーさん！"
    assert done["message"]["zh"] == "你好，制作人！"


async def test_how_she_said_it_is_judged_once_the_reply_is_recorded_and_follows_done(
    make_client: ClientFactory,
):
    """DESIGN.md「对话页的立绘小人」: 回复记下以后再按整条回复判一次语气，`emotion` 事件跟在
    `done` 后面，不拖慢回复；判得多有把握也一起带下来，立绘照着摆动作。"""
    judge = FakeJudge(answer="nothing", emotions=[feeling("happy", 0.8, nod="yes")])
    client = make_client(FakeLLM(["<ja>うれしいです！</ja><zh>好开心！</zh>"]), retrieval_judge=judge)
    conversation_id = await start_conversation(client)

    events = await send_turn(client, conversation_id, "今天也很努力呢")

    assert [e["type"] for e in events][-2:] == ["done", "emotion"]
    assert events[-1] == {"type": "emotion", "emotion": "happy", "nod": "yes", "strength": 0.8}
    # 整条回复问一次，得到的也是她这一整句说的话。
    assert [(s.ja, s.zh) for s in judge.segments] == [("うれしいです！", "好开心！")]
    assert done_of(events)["message"]["ja"] == "うれしいです！"


def deltas(events: list[dict], lang: str) -> list[tuple[int, str]]:
    return [(e["segment"], e["text"]) for e in events if e["type"] == "delta" and e["lang"] == lang]


async def test_reply_is_streamed_segment_by_segment_even_when_tags_are_split(
    make_client: ClientFactory,
):
    llm = FakeLLM(
        ["<j", "a>ほわっ、", "プロデューサーさん", "！</", "ja><zh>哇，制作人！", "</zh>\n",
         "<ja>今日は</ja><", "zh>今天</zh>"]
    )
    client = make_client(llm)
    conversation_id = await start_conversation(client)

    events = await send_turn(client, conversation_id, "こんにちは")

    assert deltas(events, "ja") == [(0, "ほわっ、"), (0, "プロデューサーさん"), (0, "！"), (1, "今日は")]
    assert deltas(events, "zh") == [(0, "哇，制作人！"), (1, "今天")]
    assert events[-1]["message"]["ja"] == "ほわっ、プロデューサーさん！今日は"
    assert events[-1]["message"]["zh"] == "哇，制作人！今天"


async def test_reply_that_ignores_the_format_is_kept_as_japanese(make_client: ClientFactory):
    client = make_client(FakeLLM(["えっと、", "ありがとうございますっ"]))
    conversation_id = await start_conversation(client)

    events = await send_turn(client, conversation_id, "谢谢")

    assert events[-1]["message"]["ja"] == "えっと、ありがとうございますっ"
    assert events[-1]["message"]["zh"] == ""


async def test_both_sides_of_a_turn_are_kept_in_the_conversation_record(
    make_client: ClientFactory,
):
    client = make_client(
        FakeLLM(["<ja>おはようございます！</ja><zh>早上好！</zh><ja>ほわっ</ja><zh>哇</zh>"])
    )
    conversation_id = await start_conversation(client)
    await send_turn(client, conversation_id, "早上好")

    reopened = make_client(FakeLLM())
    listed = (await reopened.get("/api/conversations", params={"character_id": "mano"})).json()
    messages = (await reopened.get(f"/api/conversations/{conversation_id}/messages")).json()

    assert [c["id"] for c in listed] == [conversation_id]
    assert [(m["role"], m["text"], m["ja"], m["zh"]) for m in messages] == [
        ("user", "早上好", None, None),
        ("character", None, "おはようございます！ほわっ", "早上好！哇"),
    ]
    assert messages[1]["segments"] == [
        {"ja": "おはようございます！", "zh": "早上好！"},
        {"ja": "ほわっ", "zh": "哇"},
    ]


async def test_prompt_carries_the_character_sheet_and_the_conversation_so_far(
    make_client: ClientFactory,
):
    llm = FakeLLM(
        ["<ja>ピーちゃんです！</ja><zh>是小皮！</zh>"],
        ["<ja>はいっ</ja><zh>嗯！</zh>"],
    )
    client = make_client(llm)
    conversation_id = await start_conversation(client)

    await send_turn(client, conversation_id, "这只鸽子叫什么？")
    await send_turn(client, conversation_id, "好可爱")

    # Without a world setting, the part every user's turns with her share is her sheet and
    # how she is to format her reply.
    assert llm.prompts[1][0] == ChatMessage(
        "system", f"{MANO_SHEET}\n\n{FORMAT_INSTRUCTIONS}", cache_breakpoint=True
    )
    system = system_of(llm.prompts[1])
    assert "櫻木真乃" in system
    assert "<ja>" in system and "<zh>" in system
    assert [(m.role, m.content) for m in llm.prompts[1] if m.role != "system"] == [
        ("user", "这只鸽子叫什么？"),
        ("assistant", "<ja>ピーちゃんです！</ja><zh>是小皮！</zh>"),
        ("user", "好可爱"),
    ]


async def test_conversations_are_kept_apart(make_client: ClientFactory):
    llm = FakeLLM(["<ja>一</ja><zh>一</zh>"], ["<ja>二</ja><zh>二</zh>"])
    client = make_client(llm)
    first = await start_conversation(client)
    second = await start_conversation(client)

    await send_turn(client, first, "第一次")
    await send_turn(client, second, "第二次")

    assert [(m.role, m.content) for m in llm.prompts[1] if m.role != "system"] == [
        ("user", "第二次")
    ]
    listed = (await client.get("/api/conversations", params={"character_id": "mano"})).json()
    assert [c["id"] for c in listed] == [second, first]


async def test_unknown_character_or_conversation_is_rejected(make_client: ClientFactory):
    client = make_client(FakeLLM())

    res = await client.post("/api/conversations", json={"character_id": "nobody"})
    assert res.status_code == 404
    res = await client.post("/api/conversations/missing/turns", json={"text": "hi"})
    assert res.status_code == 404


async def test_reply_cut_off_inside_a_closing_tag_keeps_only_the_text(
    make_client: ClientFactory,
):
    client = make_client(FakeLLM(["<ja>はいっ</ja><zh>好的</z"]))
    conversation_id = await start_conversation(client)

    events = await send_turn(client, conversation_id, "好吗")

    assert events[-1]["message"]["segments"] == [{"ja": "はいっ", "zh": "好的"}]


async def test_a_text_turn_may_put_her_thoughts_in_brackets_when_she_cannot_speak(
    make_client: ClientFactory,
):
    """说不出声的时候，（）里写心里那一句：这条例外排在「对方的动作和心声」的最后，
    模型才看得见它压过前面那条「不写心理活动」；对方用引号写的心里话，只有她设定里写了
    读心才听得见。"""
    llm = FakeLLM(["<ja>（……また来てくれるかな）ふっ</ja><zh>（……他还会来吗）唔</zh>"])
    client = make_client(llm)
    conversation = await start_conversation(client)

    await send_turn(client, conversation, "你怎么不说话")

    context = llm.prompts[-1][-2].content
    actions = context[context.index("# 对方的动作和心声"):]
    assert "不写心理活动" in actions
    assert actions.index("不写心理活动") < actions.index("唯一的例外")
    assert "心里那一句" in actions
    assert "他没说出口的心声" in actions
    assert "你的设定或当前模式写明你能读到他的心声" in actions
    assert "就当没听见" in actions
