"""按时段挑通话场景（DESIGN.md「通话场景」、characters/schedules.model.md）。

`scenes.py` 的冷启动是「随机一条预设行为」，和日历、星期、几点没有关系；这里接的是真乃那份
排期：`characters/schedules.<角色>.week*.toml`（一周的固定槽位 + 随机池 + 节日覆盖 + 突发事件）
加上日历本体 `characters/holidays.toml`。一次通话按下面的顺序挑，前一步命中就不再看后面的：

1. **节日覆盖**：日期落在 `[[holidays]]` 的节日里、当前时段也在它的 `slots` 里就按 `priority`
   从大到小过（平手按文件顺序），每条过自己的 `chance`（默认 1.0），命中就按 `scenes`/`weights`
   加权抽一个。日期以 `holidays.toml` 为准——排期文件里的 `dates`/`ranges` 只是镜像。
   **排期表只写「这个人和日历不一样」的那几条**：她写了的节日按她的（`priority`/`slots`/`chance`/
   `scenes`/`activity` 全用她的），**没写的节日回落到 `holidays.toml` 里同名条目的 `scenes`/
   `weights` + 第一条 `activities`**，`why` 里标「回落」。回落要的三样东西日历没有（它只给日期和
   气氛），这里按 schedules.model.md 定死：
   - `priority`：100 元日 / 95 初詣 / 90 公休 / 85 振替・国民の休日 / 80 大晦日・クリスマス /
     70 花見・お盆・夏祭り / 65 GW / 60 七夕・紅葉狩り・ハロウィン / 55 節分・ひな祭り・バレンタイン
     （`HOLIDAY_PRIORITY`，表里没有的公休按 `kind` 给 90、振替・国民の休日给 85）。
   - `chance`：只有窗口型节日（花見/お盆/夏祭り/紅葉狩り/GW）有，表示「这天真的去了」；
     取值 `HOLIDAY_WINDOW_CHANCE`（和真乃那份逐条写的一致），其余 1.0。
   - `slots`：公休/扫墓/花见/远足/GW 占白天三段；祭典（七夕・夏祭り・ハロウィン・平安夜・大晦日）
     和節分占晚上；情人节早上+晚上；雏祭中午+晚上；圣诞中午+晚上+深夜（`HOLIDAY_SLOTS`）。
2. **事件**：按文件顺序逐条看 `conditions`，全部命中才 roll `chance`，第一次成功即采用。
3. **固定槽位**：星期几 + 时段找到候选，按 `weight` 加权抽一个。
4. **随机池**：roll 一次 `chance` 决定「这一天要不要不按作息走」，命中就用池子里的地点**替换**
   第 3 步的结果；`slot` 更具体的池子优先（夜里的 `night` 池压过 `any` 池）。

时段与文档一致：morning 6-10、noon 10-14、afternoon 14-18、evening 18-22、night 22-2。
night 跨零点，**日期取这一段开始的那天**：1 月 1 日 00:30 的电话走的是 12-31 的 night，不是
元旦的白天。2:00-6:00 不在这五段里（文档里的 night 到 2 点为止），`pick` 返回 None，调用方照旧
走 `[[behaviors]]`。

时区一律 Asia/Tokyo（`[calendar].timezone`）：拿到的 `at` 带时区就先换过去，不带就当她那边的时间。

这个模块只读文件、只算，不碰网络、不碰数据库。
"""

from __future__ import annotations

import hashlib
import random
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from eidolon.scenes import Catalog, load_scenes

SLOTS = ("morning", "noon", "afternoon", "evening", "night")
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
WEATHERS = ("clear", "cloudy", "rain", "snow")
CONDITIONS = ("season", "weather", "holiday", "weekday", "slot")
SEASONS = {
    1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring", 6: "summer",
    7: "summer", 8: "summer", 9: "autumn", 10: "autumn", 11: "autumn", 12: "winter",
}
NIGHT_START = 22
"""night 从 22 点起，跨过零点到 2 点。"""

