"""排期表（`schedules.py`、characters/schedules.model.md）：读真乃那份真数据、按顺序挑、跨零点。

真数据那几条用的是仓库里的 `characters/`（容器里它在 `/characters`）；其余用 tmp_path 里造的
一张小表，`chance` 写死成 1.0 / 0.0，好断言「只在这个条件下才发生」。日期和种子都写死，
不碰网络、不看今天几号。
"""

import collections
import os
import random
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from eidolon.schedules import (
    SLOTS,
    Choice,
    ScheduleCatalog,
    load_schedules,
    pick,
    slot_at,
    span_at,
    stable_pick,
    stable_seed,
)

SCHEDULE_NAME = "schedules.mano.week.draft.toml"


def characters_dir() -> Path:
    """仓库里的 characters/：源码树里是 `<repo>/characters`，容器里是 `/characters`。"""
    candidates = []
    if os.environ.get("EIDOLON_CHARACTERS_PATH"):
        candidates.append(Path(os.environ["EIDOLON_CHARACTERS_PATH"]).parent)
    for parent in Path(__file__).resolve().parents:
        candidates.append(parent / "characters")
    for candidate in candidates:
        if (candidate / SCHEDULE_NAME).is_file():
            return candidate
    raise AssertionError(f"找不到 {SCHEDULE_NAME}：{candidates}")


_REAL: ScheduleCatalog | None = None


def real_catalog() -> ScheduleCatalog:
    """真乃那份真数据，读一次就记着。"""
    global _REAL
    cached = _REAL
    if cached is None:
        loaded = load_schedules(characters_dir() / SCHEDULE_NAME)
        assert loaded is not None
        cached = _REAL = loaded
    return cached


# ---------------------------------------------------------------------------
# tmp_path 里造的一张小表
# ---------------------------------------------------------------------------

SCENES = """
[[scenes]]
id = "home"
name = "她的家"
hint = "粉色房间"
image = "home.jpg"

[[scenes]]
id = "studio"
name = "练习室"
hint = "镜子、把杆"
image = "studio.jpg"

[[scenes]]
id = "cafe"
name = "咖啡店"
hint = "小桌、窗边"
image = "cafe.jpg"

[[scenes]]
id = "river"
name = "河堤"
hint = "水面、桥"
image = "river.jpg"

[[scenes]]
id = "park"
name = "公园"
hint = "长椅、鸽子"
image = "park.jpg"

[[scenes]]
id = "shrine"
name = "神社"
hint = "鸟居"
image = "shrine.jpg"
"""

CALENDAR = """
[calendar]
timezone = "Asia/Tokyo"

[[holidays]]
id = "new_year"
name = "元旦"
name_ja = "元日"
kind = "public"
dates = ["2026-01-01"]
scenes = ["shrine"]
weights = [1]
activities = ["元旦去神社参拜。"]
"""

WEEK = """
[[slots]]
character = "mano"
day = "mon"
slot = "afternoon"
scene = "studio"
activity = "在练习室练舞"
weight = 3

[[slots]]
character = "mano"
day = "mon"
slot = "afternoon"
scene = "home"
activity = "在家写作业"
weight = 1

[[slots]]
character = "mano"
day = "mon"
slot = "night"
scene = "studio"
activity = "趁没人多练一会儿"
weight = 1

[[slots]]
character = "mano"
day = "sun"
slot = "night"
scene = "cafe"
activity = "在咖啡店坐到很晚"
weight = 1

[[pools]]
character = "mano"
day = "any"
slot = "any"
chance = __POOL_CHANCE__
scenes = ["cafe"]
weights = [1]
why = "偶尔不按作息走"

[[holidays]]
holiday = "new_year"
dates = ["2026-01-01"]
slots = ["morning"]
scenes = ["shrine"]
weights = [1]
priority = 100
activity = "元旦在神社"

[[events]]
character = "mano"
chance = 1.0
scene = "river"
activity = "在河堤上看烟花"
conditions = { season = "summer" }
why = "夏天的花火"

[[events]]
character = "mano"
chance = 1.0
scene = "park"
activity = "下雨了，躲进公园的长椅"
conditions = { weather = "rain" }
why = "下雨"
"""


