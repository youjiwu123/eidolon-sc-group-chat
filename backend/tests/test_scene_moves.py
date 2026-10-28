"""对话里说定换地方就换场景（DESIGN.md「通话场景」）。

这一回合说完、回复记下以后，再问一次对话模型：这两句里是不是说定了换地方（「去咖啡厅吧」
「好啊，走吧」）。说定了就记在这段对话上，并在 `done` 之后发一条 `scene` 事件；页首的
「现在」、通话背景和下一回合提示词里的「此刻」都用它，没搬过才按排期表算。只认说定的：
提一句、开玩笑、没答应都不算。整件事由 `EIDOLON_SCENE_MOVES=1` 打开，默认关着（每回合多一次问）。
"""

from dataclasses import replace
from pathlib import Path

import pytest

from eidolon.config import Settings
from eidolon.scenes import Catalog, Scene, load_scenes, parse_move
from tests.conftest import SCENES, ClientFactory
from tests.fakes import FakeLLM, context_of
from tests.test_text_turn import send_turn, start_conversation

REPLY = ["<ja>いいですね、行きましょう</ja><zh>好啊，走吧</zh>"]
MOVED = ['{"moved": true, "scene": "事务所休息室"}']
STAYED = ['{"moved": false}']


@pytest.fixture
def moving(settings: Settings) -> Settings:
    """开了「说定换地方就换场景」的部署。"""
    return replace(settings, scene_moves=True)


@pytest.fixture
def catalog(tmp_path: Path) -> Catalog:
    """测试用的最小场景表（`tests.conftest.SCENES`：她的家、休息室、练习室、说不准）。"""
    path = tmp_path / "scenes.toml"
    path.write_text(SCENES, encoding="utf-8")
    return load_scenes(path)


def test_the_judged_answer_is_a_scene_only_when_it_says_they_moved(catalog: Catalog):
    assert parse_move(MOVED[0], catalog) == Scene(
        "lounge", "事务所休息室", "沙发、茶水间", "lounge.jpg"
    )
    assert parse_move('{"moved": false}', catalog) is None
    assert parse_move('{"moved": true, "scene": "月球"}', catalog) is None  # 表里没有的不算
    assert parse_move('{"moved": true, "scene": "说不准"}', catalog) is None  # 外景不算搬
    assert parse_move("没有 JSON", catalog) is None
    assert parse_move('{"moved": "yes", "scene": "事务所休息室"}', catalog) is None


async def test_a_turn_that_agrees_to_go_somewhere_moves_her_there(
    make_client: ClientFactory, moving: Settings
):
    llm = FakeLLM(REPLY, MOVED, REPLY)
    client = make_client(llm, settings=moving)
    conversation = await start_conversation(client)

    events = await send_turn(client, conversation, "我们去休息室坐一会儿吧")

    assert [event["type"] for event in events][-2:] == ["done", "scene"]
    assert events[-1] == {
        "type": "scene",
        "scene": {"id": "lounge", "name": "事务所休息室", "image_url": "/api/scenes/lounge"},
    }
    now = (await client.get(f"/api/conversations/{conversation}/now")).json()
    assert (now["scene"]["id"], now["scene"]["name"], now["source"]) == (
        "lounge", "事务所休息室", "chat"
    )
    # 下一回合的「此刻」说的是那儿。
    await send_turn(client, conversation, "这里好安静")
    assert any("你此刻在「事务所休息室」" in context_of(prompt) for prompt in llm.prompts)


async def test_a_turn_that_only_talks_about_going_leaves_her_where_she_was(
    make_client: ClientFactory, moving: Settings
):
    llm = FakeLLM(REPLY, STAYED)
    client = make_client(llm, settings=moving)
    conversation = await start_conversation(client)

    events = await send_turn(client, conversation, "有空要不要去休息室？")

    assert all(event["type"] != "scene" for event in events)
    now = (await client.get(f"/api/conversations/{conversation}/now")).json()
    assert now["source"] != "chat"


@pytest.mark.parametrize("answer", ['{"moved": true, "scene": "月球"}', "不是 JSON"])
async def test_a_move_nowhere_real_changes_nothing(
    make_client: ClientFactory, moving: Settings, answer: str
):
    client = make_client(FakeLLM(REPLY, [answer]), settings=moving)
    conversation = await start_conversation(client)

    events = await send_turn(client, conversation, "去月球吧")

    assert all(event["type"] != "scene" for event in events)
    assert (await client.get(f"/api/conversations/{conversation}/now")).json()["source"] != "chat"


async def test_it_is_judged_after_the_reply_and_does_not_hold_it_up(
    make_client: ClientFactory, moving: Settings
):
    """顺序是 done → scene：回复先出来，换场景是之后的事；问的就是这一来一回。"""
    llm = FakeLLM(REPLY, MOVED)
    client = make_client(llm, settings=moving)
    conversation = await start_conversation(client)

    events = await send_turn(client, conversation, "我们去休息室吧")

    types = [event["type"] for event in events]
    assert types.index("done") < types.index("scene")
    asked = "\n".join(message.content for message in llm.prompts[-1])
    assert "我们去休息室吧" in asked and "いいですね、行きましょう" in asked


async def test_without_the_switch_no_extra_question_is_asked(
    make_client: ClientFactory, settings: Settings
):
    """默认关着：一回合只问一次陪她说话的模型，没有换场景这回事。"""
    llm = FakeLLM(REPLY)
    client = make_client(llm, settings=settings)
    conversation = await start_conversation(client)

    events = await send_turn(client, conversation, "我们去休息室吧")

    assert all(event["type"] != "scene" for event in events)
    assert len(llm.prompts) == 1