# ---------------------------------------------------------------------------
# 节日回落用的三张表：她的 `[[holidays]]` 没写这条节日时，按日历本体 + 这三张表补一条。
# 数值取自 schedules.model.md 的优先级表和真乃那份排期（model.md 只规定「窗口型节日要有
# chance」，没给数；这里和真乃逐条写的值一致）。
# ---------------------------------------------------------------------------

HOLIDAY_PRIORITY: dict[str, int] = {
    "new_year": 100,
    "hatsumode": 95,
    "substitute_holiday": 85,
    "citizens_holiday": 85,
    "omisoka": 80,
    "christmas_eve": 80,
    "christmas": 80,
    "hanami": 70,
    "obon": 70,
    "natsumatsuri": 70,
    "golden_week": 65,
    "tanabata": 60,
    "momijigari": 60,
    "halloween": 60,
    "setsubun": 55,
    "hinamatsuri": 55,
    "valentine": 55,
}
"""schedules.model.md 的节日优先级：100 元日 / 95 初詣 / 90 公休 / 85 振替・国民の休日 /
80 大晦日・クリスマス / 70 花見・お盆・夏祭り / 65 GW / 60 七夕・紅葉狩り・ハロウィン /
55 節分・ひな祭り・バレンタイン。表にないものは `_priority_of` が `kind` で決める。"""

PUBLIC_PRIORITY = 90
SUBSTITUTE_PRIORITY = 85
"""公休 / 振替休日・国民の休日 的优先级（表里没写的新节日按 kind 落到这两档）。"""

HOLIDAY_WINDOW_CHANCE: dict[str, float] = {
    "hanami": 0.45,
    "golden_week": 0.4,
    "natsumatsuri": 0.3,
    "obon": 0.8,
    "momijigari": 0.4,
}
"""窗口型节日的 `chance`（model.md：只有花見/お盆/夏祭り/紅葉狩り/GW 设，表示「这天真的去了」）。
其余节日不写就是 1.0。"""

HOLIDAY_DAY_SLOTS = ("morning", "noon", "afternoon")
"""白天型的节日占哪几段：公休、扫墓、花见、远足、GW。"""

HOLIDAY_SLOTS: dict[str, tuple[str, ...]] = {
    "hatsumode": ("morning", "noon"),
    "coming_of_age": ("morning", "noon"),
    "setsubun": ("evening", "night"),
    "tanabata": ("evening", "night"),
    "natsumatsuri": ("evening", "night"),
    "halloween": ("evening", "night"),
    "christmas_eve": ("evening", "night"),
    "omisoka": ("evening", "night"),
    "valentine": ("morning", "evening"),
    "hinamatsuri": ("noon", "evening"),
    "christmas": ("noon", "evening", "night"),
}
"""节日占用一天的哪几段（表里没有的就是白天三段）。祭典/圣诞/除夕占晚上，情人节早上+晚上，
雏祭中午+晚上——和真乃那份逐条写的 `slots` 一致。"""


@dataclass(frozen=True)
class Choice:
    """接通时挑中的那一格：哪个场景、她这会儿在做什么、是哪一步定下来的。"""

    scene_id: str
    activity_text: str
    """这一格她在做什么，进开场白的提示词；随机池没写活动时是空的。"""
    source: str
    """`holiday` / `event` / `slot` / `pool`：是哪一步挑中她的。"""
    why: str
    """这一格的出处说明（数据里的 `why`，节日给节日名），给人看。"""


@dataclass(frozen=True)
class Span:
    """某一刻落在哪一格：算哪一天、哪个时段，这一格到几点结束。

    `slot` 是 None 表示 2:00-6:00 那段空白——没有格子，`until` 是当天 6:00（下一格开始）。
    night 的 `day` 是这一段开始的那天（和 `slot_at` 一样）。
    """

    day: date
    slot: str | None
    until: datetime


@dataclass(frozen=True)
class CalendarHoliday:
    """`holidays.toml` 的一条：哪天是什么日子、这天适合去哪、她会说什么。"""

    id: str
    name: str
    name_ja: str
    kind: str
    days: frozenset[date]
    scenes: tuple[str, ...]
    weights: tuple[float, ...]
    activities: tuple[str, ...]
    note: str