def small_table(tmp_path: Path, pool_chance: float = 0.0) -> Path:
    """在 tmp_path 里造一份能读的最小排期：scenes.toml、holidays.toml 和一周。"""
    directory = tmp_path / "characters"
    directory.mkdir(parents=True)
    (directory / "scenes.toml").write_text(SCENES, encoding="utf-8")
    (directory / "holidays.toml").write_text(CALENDAR, encoding="utf-8")
    path = directory / SCHEDULE_NAME
    path.write_text(WEEK.replace("__POOL_CHANCE__", str(pool_chance)), encoding="utf-8")
    return path


def small(tmp_path: Path, pool_chance: float = 0.0) -> ScheduleCatalog:
    loaded = load_schedules(small_table(tmp_path, pool_chance))
    assert loaded is not None
    return loaded


def drawn(
    catalog: ScheduleCatalog, at: datetime, seeds: range, weather: str | None = None
) -> list[Choice]:
    """同一天、同一时刻，换种子各抽一次（每个种子算一通电话）；抽不到就是测试写错了。"""
    chosen: list[Choice] = []
    for seed in seeds:
        picked = pick(catalog, "mano", at, random.Random(seed), weather=weather)
        assert picked is not None, f"种子 {seed} 什么都没抽到"
        chosen.append(picked)
    return chosen


# 2026-04-06 是周一（春天），2026-07-06 是周一（夏天）。
SPRING_MONDAY = datetime(2026, 4, 6, 15, 0)
SUMMER_MONDAY = datetime(2026, 7, 6, 15, 0)
MONDAY_EARLY = datetime(2026, 4, 6, 0, 30)  # 其实是 2026-04-05（周日）的 night
MONDAY_LATE = datetime(2026, 4, 6, 23, 0)


# ---------------------------------------------------------------------------
# 真数据
# ---------------------------------------------------------------------------


def test_the_real_schedule_has_what_the_model_documents() -> None:
    """真乃那份：65 个槽位、2 个池子、32 个节日覆盖、17 条事件，日历 32 条。"""
    catalog = real_catalog()

    assert catalog.timezone == "Asia/Tokyo"
    assert len(catalog.slots) == 65
    assert len(catalog.pools) == 2
    assert len(catalog.holidays) == 32
    assert len(catalog.events) == 17
    assert len(catalog.calendar) == 32

    # 每个节日覆盖都指着日历里有的日子；优先级从大到小排好
    for holiday in catalog.holidays:
        assert catalog.calendar[holiday.holiday].days
    priorities = [holiday.priority for holiday in catalog.holidays]
    assert priorities == sorted(priorities, reverse=True)

    # 2026-10 调过的三个数：池子 chance 0.18、GW 优先级 65
    assert {pool.chance for pool in catalog.pools} == {0.18}
    golden_week = next(h for h in catalog.holidays if h.holiday == "golden_week")
    assert golden_week.priority == 65
    assert golden_week.chance == 0.4

    # 三个无条件事件压小之后的 chance
    unconditional = {
        event.scenes[0]: event.chance for event in catalog.events if not event.conditions
    }
    assert unconditional["studio"] == 0.055
    assert unconditional["lounge"] == 0.045
    assert unconditional["train"] == 0.03


def test_new_year_takes_her_to_the_shrine() -> None:
    """元旦上午：节日覆盖先吃掉（优先级 100），神社 3 : 家里客厅 2。"""
    catalog = real_catalog()
    at = datetime(2026, 1, 1, 9, 0)

    picks = drawn(catalog, at, range(200))
    assert all(chosen.source == "holiday" for chosen in picks)
    assert {chosen.scene_id for chosen in picks} == {"shrine", "home_living"}
    counts = collections.Counter(chosen.scene_id for chosen in picks)
    assert counts["shrine"] > counts["home_living"]
    assert "元日" in picks[0].why


