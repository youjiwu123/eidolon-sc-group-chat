"""接通时的场景和页首的「现在：…」是同一格：有排期表的角色从 `current_scene` 取背景和
开场白，页首、背景、开场白、提示词的「此刻」四处一致。"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import eidolon.app as app_module
from eidolon.config import Settings
from tests.conftest import SCENES, ClientFactory
from tests.fakes import FakeLLM, system_of
from tests.test_text_turn import send_turn, start_conversation

NOW = datetime(2026, 4, 6, 15, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
"""2026-04-06 周一下午三点：任何时段池都会命中，测试不随真机时钟落在 2:00-6:00 的空白里。"""


class FrozenDatetime(datetime):
    """`app.current_scene` 里的 `datetime.now(Asia/Tokyo)`，钉在这一格上。"""

    @classmethod
    def now(cls, tz=None):  # noqa: ANN001, ANN206 - datetime's own signature
        return NOW if tz is None else NOW.astimezone(tz)


HOLIDAYS = """
[calendar]
timezone = "Asia/Tokyo"

[[holidays]]
id = "new_year"
name = "元旦"
name_ja = "元日"
kind = "public"
dates = ["2000-01-01"]
scenes = ["home"]
weights = [1]
activities = ["在家里的沙发上"]
"""

SCHEDULE = """
[[pools]]
character = "mano"
day = "any"
slot = "any"
chance = 1.0
scene = "home"
activity = "在家里的沙发上"
why = "测试用：什么时候都在家"
"""

OPENER = ['{"opener_ja": "もしもし、[softly] ただいま", "opener_zh": "喂，我回来了"}']
REPLY = ["<ja>うん</ja><zh>嗯</zh>"]


def write_world(settings: Settings, *, with_schedule: bool) -> None:
    """Write the scene table `create_app` reads, and, for Mano, her week."""
    directory = settings.characters_path.parent
    (directory / "scenes.toml").write_text(SCENES, encoding="utf-8")
    if with_schedule:
        (directory / "holidays.toml").write_text(HOLIDAYS, encoding="utf-8")
        (directory / "schedules.mano.week.toml").write_text(SCHEDULE, encoding="utf-8")


@pytest.fixture
def afternoon(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module, "datetime", FrozenDatetime)


async def test_a_scheduled_character_calls_from_the_scene_the_page_shows(
    make_client: ClientFactory, settings: Settings, afternoon: None
) -> None:
    write_world(settings, with_schedule=True)
    llm = FakeLLM(OPENER)
    client = make_client(llm)
    conversation = await start_conversation(client)

    scene = (await client.get(f"/api/conversations/{conversation}/scene")).json()
    now = (await client.get(f"/api/conversations/{conversation}/now")).json()

    assert scene["scene"]["id"] == now["scene"]["id"] == "home"
    assert scene["source"] == now["source"] == scene["scene"]["source"] == "pool"
    assert scene["activity"] == now["activity"] == "在家里的沙发上"
    assert scene["until"] == now["until"]

    opener = scene["scene"]["opener"]
    assert opener is not None
    assert "ただいま" in opener["ja"]
    assert opener["zh"] == "喂，我回来了"
    assert "/call-opener/speech?scene=home" in opener["speech_url"]
    # 开场白是按这一格的活动写的，不是她固定的那一句。
    assert "在家里的沙发上" in system_of(llm.prompts[0])

    # 同一格再问一次：同一张，开场白也不重写。
    assert (
        await client.get(f"/api/conversations/{conversation}/scene")
    ).json() == scene
    assert len(llm.prompts) == 1


async def test_a_scheduled_character_with_history_still_calls_from_the_page_scene(
    make_client: ClientFactory, settings: Settings, afternoon: None
) -> None:
    """有聊天记录也不让判断模型换场景：这一格排期说了算，四处的「此刻」才对得上。"""
    write_world(settings, with_schedule=True)
    llm = FakeLLM(REPLY, REPLY, OPENER)
    client = make_client(llm)
    conversation = await start_conversation(client)
    await send_turn(client, conversation, "在干嘛？")
    await send_turn(client, conversation, "一直在练习室吗？")

    scene = (await client.get(f"/api/conversations/{conversation}/scene")).json()
    now = (await client.get(f"/api/conversations/{conversation}/now")).json()

    assert scene["scene"]["id"] == now["scene"]["id"] == "home"
    # 最后一条提示词是开场白的（按这一格的活动写），不是判断场景的那条。
    assert "根据最近这段对话" not in system_of(llm.prompts[-1])
    assert "在家里的沙发上" in system_of(llm.prompts[-1])


async def test_a_character_without_a_schedule_still_calls_from_a_cold_scene(
    make_client: ClientFactory, settings: Settings, afternoon: None
) -> None:
    write_world(settings, with_schedule=False)
    llm = FakeLLM(OPENER)
    client = make_client(llm)
    conversation = await start_conversation(client, "kogane")

    scene = (await client.get(f"/api/conversations/{conversation}/scene")).json()

    assert scene["scene"]["id"] == "studio"
    assert scene["scene"]["source"] == "behavior"
    assert scene["scene"]["opener"] is not None