@dataclass(frozen=True)
class Slot:
    """`[[slots]]`：星期几的这一个时段她通常在哪。"""

    character: str
    day: str
    slot: str
    weight: float
    """同一格里的相对权重，不是概率。"""
    scenes: tuple[str, ...]
    weights: tuple[float, ...]
    activity_text: str
    why: str


@dataclass(frozen=True)
class Pool:
    """`[[pools]]`：不按作息走时可能去的日常地点。"""

    character: str
    day: str
    slot: str
    chance: float
    scenes: tuple[str, ...]
    weights: tuple[float, ...]
    activity_text: str
    why: str


@dataclass(frozen=True)
class Event:
    """`[[events]]`：条件命中才 roll 的突发事件。"""

    character: str
    chance: float
    scenes: tuple[str, ...]
    weights: tuple[float, ...]
    activity_text: str
    why: str
    conditions: Mapping[str, frozenset[str]]
    """键是 season/weather/holiday/weekday/slot，值是「命中任一即可」的集合。"""


@dataclass(frozen=True)
class Holiday:
    """`[[holidays]]`：节日覆盖。日期以 `holidays.toml` 为准，这里只留选法。

    可能是文件里写的（她用 `scenes`/`slots`/`chance`/`activity` 覆盖日历），也可能是
    `_fallback_holiday` 按日历本体补的那条（`activity_text` 空，`why` 以「回落：」开头）。
    """

    character: str
    holiday: str
    slots: frozenset[str]
    chance: float
    priority: int
    scenes: tuple[str, ...]
    weights: tuple[float, ...]
    activity_text: str
    why: str


@dataclass(frozen=True)
class ScheduleCatalog:
    """一位角色的排期表，加上日历本体。"""

    timezone: str
    slots: tuple[Slot, ...]
    pools: tuple[Pool, ...]
    holidays: tuple[Holiday, ...]
    """她写的 `[[holidays]]` + 没写的节日按日历补的回落条目，已按 `priority` 从大到小排好
    （平手时她写的排在回落前面，同组内保持文件顺序）。"""
    events: tuple[Event, ...]
    """文件顺序就是优先级。"""
    calendar: Mapping[str, CalendarHoliday]

    def calendar_holiday(self, holiday_id: str) -> CalendarHoliday | None:
        return self.calendar.get(holiday_id)


def load_schedules(
    path: Path,
    *,
    catalog: Catalog | None = None,
    calendar_path: Path | None = None,
) -> ScheduleCatalog | None:
    """读一份排期表（外加同目录的 `holidays.toml`）；文件不在就是 None。

    `catalog` 是已经读好的场景表（省一次解析，也让调用方只读一次 `scenes.toml`）；
    不给就从 `path` 往上找 `scenes.toml`（排期表平铺在 `characters/` 或放在
    `characters/schedules/` 都行）。`calendar_path` 不给就是往上找到的 `holidays.toml`。

    `[[holidays]]` 是「和日历不一样」的那几条：这里会把日历里剩下没写的节日按
    `_fallback_holiday` 补成回落条目，所以 `ScheduleCatalog.holidays` 覆盖 `holidays.toml`
    的全部 32 条——写全了的一份（真乃）补 0 条。

    `[[slots]]`/`[[pools]]`/`[[holidays]]`/`[[events]]` 里用到不存在的场景 id、星期/时段写错、
    `scenes` 和 `weights` 不等长、节日指向 `holidays.toml` 里没有的 id——都抛 RuntimeError，
    消息里带上是哪个文件、哪一条、错在哪。
    """
    if not path.is_file():
        return None
    data = _toml(path)
    if catalog is None:
        catalog = load_scenes(_nearby(path.parent, "scenes.toml"))
    known = {scene.id for scene in catalog.scenes}

    calendar_file = calendar_path or _nearby(path.parent, "holidays.toml")
    if not calendar_file.is_file():
        raise RuntimeError(f"缺少日历表 {calendar_file}（排期表 {path} 要用它）")
    calendar_data = _toml(calendar_file)
    timezone = str(calendar_data.get("calendar", {}).get("timezone") or "Asia/Tokyo")
    calendar = _calendar(calendar_file, calendar_data, known)

    slots = tuple(
        _slot(path, index, entry, known) for index, entry in enumerate(data.get("slots", []))
    )
    pools = tuple(
        _pool(path, index, entry, known) for index, entry in enumerate(data.get("pools", []))
    )
    written = [
        _holiday(path, index, entry, calendar, known)
        for index, entry in enumerate(data.get("holidays", []))
    ]
    covered = {holiday.holiday for holiday in written}
    # 日历里有、她没写的节日：用 holidays.toml 的场景和默认活动顶上——否则「她只写差异项」
    # 就等于「其余节日一律不过」。
    fallbacks = [
        _fallback_holiday(entry) for holiday_id, entry in calendar.items() if holiday_id not in covered
    ]
    # 她写的排在前面：同优先级时先过她的选择，再轮到回落的（model.md「平手取文件里靠前的」）。
    holidays = tuple(sorted([*written, *fallbacks], key=lambda holiday: -holiday.priority))
    events = tuple(
        _event(path, index, entry, known) for index, entry in enumerate(data.get("events", []))
    )
    return ScheduleCatalog(timezone, slots, pools, holidays, events, calendar)