def test_tanabata_takes_her_to_the_shop_street() -> None:
    """七夕晚上：商店街 3 : 花园 2 : 夜晚的公园 2，19 点落在 evening。"""
    catalog = real_catalog()
    at = datetime(2026, 7, 7, 19, 0)

    picks = drawn(catalog, at, range(200))
    assert all(chosen.source == "holiday" for chosen in picks)
    assert {chosen.scene_id for chosen in picks} == {"shopstreet", "garden", "park_night"}
    counts = collections.Counter(chosen.scene_id for chosen in picks)
    assert counts["shopstreet"] > counts["garden"] > counts["park_night"]
    assert "七夕" in picks[0].why


def test_christmas_eve_is_its_own_holiday() -> None:
    """平安夜 20 点：夜晚的街道 3 : 家庭餐厅 2 : 家里客厅 2，压过普通周三的槽位。"""
    catalog = real_catalog()
    at = datetime(2026, 12, 24, 20, 0)

    picks = drawn(catalog, at, range(40))
    assert all(chosen.source == "holiday" for chosen in picks)
    assert {chosen.scene_id for chosen in picks} == {"street_night", "restaurant", "home_living"}
    assert "クリスマスイブ" in picks[0].why or "平安夜" in picks[0].why


def test_night_belongs_to_the_day_it_started(tmp_path: Path) -> None:
    """night 跨零点：0:00-2:00 算前一天的 night，2:00-6:00 不在任何一段里。"""
    assert slot_at(datetime(2025, 12, 31, 22, 0)) == (date(2025, 12, 31), "night")
    assert slot_at(datetime(2026, 1, 1, 0, 0)) == (date(2025, 12, 31), "night")
    assert slot_at(datetime(2026, 1, 1, 1, 59)) == (date(2025, 12, 31), "night")
    assert slot_at(datetime(2026, 1, 1, 2, 0)) is None
    assert slot_at(datetime(2026, 1, 1, 5, 59)) is None
    assert slot_at(datetime(2026, 1, 1, 6, 0)) == (date(2026, 1, 1), "morning")
    assert slot_at(datetime(2026, 1, 1, 13, 59)) == (date(2026, 1, 1), "noon")
    assert slot_at(datetime(2026, 1, 1, 17, 59)) == (date(2026, 1, 1), "afternoon")
    assert slot_at(datetime(2026, 1, 1, 21, 59)) == (date(2026, 1, 1), "evening")
    assert slot_at(datetime(2026, 1, 1, 22, 0)) == (date(2026, 1, 1), "night")

    # 造的那张小表：周日 night 在咖啡店，周一 night 在练习室。周一 00:30 走的是周日那格。
    catalog = small(tmp_path)
    early = pick(catalog, "mano", MONDAY_EARLY, random.Random(0))
    late = pick(catalog, "mano", MONDAY_LATE, random.Random(0))
    assert early is not None and (early.scene_id, early.source) == ("cafe", "slot")
    assert late is not None and (late.scene_id, late.source) == ("studio", "slot")


def test_a_real_night_call_uses_the_previous_days_slots() -> None:
    """2026-01-08 00:30 是 1 月 7 日（周三）的 night——周三夜里只有家；周四夜里是厨房/便利店。"""
    catalog = real_catalog()
    picks = drawn(catalog, datetime(2026, 1, 8, 0, 30), range(60))

    scenes = {chosen.scene_id for chosen in picks}
    assert "kitchen" not in scenes
    assert "convenience_store" not in scenes
    assert "home" in scenes


