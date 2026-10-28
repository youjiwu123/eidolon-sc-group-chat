"""The producer profile: edited through the API, owned by the user rather than one device,
and carried into every conversation's prompt along with the current date and time
in the user's time zone."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from eidolon.config import Settings
from eidolon.store import Store
from tests.conftest import ClientFactory
from tests.fakes import FakeLLM, system_of
from tests.test_text_turn import send_turn, start_conversation

REPLY = ["<ja>はいっ</ja><zh>好的</zh>"]
NOW = datetime(2026, 9, 25, 12, 30, tzinfo=UTC)  # a Friday


def clock() -> datetime:
    return NOW


async def system_prompt(client: httpx.AsyncClient, llm: FakeLLM) -> str:
    conversation_id = await start_conversation(client)
    await send_turn(client, conversation_id, "在吗")
    return system_of(llm.prompts[-1])


async def test_profile_belongs_to_the_user_not_the_device(make_client: ClientFactory):
    desktop = make_client(FakeLLM())

    profile = {
        "form_of_address": "小林",
        "gender": "female",
        "timezone": "Asia/Tokyo",
        "birthday": {"month": 2, "day": 29},
        "special_mode": "",
    }
    res = await desktop.put("/api/profile", json=profile)
    assert res.status_code == 200

    phone = await make_client(FakeLLM()).get("/api/profile")
    assert phone.json() == profile
    friend = await make_client(FakeLLM(), "friend").get("/api/profile")
    assert friend.json() == {
        "form_of_address": None,
        "gender": None,
        "timezone": None,
        "birthday": None,
        "special_mode": "",
    }


FULL_PROFILE = {
    "form_of_address": "小林",
    "gender": "male",
    "timezone": "Asia/Tokyo",
    "birthday": {"month": 5, "day": 3},
    "special_mode": "",
}
EMPTY_PROFILE = {
    "form_of_address": None,
    "gender": None,
    "timezone": None,
    "birthday": None,
    "special_mode": "",
}


async def test_clearing_a_field_restores_its_default(make_client: ClientFactory):
    client = make_client(FakeLLM())
    await client.put("/api/profile", json=FULL_PROFILE)

    res = await client.put(
        "/api/profile",
        json={"form_of_address": "  ", "gender": None, "timezone": None, "birthday": None},
    )

    assert res.json() == EMPTY_PROFILE
    assert (await client.get("/api/profile")).json() == EMPTY_PROFILE


@pytest.mark.parametrize(
    "profile",
    [
        {"form_of_address": "长" * 21},
        {"gender": "unknown"},
        {"timezone": "Mars/Olympus_Mons"},
        {"timezone": "../../etc/passwd"},
        {"timezone": "America"},
        {"timezone": "localtime"},
    ],
    ids=[
        "address-too-long",
        "unknown-gender",
        "unknown-timezone",
        "path-as-timezone",
        "region-as-timezone",
        "server-local-time",
    ],
)
async def test_invalid_profile_is_rejected(make_client: ClientFactory, profile: dict):
    client = make_client(FakeLLM())

    res = await client.put("/api/profile", json=profile)

    assert res.status_code == 422
    assert (await client.get("/api/profile")).json()["timezone"] is None


@pytest.mark.parametrize(
    "birthday",
    [
        {"month": 2, "day": 30},
        {"month": 13, "day": 1},
        {"month": 0, "day": 1},
        {"month": 5, "day": 0},
    ],
    ids=["past-month-end", "month-13", "month-0", "day-0"],
)
async def test_a_birthday_that_is_no_day_of_the_year_is_rejected(
    make_client: ClientFactory, birthday: dict
):
    client = make_client(FakeLLM())
    await client.put("/api/profile", json=FULL_PROFILE)

    res = await client.put("/api/profile", json={**FULL_PROFILE, "birthday": birthday})

    assert res.status_code == 422
    assert (await client.get("/api/profile")).json() == FULL_PROFILE


async def test_profile_needs_a_session(make_client: ClientFactory):
    client = make_client(FakeLLM(), user=None)

    assert (await client.get("/api/profile")).status_code == 401
    assert (await client.put("/api/profile", json={})).status_code == 401


async def test_form_of_address_enters_the_prompt_as_a_way_of_calling_the_producer(
    make_client: ClientFactory,
):
    llm = FakeLLM(REPLY)
    client = make_client(llm)
    await client.put("/api/profile", json={"form_of_address": "小林さん"})

    prompt = await system_prompt(client, llm)

    assert "「小林さん」" in prompt
    assert "仍然是你的制作人" in prompt


async def test_without_a_form_of_address_the_character_sheet_decides(
    make_client: ClientFactory,
):
    llm = FakeLLM(REPLY)
    client = make_client(llm)

    prompt = await system_prompt(client, llm)

    assert "你是櫻木真乃" in prompt
    assert "希望你称呼" not in prompt


async def test_gender_enters_the_prompt_without_rewriting_the_story(
    make_client: ClientFactory,
):
    llm = FakeLLM(REPLY)
    client = make_client(llm)
    await client.put("/api/profile", json={"gender": "female"})

    prompt = await system_prompt(client, llm)

    assert "制作人是女性" in prompt
    assert "剧情中发生过的事保持原样" in prompt


async def test_without_a_gender_the_original_producer_stands(make_client: ClientFactory):
    llm = FakeLLM(REPLY)
    client = make_client(llm)

    prompt = await system_prompt(client, llm)

    assert "制作人是男性" in prompt
    assert "女性" not in prompt


async def test_a_birthday_enters_the_prompt_as_the_producers_own_word(
    make_client: ClientFactory,
):
    llm = FakeLLM(REPLY)
    client = make_client(llm, clock=clock)
    await client.put("/api/profile", json={"birthday": {"month": 5, "day": 3}})

    prompt = await system_prompt(client, llm)

    assert "生日是5月3日" in prompt
    assert "以这里为准" in prompt
    assert "不要主动提起" in prompt


async def test_a_profile_with_no_birthday_says_nothing_of_one(make_client: ClientFactory):
    llm = FakeLLM(REPLY)
    client = make_client(llm, clock=clock)

    prompt = await system_prompt(client, llm)

    assert "制作人的生日" not in prompt


async def test_the_special_mode_is_read_and_changed_on_its_own(make_client: ClientFactory):
    client = make_client(FakeLLM())

    assert (await client.get("/api/profile")).json()["special_mode"] == ""

    res = await client.put("/api/profile", json={"special_mode": "special"})
    assert res.status_code == 200
    assert (await client.get("/api/profile")).json()["special_mode"] == "special"

    # 只改别的字段：没带 special_mode，模式保持不变。
    await client.put("/api/profile", json={"form_of_address": "小林", "gender": "female"})
    profile = (await client.get("/api/profile")).json()
    assert profile["form_of_address"] == "小林"
    assert profile["special_mode"] == "special"

    # 只改模式：别的字段也保持不变。
    await client.put("/api/profile", json={"special_mode": "stern"})
    profile = (await client.get("/api/profile")).json()
    assert profile["form_of_address"] == "小林"
    assert profile["gender"] == "female"
    assert profile["special_mode"] == "stern"

    await client.put("/api/profile", json={"special_mode": ""})
    assert (await client.get("/api/profile")).json()["special_mode"] == ""


def test_a_profile_table_from_before_modes_gains_the_column(tmp_path: Path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as db:
        db.executescript(
            """
            CREATE TABLE users (id TEXT PRIMARY KEY, created_at TEXT NOT NULL);
            CREATE TABLE producer_profiles (
                user_id TEXT PRIMARY KEY REFERENCES users(id),
                form_of_address TEXT,
                gender TEXT,
                timezone TEXT,
                updated_at TEXT NOT NULL,
                birthday_month INTEGER,
                birthday_day INTEGER
            );
            INSERT INTO users (id, created_at) VALUES ('u1', '2026-01-01T00:00:00+00:00');
            INSERT INTO producer_profiles
                (user_id, form_of_address, updated_at)
                VALUES ('u1', '小林', '2026-01-01T00:00:00+00:00');
            """
        )

    store = Store(path)
    try:
        profile = store.get_profile("u1")
    finally:
        store.close()

    assert profile.form_of_address == "小林"
    assert profile.special_mode == ""
    with sqlite3.connect(path) as db:
        column = {
            row[1]: row for row in db.execute("PRAGMA table_info(producer_profiles)")
        }["special_mode"]
    assert (column[2], column[3], column[4]) == ("TEXT", 1, "''")


async def test_prompt_tells_the_current_time_in_the_devices_timezone(
    make_client: ClientFactory,
):
    llm = FakeLLM(REPLY)
    client = make_client(llm, clock=clock)
    client.headers["X-Timezone"] = "Asia/Tokyo"

    prompt = await system_prompt(client, llm)

    assert "2026年9月25日" in prompt
    assert "星期五" in prompt
    assert "21:30" in prompt
    assert "Asia/Tokyo" in prompt


async def test_a_timezone_set_in_the_profile_overrides_the_device(make_client: ClientFactory):
    llm = FakeLLM(REPLY)
    client = make_client(llm, clock=clock)
    client.headers["X-Timezone"] = "Asia/Tokyo"
    await client.put("/api/profile", json={"timezone": "America/Los_Angeles"})

    prompt = await system_prompt(client, llm)

    assert "2026年9月25日" in prompt
    assert "05:30" in prompt
    assert "America/Los_Angeles" in prompt


@pytest.mark.parametrize(
    "header", [None, "Not/A_Zone", "America"], ids=["missing", "unknown", "region"]
)
async def test_without_a_usable_timezone_the_time_is_given_in_shanghai(
    make_client: ClientFactory, header: str | None
):
    llm = FakeLLM(REPLY)
    client = make_client(llm, clock=clock)
    if header is not None:
        client.headers["X-Timezone"] = header

    prompt = await system_prompt(client, llm)

    assert "20:30" in prompt
    assert "Asia/Shanghai" in prompt


async def test_a_saved_timezone_no_longer_known_falls_back_instead_of_failing(
    make_client: ClientFactory, settings: Settings
):
    llm = FakeLLM(REPLY)
    client = make_client(llm, clock=clock)
    client.headers["X-Timezone"] = "Asia/Tokyo"
    await client.put("/api/profile", json={"timezone": "Asia/Tokyo"})
    with sqlite3.connect(settings.database_path) as db:  # as if tzdata dropped the zone
        db.execute("UPDATE producer_profiles SET timezone = 'Gone/Away'")

    prompt = await system_prompt(client, llm)

    assert "21:30" in prompt and "Asia/Tokyo" in prompt


async def test_a_profile_saved_before_birthdays_keeps_working(
    make_client: ClientFactory, settings: Settings
):
    old = {"form_of_address": "小林", "gender": "female", "timezone": "Asia/Tokyo"}
    await make_client(FakeLLM()).put("/api/profile", json=old)
    with sqlite3.connect(settings.database_path) as db:  # as the table was before birthdays
        db.execute("ALTER TABLE producer_profiles DROP COLUMN birthday_month")
        db.execute("ALTER TABLE producer_profiles DROP COLUMN birthday_day")

    upgraded = make_client(FakeLLM())

    assert (await upgraded.get("/api/profile")).json() == {
        **old, "birthday": None, "special_mode": "",
    }
    res = await upgraded.put("/api/profile", json={**old, "birthday": {"month": 5, "day": 3}})
    assert res.status_code == 200
    assert (await upgraded.get("/api/profile")).json()["birthday"] == {"month": 5, "day": 3}


ON_THE_DAY = "今天是制作人的生日"


@pytest.mark.parametrize(
    ("birthday", "on_the_day"),
    [
        ({"month": 9, "day": 25}, True),
        ({"month": 9, "day": 24}, False),
    ],
    ids=["the-day", "the-day-after"],
)
async def test_on_the_birthday_the_character_is_asked_to_wish_once(
    make_client: ClientFactory, birthday: dict, on_the_day: bool
):
    llm = FakeLLM(REPLY)
    client = make_client(llm, clock=clock)  # 2026-09-25 in Shanghai
    await client.put("/api/profile", json={"birthday": birthday})

    prompt = await system_prompt(client, llm)

    assert (ON_THE_DAY in prompt) is on_the_day
    if on_the_day:
        assert "祝福一次" in prompt
        assert "不要每句都提" in prompt


TOKYO_MIDNIGHT = datetime(2026, 5, 2, 15, 30, tzinfo=UTC)  # 05-03 00:30 in Tokyo


async def test_the_birthday_begins_at_midnight_where_the_producer_is(
    make_client: ClientFactory,
):
    llm = FakeLLM(REPLY)
    client = make_client(llm, clock=lambda: TOKYO_MIDNIGHT)  # still 05-02 in UTC
    client.headers["X-Timezone"] = "Asia/Tokyo"
    await client.put("/api/profile", json={"birthday": {"month": 5, "day": 3}})

    prompt = await system_prompt(client, llm)

    assert ON_THE_DAY in prompt


@pytest.mark.parametrize(
    ("today", "on_the_day"),
    [
        (datetime(2027, 2, 28, 4, tzinfo=UTC), True),
        (datetime(2028, 2, 28, 4, tzinfo=UTC), False),
    ],
    ids=["common-year-feb-28", "leap-year-feb-28"],
)
async def test_a_february_29_birthday_falls_on_february_28_in_common_years(
    make_client: ClientFactory, today: datetime, on_the_day: bool
):
    llm = FakeLLM(REPLY)
    client = make_client(llm, clock=lambda: today)
    await client.put("/api/profile", json={"birthday": {"month": 2, "day": 29}})

    prompt = await system_prompt(client, llm)

    assert (ON_THE_DAY in prompt) is on_the_day