def slot_at(at: datetime) -> tuple[date, str] | None:
    """这会儿在哪一格：返回（这一格算哪一天，时段名）；2:00-6:00 不在任何一段里，返回 None。

    night 跨零点：0:00-2:00 算**前一天**的 night。所以元旦 00:30 是 12-31 的 night
    （大晦日/初詣的深夜参拜），不是元旦的白天。
    """
    hour = at.hour
    if hour < 2:
        return (at.date() - timedelta(days=1), "night")
    if hour < 6:
        return None
    if hour < 10:
        return (at.date(), "morning")
    if hour < 14:
        return (at.date(), "noon")
    if hour < 18:
        return (at.date(), "afternoon")
    if hour < NIGHT_START:
        return (at.date(), "evening")
    return (at.date(), "night")


SLOT_ENDS = {"morning": 10, "noon": 14, "afternoon": 18, "evening": 22, "night": 2}
"""每一格到几点结束：night 是次日的 2 点，其余是当天的整点。"""

GAP_ENDS = 6
"""2:00-6:00 的空白到 6 点结束（morning 开始）。"""


def span_at(at: datetime, timezone: str = "Asia/Tokyo") -> Span:
    """这会儿在哪一格、这一格到几点：`at` 先换到 `timezone`，其余和 `slot_at` 一样。

    2:00-6:00 没有格子：`slot` 是 None，`until` 是当天 6:00。night 的 `until` 是次日 2 点，
    所以元旦 00:30 的 until 是元旦 02:00（这一格从 12-31 晚上开始）。
    """
    local = _local(at, timezone)
    span = slot_at(local)
    if span is None:
        day = local.date()
        return Span(day, None, _clock(day, GAP_ENDS, local.tzinfo))
    day, slot = span
    ends = day + timedelta(days=1) if slot == "night" else day
    return Span(day, slot, _clock(ends, SLOT_ENDS[slot], local.tzinfo))


def stable_seed(character: str, day: date, slot: str) -> int:
    """（角色、日期、时段）→ 固定种子：跨进程也稳定。

    不用 Python 的 `hash()`：它每个进程加盐，重启后同一格会换一张，页面会闪。
    """
    raw = f"{character}\0{day.isoformat()}\0{slot}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")


def stable_pick(
    catalog: ScheduleCatalog, character: str, at: datetime
) -> Choice | None:
    """和 `pick` 的顺序、天气默认值完全一样，但种子按（角色、日期、时段）固定。

    同一格反复打开页面看到的是同一张；通话用的 `pick` 仍然每通电话重掷，不经过这里。
    2:00-6:00 没有格子，返回 None，调用方回落 `[[behaviors]]`。
    """
    span = span_at(at, catalog.timezone)
    if span.slot is None:
        return None
    return pick(
        catalog,
        character,
        at,
        rng=random.Random(stable_seed(character, span.day, span.slot)),
    )