def test_span_at_says_when_the_slot_ends() -> None:
    """`now` 的 `until`：白天到这一格的整点，night 到次日 2 点，2-6 点的空白到 6 点。"""
    tokyo = ZoneInfo("Asia/Tokyo")
    morning = span_at(datetime(2026, 4, 6, 7, 0, tzinfo=tokyo))
    assert (morning.day, morning.slot) == (date(2026, 4, 6), "morning")
    assert morning.until == datetime(2026, 4, 6, 10, 0, tzinfo=tokyo)

    evening = span_at(datetime(2026, 4, 6, 21, 59, tzinfo=tokyo))
    assert (evening.day, evening.slot) == (date(2026, 4, 6), "evening")
    assert evening.until == datetime(2026, 4, 6, 22, 0, tzinfo=tokyo)

    night = span_at(datetime(2026, 4, 6, 23, 0, tzinfo=tokyo))
    assert (night.day, night.slot) == (date(2026, 4, 6), "night")
    assert night.until == datetime(2026, 4, 7, 2, 0, tzinfo=tokyo)

    # 跨零点：4 月 6 日 00:30 是 4 月 5 日的 night，到 4 月 6 日 02:00；接着 02:00-06:00 是空白。
    early = span_at(datetime(2026, 4, 6, 0, 30, tzinfo=tokyo))
    assert (early.day, early.slot) == (date(2026, 4, 5), "night")
    assert early.until == datetime(2026, 4, 6, 2, 0, tzinfo=tokyo)

    gap = span_at(datetime(2026, 4, 6, 3, 0, tzinfo=tokyo))
    assert (gap.day, gap.slot) == (date(2026, 4, 6), None)
    assert gap.until == datetime(2026, 4, 6, 6, 0, tzinfo=tokyo)


def test_the_same_slot_gets_the_same_scene_whatever_the_time_in_it(tmp_path: Path) -> None:
    """`stable_pick` 的种子按（角色、日期、时段）：同一格 14:00 和 17:59 是同一张；
    换一天、换一格种子不同（不保证场景一定不同，只保证种子不是同一个）。"""
    catalog = small(tmp_path)
    tokyo = ZoneInfo("Asia/Tokyo")
    start = datetime(2026, 4, 6, 14, 0, tzinfo=tokyo)

    first = stable_pick(catalog, "mano", start)
    later = stable_pick(catalog, "mano", start.replace(hour=17, minute=59))
    assert first is not None and later is not None
    assert (first.scene_id, first.source) == (later.scene_id, later.source)
    assert stable_seed("mano", date(2026, 4, 6), "afternoon") == stable_seed(
        "mano", date(2026, 4, 6), "afternoon"
    )
    assert len(
        {
            stable_seed("mano", date(2026, 4, 6), "afternoon"),
            stable_seed("mano", date(2026, 4, 7), "afternoon"),
            stable_seed("mano", date(2026, 4, 6), "evening"),
            stable_seed("kogane", date(2026, 4, 6), "afternoon"),
        }
    ) == 4

    # 2:00-6:00 没有格子：交给调用方回落 `[[behaviors]]`。
    assert stable_pick(catalog, "mano", start.replace(hour=3)) is None


def test_new_years_night_belongs_to_new_years_eve() -> None:
    """2026-01-01 00:30 是 2025-12-31 的 night：大晦日覆盖（神社 3 : 寺庙 2 : 客厅 2）。"""
    catalog = real_catalog()
    picks = drawn(catalog, datetime(2026, 1, 1, 0, 30), range(40))

    assert all(chosen.source == "holiday" for chosen in picks)
    assert {chosen.scene_id for chosen in picks} == {"temple", "shrine", "home_living"}
    assert "大晦日" in picks[0].why


# ---------------------------------------------------------------------------
# 造的小表：事件、加权槽位、池子、坏数据
# ---------------------------------------------------------------------------


