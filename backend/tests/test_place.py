"""Where she is: the conversation page's 「现在：…」 scene goes into the turn's 「此刻」, so she
does not make up a place of her own (GLOSSARY.md「此刻」)."""

from datetime import UTC, datetime

from eidolon.config import Settings
from eidolon.producer import Place, ProducerProfile, now_prompt
from tests.conftest import ClientFactory
from tests.fakes import FakeLLM, context_of
from tests.test_text_turn import send_turn, start_conversation

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
REPLY = ["<ja>小練習室っす</ja><zh>在小练习室哦</zh>"]

SCENES = """
[[scenes]]
id = "studio"
name = "小练习室"
hint = "木地板、镜子"
image = "studio.jpg"

[[scenes]]
id = "sky"
name = "说不准"
hint = "外景天空"
image = "sky.jpg"

[[behaviors]]
character = "*"
scene = "studio"
text = "在练习室练新曲"
"""

HOLIDAYS = """
[calendar]
timezone = "Asia/Tokyo"

[[holidays]]
id = "new_year"
name = "元旦"
name_ja = "元日"
kind = "public"
dates = ["2000-01-01"]
scenes = ["studio"]
weights = [1]
activities = ["在练习室练新曲"]
"""

SCHEDULE = """
[[pools]]
character = "mano"
day = "any"
slot = "any"
chance = 1.0
scene = "studio"
activity = "在练习室练新曲"
why = "测试用：什么时候都在小练习室"
"""


def write_world(settings: Settings, *, with_schedule: bool) -> None:
    """Write the scene table `create_app` reads, and, if `with_schedule`, Mano's week."""
    directory = settings.characters_path.parent
    (directory / "scenes.toml").write_text(SCENES, encoding="utf-8")
    if with_schedule:
        (directory / "holidays.toml").write_text(HOLIDAYS, encoding="utf-8")
        (directory / "schedules.mano.week.toml").write_text(SCHEDULE, encoding="utf-8")


def test_now_prompt_says_where_she_is() -> None:
    text = now_prompt(
        ProducerProfile(), NOW, "Asia/Tokyo", "typing",
        place=Place("小练习室", "在练习室练新曲"),
    )

    assert "# 此刻" in text
    assert (
        "你此刻在「小练习室」：在练习室练新曲。"
        "如果这段对话里你们已经说好去了别处，以对话为准。"
    ) in text


def test_now_prompt_says_nothing_of_a_place_without_one() -> None:
    text = now_prompt(ProducerProfile(), NOW, "Asia/Tokyo", "typing")

    assert "你此刻在" not in text


def test_a_place_without_an_activity_is_just_the_scene() -> None:
    text = now_prompt(
        ProducerProfile(), NOW, "Asia/Tokyo", "typing", place=Place("小练习室")
    )

    lines = [line for line in text.splitlines() if line.startswith("你此刻在")]
    assert lines == [
        "你此刻在「小练习室」。如果这段对话里你们已经说好去了别处，以对话为准。"
    ]


async def test_a_text_turn_tells_her_the_scene_the_page_shows(
    make_client: ClientFactory, settings: Settings
) -> None:
    write_world(settings, with_schedule=True)
    llm = FakeLLM(REPLY)
    client = make_client(llm)
    conversation = await start_conversation(client)

    await send_turn(client, conversation, "你现在在哪？")

    assert (
        "你此刻在「小练习室」：在练习室练新曲。"
        "如果这段对话里你们已经说好去了别处，以对话为准。"
    ) in context_of(llm.prompts[-1])


async def test_a_character_without_a_schedule_is_not_told_a_place(
    make_client: ClientFactory, settings: Settings
) -> None:
    write_world(settings, with_schedule=False)
    llm = FakeLLM(REPLY)
    client = make_client(llm)
    conversation = await start_conversation(client)

    await send_turn(client, conversation, "你现在在哪？")

    assert "你此刻在" not in context_of(llm.prompts[-1])