def pick(
    catalog: ScheduleCatalog,
    character: str,
    at: datetime,
    rng: random.Random | None = None,
    weather: str | None = None,
) -> Choice | None:
    """按 schedules.model.md 的顺序挑一格：节日 > 事件 > 固定槽位 > 随机池。

    `at` 是她那边的时刻（带时区会先换到 `catalog.timezone`）。`weather` 是调用方知道的
    天气（clear/cloudy/rain/snow），不知道就当 clear。`rng` 不给就用模块的 random——
    测试里给 `random.Random(种子)` 就能复现。

    没有能挑的（2:00-6:00 的空白，或者这个角色在这份表里没有槽位）就是 None，调用方回落
    `[[behaviors]]`。
    """
    local = _local(at, catalog.timezone)
    span = slot_at(local)
    if span is None:
        return None
    day, slot = span
    picker = rng if rng is not None else random.Random()
    chosen = _holiday_choice(catalog, character, day, slot, picker)
    if chosen is not None:
        return chosen
    weekend = day.weekday() >= 5
    chosen = _event_choice(catalog, character, day, slot, weekend, _weather(weather), picker)
    if chosen is not None:
        return chosen
    in_slot = _slot_choice(catalog, character, day, slot, picker)
    in_pool = _pool_choice(catalog, character, slot, picker)
    return in_pool or in_slot


def holidays_on(catalog: ScheduleCatalog, day: date) -> frozenset[str]:
    """这一天在 `holidays.toml` 里是什么日子：可能不止一个（公休 + 季节行事）。"""
    return frozenset(
        holiday.id for holiday in catalog.calendar.values() if day in holiday.days
    )


# ---------------------------------------------------------------------------
# 四步选法
# ---------------------------------------------------------------------------


def _holiday_choice(
    catalog: ScheduleCatalog, character: str, day: date, slot: str, picker: random.Random
) -> Choice | None:
    """第一步：节日覆盖。日期用日历本体的，`priority` 从大到小，窗口期节日 chance 没中就接着看下一条。"""
    for entry in catalog.holidays:
        if not _mine(entry.character, character):
            continue
        if slot not in entry.slots:
            continue
        calendar = catalog.calendar.get(entry.holiday)
        if calendar is None or day not in calendar.days:
            continue
        if entry.chance < 1.0 and picker.random() >= entry.chance:
            continue
        scene = _weighted(picker, entry.scenes, entry.weights)
        activity = entry.activity_text or (calendar.activities[0] if calendar.activities else "")
        why = entry.why or f"{calendar.name_ja or calendar.name}（{entry.holiday}）"
        return Choice(scene, activity, "holiday", why)
    return None


def _event_choice(
    catalog: ScheduleCatalog,
    character: str,
    day: date,
    slot: str,
    weekend: bool,
    weather: str,
    picker: random.Random,
) -> Choice | None:
    """第二步：突发事件，文件顺序就是优先级，全部条件命中才 roll。"""
    holidays = holidays_on(catalog, day)
    actual = {
        "season": frozenset({SEASONS[day.month]}),
        "weather": frozenset({weather}),
        "holiday": holidays,
        "weekday": frozenset({"weekend" if weekend else "weekday"}),
        "slot": frozenset({slot}),
    }
    for event in catalog.events:
        if not _mine(event.character, character):
            continue
        if not all(wanted & actual[key] for key, wanted in event.conditions.items()):
            continue
        if event.chance < 1.0 and picker.random() >= event.chance:
            continue
        scene = _weighted(picker, event.scenes, event.weights)
        return Choice(scene, event.activity_text, "event", event.why)
    return None


def _slot_choice(
    catalog: ScheduleCatalog, character: str, day: date, slot: str, picker: random.Random
) -> Choice | None:
    """第三步：星期几 + 时段的固定槽位，按 weight 加权。"""
    candidates = [
        entry
        for entry in catalog.slots
        if _mine(entry.character, character) and entry.day == DAYS[day.weekday()] and entry.slot == slot
    ]
    if not candidates:
        return None
    index = picker.choices(
        range(len(candidates)), weights=[entry.weight for entry in candidates], k=1
    )[0]
    entry = candidates[index]
    scene = _weighted(picker, entry.scenes, entry.weights)
    return Choice(scene, entry.activity_text, "slot", entry.why)