def test_an_event_only_fires_inside_its_conditions(tmp_path: Path) -> None:
    """事件的条件全中才 roll：夏天才有花火，雨天才有公园，春天晴天两条都不中。"""
    catalog = small(tmp_path)

    summer = pick(catalog, "mano", SUMMER_MONDAY, random.Random(0), weather="cloudy")
    assert summer is not None and (summer.scene_id, summer.source) == ("river", "event")
    assert summer.activity_text == "在河堤上看烟花"

    rainy = pick(catalog, "mano", SPRING_MONDAY, random.Random(0), weather="rain")
    assert rainy is not None and (rainy.scene_id, rainy.source) == ("park", "event")

    neither = pick(catalog, "mano", SPRING_MONDAY, random.Random(0), weather="cloudy")
    assert neither is not None and neither.source == "slot"


def test_a_weighted_slot_is_reproducible_and_follows_its_weights(tmp_path: Path) -> None:
    """同一个种子给出同一串结果；练习室 3 : 家 1 的权重也照 3:1 抽。"""
    catalog = small(tmp_path)

    def run(seed: int) -> list[str]:
        picker = random.Random(seed)
        chosen: list[str] = []
        for _ in range(40):
            picked = pick(catalog, "mano", SPRING_MONDAY, picker, weather="cloudy")
            assert picked is not None
            chosen.append(picked.scene_id)
        return chosen

    assert run(11) == run(11)
    counts = collections.Counter(run(11))
    assert set(counts) == {"studio", "home"}
    assert counts["studio"] > counts["home"] * 2

    first = pick(catalog, "mano", SPRING_MONDAY, random.Random(7), weather="cloudy")
    again = pick(catalog, "mano", SPRING_MONDAY, random.Random(7), weather="cloudy")
    assert first == again


def test_a_pool_with_no_chance_never_replaces_the_slot_and_a_certain_one_always_does(
    tmp_path: Path,
) -> None:
    """池子的 chance：0 一次都不中（还是槽位），1 每次都换成池子里的地点。"""
    never = small(tmp_path / "never", pool_chance=0.0)
    always = small(tmp_path / "always", pool_chance=1.0)

    for seed in range(30):
        kept = pick(never, "mano", SPRING_MONDAY, random.Random(seed), weather="cloudy")
        assert kept is not None and kept.source == "slot"
        assert kept.scene_id in {"studio", "home"}

        replaced = pick(always, "mano", SPRING_MONDAY, random.Random(seed), weather="cloudy")
        assert replaced is not None and (replaced.scene_id, replaced.source) == ("cafe", "pool")


def test_a_schedule_may_only_name_scenes_in_the_table(tmp_path: Path) -> None:
    """排期表里写了场景表没有的 id：读的时候就说清楚是哪个文件、哪一条。"""
    path = small_table(tmp_path)
    broken = path.read_text(encoding="utf-8").replace('scene = "studio"', 'scene = "moon"', 1)
    path.write_text(broken, encoding="utf-8")

    with pytest.raises(RuntimeError, match="moon"):
        load_schedules(path)


def test_a_character_without_a_schedule_file_is_none(tmp_path: Path) -> None:
    """没有这份文件就是 None：调用方照旧走 [[behaviors]]。"""
    assert load_schedules(tmp_path / "characters" / SCHEDULE_NAME) is None


# ---------------------------------------------------------------------------
# 节日回落：排期表只写「和日历不一样」的几条，其余节日走 holidays.toml
# ---------------------------------------------------------------------------

CALENDAR_WITH_SPARES = """
[calendar]
timezone = "Asia/Tokyo"

[[holidays]]
id = "new_year"
name = "元旦"
name_ja = "元日"
kind = "public"
dates = ["2026-01-01"]
scenes = ["shrine"]
weights = [1]
activities = ["日历上的元旦：去神社参拜。"]

[[holidays]]
id = "golden_week"
name = "黄金周"
name_ja = "ゴールデンウィーク"
kind = "festival"
ranges = [{ from = "2026-04-29", to = "2026-05-06" }]
scenes = ["park"]
weights = [1]
activities = ["日历上的 GW：在公园躺着。"]

[[holidays]]
id = "tanabata"
name = "七夕"
name_ja = "七夕"
kind = "festival"
dates = ["2026-07-07"]
scenes = ["park", "cafe"]
weights = [3, 1]
activities = ["日历上的七夕：在公园看竹枝。"]

[[holidays]]
id = "christmas_eve"
name = "平安夜"
name_ja = "クリスマスイブ"
kind = "festival"
dates = ["2026-12-24"]
scenes = ["cafe"]
weights = [1]
activities = ["日历上的平安夜：在咖啡店坐到打烊。"]
"""