def _pool_choice(
    catalog: ScheduleCatalog, character: str, slot: str, picker: random.Random
) -> Choice | None:
    """第四步：随机池。slot 更具体的池子优先，只 roll 最具体的那一个（和 simulate.py 一致）。"""
    mine = [pool for pool in catalog.pools if _mine(pool.character, character)]
    pool = next((entry for entry in mine if entry.slot == slot), None) or next(
        (entry for entry in mine if entry.slot == "any"), None
    )
    if pool is None:
        return None
    if pool.chance < 1.0 and picker.random() >= pool.chance:
        return None
    scene = _weighted(picker, pool.scenes, pool.weights)
    return Choice(scene, pool.activity_text, "pool", pool.why)


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------


def _mine(owner: str, character: str) -> bool:
    """这一条是不是她的：她自己的，或者所有人共用的（`*`）。"""
    return owner in (character, "*")


def _weather(weather: str | None) -> str:
    """调用方没给天气时就当晴天（文档：默认 clear）。"""
    value = (weather or "clear").strip().lower()
    if value not in WEATHERS:
        raise ValueError(f"天气只有 {'/'.join(WEATHERS)}，给的是 {weather!r}")
    return value


def _local(at: datetime, timezone: str) -> datetime:
    """换到她那个时区；naive 的 `at` 就当她那边的时间，不动。"""
    if at.tzinfo is None:
        return at
    try:
        return at.astimezone(ZoneInfo(timezone))
    except (ZoneInfoNotFoundError, ValueError):
        return at


def _clock(day: date, hour: int, timezone: tzinfo | None) -> datetime:
    """那一天的整点（带上 `at` 原来的时区）。"""
    return datetime.combine(day, time(hour), tzinfo=timezone)


def _weighted(picker: random.Random, scenes: tuple[str, ...], weights: tuple[float, ...]) -> str:
    """按权重抽一个；只有一个就不动随机数（种子复现时少一次浪费）。"""
    if len(scenes) == 1:
        return scenes[0]
    return picker.choices(scenes, weights=list(weights), k=1)[0]


def _nearby(start: Path, name: str) -> Path:
    """从 `start` 往上找 `name`：排期表可能在 `characters/` 里，也可能在 `characters/schedules/` 里。"""
    for directory in (start, *start.parents):
        path = directory / name
        if path.is_file():
            return path
    raise RuntimeError(f"从 {start} 往上都找不到 {name}")


def _toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as e:
        raise RuntimeError(f"{path} 读不了：{e}") from e


def _places(where: str, entry: Mapping, known: set[str]) -> tuple[tuple[str, ...], tuple[float, ...]]:
    """`scene` 单候选简写，或者 `scenes` + `weights`；场景 id 必须在场景表里。"""
    if "scene" in entry:
        scenes, weights = [str(entry["scene"])], [1.0]
    else:
        scenes = [str(scene) for scene in entry.get("scenes", [])]
        weights = [float(weight) for weight in entry.get("weights", [1.0] * len(scenes))]
    if not scenes:
        raise RuntimeError(f"{where} 没有 scene 或 scenes")
    if len(scenes) != len(weights):
        raise RuntimeError(f"{where} 的 scenes/weights 不等长：{len(scenes)} vs {len(weights)}")
    for scene in scenes:
        if scene not in known:
            raise RuntimeError(f"{where} 用到了不存在的场景 {scene}")
    if any(weight <= 0 for weight in weights):
        raise RuntimeError(f"{where} 的 weight 要大于 0：{weights}")
    return tuple(scenes), tuple(weights)


def _dates(where: str, entry: Mapping) -> frozenset[date]:
    """`date` 单天、`dates` 若干天、`range` 一段、`ranges` 若干段，合成一组日期。"""
    days: set[date] = set()

    def day(value: object) -> date:
        try:
            return date.fromisoformat(str(value))
        except ValueError as e:
            raise RuntimeError(f"{where} 的日期 {value!r} 不是 YYYY-MM-DD") from e

    if "date" in entry:
        days.add(day(entry["date"]))
    for item in entry.get("dates", []):
        days.add(day(item))
    ranges = list(entry.get("ranges", []))
    if "range" in entry:
        ranges.append(entry["range"])
    for span in ranges:
        start, end = day(span["from"]), day(span["to"])
        if end < start:
            raise RuntimeError(f"{where} 的 range 结束早于开始：{start}..{end}")
        current = start
        while current <= end:
            days.add(current)
            current += timedelta(days=1)
    return frozenset(days)


def _chance(where: str, entry: Mapping, default: float) -> float:
    value = entry.get("chance", default)
    try:
        chance = float(value)
    except (TypeError, ValueError) as e:
        raise RuntimeError(f"{where} 的 chance 不是数字：{value!r}") from e
    if not 0.0 <= chance <= 1.0:
        raise RuntimeError(f"{where} 的 chance 要在 0-1：{chance}")
    return chance


def _activity(entry: Mapping) -> str:
    return str(entry.get("activity", "")).strip()


def _calendar(where: Path, data: Mapping, known: set[str]) -> dict[str, CalendarHoliday]:
    """`holidays.toml` 的日历本体：id → 哪天 + 去哪 + 她会说什么。"""
    calendar: dict[str, CalendarHoliday] = {}
    for index, entry in enumerate(data.get("holidays", [])):
        holiday_id = str(entry.get("id", ""))
        if not holiday_id:
            raise RuntimeError(f"日历表 {where}：holidays[{index}] 没有 id")
        if holiday_id in calendar:
            raise RuntimeError(f"日历表 {where}：id {holiday_id} 重复了")
        label = f"日历表 {where}：{holiday_id}"
        scenes, weights = _places(label, entry, known)
        days = _dates(label, entry)
        if not days:
            raise RuntimeError(f"{label} 没有 dates/ranges")
        activities = tuple(str(item) for item in entry.get("activities", []))
        calendar[holiday_id] = CalendarHoliday(
            id=holiday_id,
            name=str(entry.get("name", "")),
            name_ja=str(entry.get("name_ja", "")),
            kind=str(entry.get("kind", "")),
            days=days,
            scenes=scenes,
            weights=weights,
            activities=activities,
            note=str(entry.get("note", "")),
        )
    if not calendar:
        raise RuntimeError(f"日历表 {where} 里没有 [[holidays]]")
    return calendar


def _slot(path: Path, index: int, entry: Mapping, known: set[str]) -> Slot:
    where = f"排期表 {path}：slots[{index}]"
    day, slot = str(entry.get("day", "")), str(entry.get("slot", ""))
    if day not in DAYS:
        raise RuntimeError(f"{where} 的 day={day!r}，只有 {'/'.join(DAYS)}")
    if slot not in SLOTS:
        raise RuntimeError(f"{where} 的 slot={slot!r}，只有 {'/'.join(SLOTS)}")
    scenes, weights = _places(where, entry, known)
    weight = entry.get("weight", 1)
    try:
        weight = float(weight)
    except (TypeError, ValueError) as e:
        raise RuntimeError(f"{where} 的 weight 不是数字：{weight!r}") from e
    if weight <= 0:
        raise RuntimeError(f"{where} 的 weight 要大于 0：{weight}")
    return Slot(
        character=str(entry.get("character", "*")),
        day=day,
        slot=slot,
        weight=weight,
        scenes=scenes,
        weights=weights,
        activity_text=_activity(entry),
        why=str(entry.get("why", "")),
    )