# 只写了元旦这一条差异：其余七个多月的节日都得靠回落。
DIFFERENCE_ONLY_WEEK = """
[[slots]]
character = "mano"
day = "thu"
slot = "morning"
scene = "studio"
activity = "在练习室练舞"
weight = 1

[[slots]]
character = "mano"
day = "tue"
slot = "evening"
scene = "home"
activity = "在家写作业"
weight = 1

[[slots]]
character = "mano"
day = "thu"
slot = "evening"
scene = "home"
activity = "在家吃晚饭"
weight = 1

[[holidays]]
holiday = "new_year"
dates = ["2026-01-01"]
slots = ["morning"]
scenes = ["home"]
weights = [1]
priority = 100
activity = "她写的元旦：在家睡到中午"
why = "她自己写的"
"""


def difference_only(tmp_path: Path) -> ScheduleCatalog:
    """一张只写了差异项的排期：日历四条，她只写元旦。"""
    directory = tmp_path / "characters"
    directory.mkdir(parents=True)
    (directory / "scenes.toml").write_text(SCENES, encoding="utf-8")
    (directory / "holidays.toml").write_text(CALENDAR_WITH_SPARES, encoding="utf-8")
    path = directory / SCHEDULE_NAME
    path.write_text(DIFFERENCE_ONLY_WEEK, encoding="utf-8")
    loaded = load_schedules(path)
    assert loaded is not None
    return loaded


def test_only_the_differences_written_still_leaves_every_holiday_reachable(tmp_path: Path) -> None:
    """她只写元旦一条，日历上其余的节日都被回落补上：四条一条不少，优先级按 model.md。"""
    catalog = difference_only(tmp_path)

    assert {holiday.holiday for holiday in catalog.holidays} == {
        "new_year",
        "golden_week",
        "tanabata",
        "christmas_eve",
    }
    by_id = {holiday.holiday: holiday for holiday in catalog.holidays}

    # 她自己写的那条：scenes/activity/priority/why 全是她的
    own = by_id["new_year"]
    assert own.scenes == ("home",) and own.priority == 100
    assert own.why == "她自己写的"
    assert own.slots == frozenset({"morning"})

    # 回落的三条：场景/权重/活动来自日历，why 标「回落」，优先级/时段/chance 按 model.md
    assert by_id["tanabata"].scenes == ("park", "cafe")
    assert by_id["tanabata"].weights == (3.0, 1.0)
    assert by_id["tanabata"].activity_text == ""
    assert by_id["tanabata"].priority == 60
    assert by_id["tanabata"].slots == frozenset({"evening", "night"})
    assert by_id["tanabata"].chance == 1.0
    assert by_id["tanabata"].why.startswith("回落")
    assert "七夕" in by_id["tanabata"].why

    assert by_id["christmas_eve"].priority == 80
    assert by_id["christmas_eve"].slots == frozenset({"evening", "night"})
    assert "回落" in by_id["christmas_eve"].why

    # 窗口型节日：白天三段 + chance 0.4（model.md：只有窗口型节日设 chance）
    assert by_id["golden_week"].priority == 65
    assert by_id["golden_week"].slots == frozenset({"morning", "noon", "afternoon"})
    assert by_id["golden_week"].chance == 0.4

    # 优先级从大到小，平手时她写的在前
    priorities = [holiday.priority for holiday in catalog.holidays]
    assert priorities == sorted(priorities, reverse=True)


def test_new_year_uses_her_own_entry_and_the_others_fall_back(tmp_path: Path) -> None:
    """元旦上午走她写的（家），七夕/平安夜走日历的场景和默认活动。"""
    catalog = difference_only(tmp_path)

    new_year = pick(catalog, "mano", datetime(2026, 1, 1, 9, 0), random.Random(0))
    assert new_year is not None
    assert (new_year.scene_id, new_year.source) == ("home", "holiday")
    assert new_year.activity_text == "她写的元旦：在家睡到中午"
    assert "回落" not in new_year.why

    tanabata = drawn(catalog, datetime(2026, 7, 7, 19, 0), range(120))
    assert all(chosen.source == "holiday" for chosen in tanabata)
    assert {chosen.scene_id for chosen in tanabata} == {"park", "cafe"}
    assert tanabata[0].activity_text == "日历上的七夕：在公园看竹枝。"
    assert "回落" in tanabata[0].why and "七夕" in tanabata[0].why
    counts = collections.Counter(chosen.scene_id for chosen in tanabata)
    assert counts["park"] > counts["cafe"]  # 3 : 1

    eve = pick(catalog, "mano", datetime(2026, 12, 24, 20, 0), random.Random(3))
    assert eve is not None
    assert (eve.scene_id, eve.source) == ("cafe", "holiday")
    assert eve.activity_text == "日历上的平安夜：在咖啡店坐到打烊。"
    assert "回落" in eve.why


def test_a_holiday_her_table_writes_is_never_fallen_back_to(tmp_path: Path) -> None:
    """写了的节日不会再补一条回落：元旦只有她自己那一条（否则会多出一条优先级 100 的重复）。"""
    catalog = difference_only(tmp_path)

    new_years = [holiday for holiday in catalog.holidays if holiday.holiday == "new_year"]
    assert len(new_years) == 1
    assert new_years[0].why == "她自己写的"


# ---------------------------------------------------------------------------
# pilot 批：四份只写差异项的周表（hiori / toru / juri / kaho）
# ---------------------------------------------------------------------------

PILOT = ("hiori", "toru", "juri", "kaho")


@pytest.mark.parametrize("character", PILOT)
def test_a_pilot_week_draft_loads_and_its_holidays_are_filled(character: str) -> None:
    """四份 pilot 草案：能读、场景全合法、7x5 槽位齐、每格 1-2 条、节日一条不落（含回落）。"""
    path = characters_dir() / "schedules" / f"{character}.week.draft.toml"
    if not path.is_file():
        pytest.skip(f"没有 {path.name}")
    loaded = load_schedules(path)
    assert loaded is not None

    by_cell = collections.Counter((slot.day, slot.slot) for slot in loaded.slots)
    assert len(by_cell) == 35, "7 天 x 5 时段"
    assert set(by_cell.values()) <= {1, 2}
    assert len(loaded.slots) == 65

    # 每个节日都有条目：她写的 + 回落，合起来正好覆盖日历（32 条），不多不少
    covered = {holiday.holiday for holiday in loaded.holidays}
    assert covered == set(loaded.calendar)
    assert len(loaded.holidays) == len(covered)

    # 至少有一条是回落（这四份都只写了 11-13 条差异），且都标了「回落」
    fallen = [holiday for holiday in loaded.holidays if holiday.why.startswith("回落")]
    assert fallen, f"{character} 应该有几条回落"
    for holiday in fallen:
        calendar = loaded.calendar[holiday.holiday]
        assert holiday.scenes == calendar.scenes
        assert holiday.weights == calendar.weights
        assert holiday.activity_text == ""  # 用日历的 activities[0]
        assert holiday.slots and holiday.slots <= set(SLOTS)

    # 被回落的节日真的能接出场景来（元旦白天 + 七夕晚上 + 平安夜晚上）
    for at in (
        datetime(2026, 1, 1, 9, 0),
        datetime(2026, 7, 7, 19, 0),
        datetime(2026, 12, 24, 20, 0),
    ):
        chosen = pick(loaded, character, at, random.Random(0))
        assert chosen is not None
        assert chosen.source == "holiday", (character, at, chosen.source)