def _pool(path: Path, index: int, entry: Mapping, known: set[str]) -> Pool:
    where = f"排期表 {path}：pools[{index}]"
    day, slot = str(entry.get("day", "any")), str(entry.get("slot", "any"))
    if day != "any" and day not in DAYS:
        raise RuntimeError(f"{where} 的 day={day!r}，只有 any 或 {'/'.join(DAYS)}")
    if slot != "any" and slot not in SLOTS:
        raise RuntimeError(f"{where} 的 slot={slot!r}，只有 any 或 {'/'.join(SLOTS)}")
    scenes, weights = _places(where, entry, known)
    return Pool(
        character=str(entry.get("character", "*")),
        day=day,
        slot=slot,
        chance=_chance(where, entry, 1.0),
        scenes=scenes,
        weights=weights,
        activity_text=_activity(entry),
        why=str(entry.get("why", "")),
    )


def _holiday(
    path: Path,
    index: int,
    entry: Mapping,
    calendar: Mapping[str, CalendarHoliday],
    known: set[str],
) -> Holiday:
    where = f"排期表 {path}：holidays[{index}]"
    holiday_id = str(entry.get("holiday", ""))
    if holiday_id not in calendar:
        raise RuntimeError(f"{where} 的 holiday={holiday_id!r} 不在 {path.parent / 'holidays.toml'}")
    scenes, weights = _places(where, entry, known)
    slots = frozenset(str(slot) for slot in entry.get("slots", SLOTS))
    unknown = slots - set(SLOTS)
    if unknown:
        raise RuntimeError(f"{where} 的 slots 里有 {sorted(unknown)}")
    if not slots:
        raise RuntimeError(f"{where} 的 slots 是空的")
    priority = entry.get("priority")
    if not isinstance(priority, int):
        raise RuntimeError(f"{where} 的 priority 要是整数：{priority!r}")
    return Holiday(
        character=str(entry.get("character", "*")),
        holiday=holiday_id,
        slots=slots,
        chance=_chance(where, entry, 1.0),
        priority=priority,
        scenes=scenes,
        weights=weights,
        activity_text=_activity(entry),
        why=str(entry.get("why", "")),
    )


def _priority_of(holiday: CalendarHoliday) -> int:
    """回落条目的优先级：先查 model.md 那张表，表里没有就按 `kind`（公休 90 / 振替 85）。"""
    known = HOLIDAY_PRIORITY.get(holiday.id)
    if known is not None:
        return known
    if holiday.kind in ("substitute", "citizens"):
        return SUBSTITUTE_PRIORITY
    return PUBLIC_PRIORITY


def _fallback_holiday(holiday: CalendarHoliday) -> Holiday:
    """日历里有、她的排期没写的节日：`holidays.toml` 的场景 + 第一条活动顶上。

    `activity_text` 留空，`_holiday_choice` 会拿 `calendar.activities[0]`；`why` 带「回落」，
    一眼能看出这条不是她写的。
    """
    return Holiday(
        character="*",
        holiday=holiday.id,
        slots=frozenset(HOLIDAY_SLOTS.get(holiday.id, HOLIDAY_DAY_SLOTS)),
        chance=HOLIDAY_WINDOW_CHANCE.get(holiday.id, 1.0),
        priority=_priority_of(holiday),
        scenes=holiday.scenes,
        weights=holiday.weights,
        activity_text="",
        why=f"回落：{holiday.name_ja or holiday.name}（{holiday.id}）",
    )


def _event(path: Path, index: int, entry: Mapping, known: set[str]) -> Event:
    where = f"排期表 {path}：events[{index}]"
    scenes, weights = _places(where, entry, known)
    conditions: dict[str, frozenset[str]] = {}
    for key, value in entry.get("conditions", {}).items():
        if key not in CONDITIONS:
            raise RuntimeError(f"{where} 的条件 {key!r}，只有 {'/'.join(CONDITIONS)}")
        values = value if isinstance(value, list) else [value]
        wanted = frozenset(str(item) for item in values)
        if not wanted:
            raise RuntimeError(f"{where} 的条件 {key} 是空的")
        conditions[str(key)] = wanted
    return Event(
        character=str(entry.get("character", "*")),
        chance=_chance(where, entry, 1.0),
        scenes=scenes,
        weights=weights,
        activity_text=_activity(entry),
        why=str(entry.get("why", "")),
        conditions=conditions,
    )
