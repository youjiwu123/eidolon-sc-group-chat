#!/usr/bin/env python3
"""把真乃 2026 年的排期渲染成人看的日历：HTML（12 个月网格）+ Markdown（速读）。

选择逻辑不重写：TOML 解析、日期展开、加权抽签直接用 `.scratch/schedule/simulate.py`
（`load_toml` / `dates_of` / `scene_list` / `pick`），`call()` 的判定顺序照抄
`simulate.py` 的 `main()`（节日覆盖 > 事件 > 固定槽位 > 随机池），连随机数的消耗顺序也一致。
固定种子 `random.Random(20260101)`，所以同一天重跑结果完全相同。

用法：python .scratch/schedule/calendar_2026.py
输出：characters/schedules.mano.2026.html
      characters/schedules.mano.2026.md
"""

from __future__ import annotations

import calendar as pycal
import collections
import dataclasses
import datetime as dt
import html
import pathlib
import random
import sys

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:  # 允许从别处 import 本文件
    sys.path.insert(0, str(HERE))

import simulate  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001 - 老终端不支持就算了，输出文件仍是 UTF-8
    pass

ROOT = simulate.ROOT
P_HTML = ROOT / "characters" / "schedules.mano.2026.html"
P_MD = ROOT / "characters" / "schedules.mano.2026.md"

YEAR = 2026
SEED = 20260101
WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
WEEKDAY_HEAD = ["一", "二", "三", "四", "五", "六", "日"]
SLOT_LABEL = {
    "morning": "早 6–10",
    "noon": "上午 10–14",
    "afternoon": "下午 14–18",
    "evening": "傍晚 18–22",
    "night": "深夜 22–2",
}
DRIVER_LABEL = {"holiday": "节日覆盖", "event": "事件", "slot": "固定槽位", "pool": "随机池"}
DRIVER_CLASS = {
    "holiday": "s-holiday",
    "event": "s-event",
    "slot": "s-slot",
    "pool": "s-pool",
}
DRIVER_COLOR = {"holiday": "#d92d20", "event": "#f79009", "slot": "#98a2b3", "pool": "#2e90fa"}
KIND_ORDER = {"public": 0, "substitute": 1, "citizens": 1, "festival": 2}
KIND_LABEL = {"public": "公休", "substitute": "振替休日", "citizens": "国民休日", "festival": "行事"}

# 84 个场景的 2 字短名（格子太窄，全名放 title）。key 必须与 scenes.toml 完全一致。
SHORT = {
    "lounge": "休息",
    "studio": "练习",
    "park": "公园",
    "beach": "海边",
    "home": "她家",
    "train": "电车",
    "studio_small": "小练",
    "stage": "舞台",
    "dressing_room": "化妆",
    "recording_studio": "录音",
    "photo_studio": "摄影",
    "office_corridor": "走廊",
    "meeting_room": "会议",
    "banquet": "宴会",
    "street": "街上",
    "street_night": "夜街",
    "shopstreet": "商店",
    "river": "河堤",
    "shrine": "神社",
    "park_night": "夜园",
    "garden": "花园",
    "classroom": "教室",
    "gym": "体育",
    "schoolyard": "操场",
    "cafe": "咖啡",
    "restaurant": "餐厅",
    "flowershop": "花店",
    "convenience_store": "便利",
    "car": "车里",
    "station": "车站",
    "kitchen": "厨房",
    "sky": "天空",
    "bedroom": "卧室",
    "apartment_living": "公寓",
    "home_living": "客厅",
    "washitsu": "和室",
    "bathroom": "浴室",
    "sento": "澡堂",
    "dorm": "宿舍",
    "esports_room": "电竞",
    "school_corridor": "校廊",
    "library": "图书",
    "music_room": "音乐",
    "art_room": "美术",
    "cooking_room": "家政",
    "lecture_hall": "阶梯",
    "school_gate": "校门",
    "roof": "天台",
    "office": "办公",
    "office_reception": "前台",
    "backstage": "后台",
    "bookstore": "书店",
    "supermarket": "超市",
    "mall": "商场",
    "arcade": "游戏",
    "cake_shop": "甜品",
    "bakery": "面包",
    "laundry": "洗衣",
    "general_store": "杂货",
    "petshop": "宠物",
    "izakaya": "居酒",
    "bar": "酒吧",
    "fastfood": "快餐",
    "station_hall": "站厅",
    "subway": "地铁",
    "airport": "机场",
    "vending_machine": "售货",
    "crossroad": "十字",
    "railway_crossing": "道口",
    "residential_street": "住宅",
    "alley": "小巷",
    "coast_road": "沿海",
    "stone_path": "石板",
    "observatory": "展望",
    "temple": "寺庙",
    "lake": "湖畔",
    "flower_field": "花田",
    "ginkgo": "银杏",
    "cherry": "樱花",
    "hospital_corridor": "医院",
    "exam_room": "诊察",
    "hall": "礼堂",
    "bowling": "保龄",
    "office_building": "大楼",
}

# 32 条日历在格子里的短名（假日名本身可以长，chip 只能 2-4 字）。
SHORT_HOLIDAY = {
    "new_year": "元旦",
    "coming_of_age": "成人节",
    "national_foundation_day": "建国纪念",
    "emperors_birthday": "天皇诞",
    "vernal_equinox": "春分",
    "showa_day": "昭和之日",
    "constitution_day": "宪法纪念",
    "greenery_day": "绿之日",
    "childrens_day": "儿童节",
    "substitute_holiday": "补休日",
    "marine_day": "海之日",
    "tanabata": "七夕",
    "natsumatsuri": "夏日祭",
    "mountain_day": "山之日",
    "obon": "盂兰盆",
    "respect_for_the_aged_day": "敬老日",
    "citizens_holiday": "国民休日",
    "autumnal_equinox": "秋分",
    "sports_day": "体育日",
    "halloween": "万圣节",
    "culture_day": "文化日",
    "momijigari": "红叶",
    "labor_thanksgiving_day": "勤劳感谢",
    "christmas_eve": "平安夜",
    "christmas": "圣诞节",
    "omisoka": "除夕",
    "setsubun": "节分",
    "valentine": "情人节",
    "hinamatsuri": "女儿节",
    "hanami": "赏花",
    "golden_week": "黄金周",
    "hatsumode": "初诣",
}


@dataclasses.dataclass
class Pick:
    slot: str
    scene: str
    driver: str
    source: str
    activity: str
    label: str


@dataclasses.dataclass
class Day:
    date: dt.date
    weather: str
    picks: list[Pick]
    cal_entries: list[dict]


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def span_text(dates: list[dt.date]) -> str:
    """把一串日期压成 01-01 / 03-25–04-05 这样（不跨年的连续段）。"""
    if not dates:
        return ""
    days = sorted(dates)
    groups: list[tuple[dt.date, dt.date]] = []
    start = prev = days[0]
    for day in days[1:]:
        if day == prev + dt.timedelta(days=1):
            prev = day
            continue
        groups.append((start, prev))
        start = prev = day
    groups.append((start, prev))
    out = []
    for start, end in groups:
        out.append(f"{start:%m-%d}" if start == end else f"{start:%m-%d}–{end:%m-%d}")
    return "、".join(out)


def index_holidays(holidays_doc: dict) -> tuple[list[dict], dict, dict]:
    """日历条目按日期/月份建索引；只保留 2026 年里有落点的条目。"""
    entries: list[dict] = []
    for order, raw in enumerate(holidays_doc["holidays"]):
        dates = sorted(d for d in simulate.dates_of(raw) if d.year == YEAR)
        if not dates:
            continue
        entry = dict(raw)
        entry["_order"] = order
        entry["_window"] = bool(raw.get("ranges") or raw.get("range"))
        entry["_dates"] = dates
        entry["_span"] = span_text(dates)
        entries.append(entry)

    by_date: dict[dt.date, list[dict]] = collections.defaultdict(list)
    by_month: dict[int, list[dict]] = collections.defaultdict(list)
    for entry in entries:
        for day in entry["_dates"]:
            by_date[day].append(entry)
        for month in sorted({d.month for d in entry["_dates"]}):
            by_month[month].append(entry)
    for day in by_date:
        by_date[day].sort(key=lambda e: (e["_window"], KIND_ORDER[e["kind"]], e["_order"]))
    for month in by_month:
        by_month[month].sort(key=lambda e: (e["_dates"][0], e["_window"], KIND_ORDER[e["kind"]]))
    return entries, dict(by_date), dict(by_month)


def index_overrides(sched: dict) -> dict[dt.date, list[dict]]:
    """排期文件里的 [[holidays]] 按日期建索引（priority 从大到小，同分按文件顺序）。"""
    by_date: dict[dt.date, list[dict]] = collections.defaultdict(list)
    for order, override in enumerate(sched.get("holidays", [])):
        for day in simulate.dates_of(override):
            if day.year == YEAR:
                by_date[day].append({**override, "_i": order})
    for day in by_date:
        by_date[day].sort(key=lambda o: (-o["priority"], o["_i"]))
    return dict(by_date)


def simulate_days(sched: dict, cal_by_date: dict, cal_name: dict, ov_by_date: dict,
                  day_entries: dict) -> list[Day]:
    """逐日跑 2026；call() 的判定顺序与随机数消耗照抄 simulate.py 的 main()。"""
    slot_index: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    for slot in sched["slots"]:
        slot_index[(slot["day"], slot["slot"])].append(slot)
    pool_by_slot = {pool["slot"]: pool for pool in sched["pools"]}
    events = sched.get("events", [])

    rng = random.Random(SEED)
    weather_pool = ["clear", "cloudy", "rain", "snow"]
    weather_w = [0.50, 0.27, 0.18, 0.05]

    def call(day: dt.date, slot: str, weather: str) -> Pick:
        ctx = {
            "season": simulate.SEASON[day.month],
            "weather": weather,
            "holiday": cal_by_date.get(day, set()),
            "weekday": "weekend" if day.weekday() >= 5 else "weekday",
            "slot": slot,
        }
        # 1. 节日覆盖：priority 从大到小，窗口期 chance 没中就继续看下一条
        for ov in ov_by_date.get(day, ()):
            if slot not in ov.get("slots", simulate.SLOTS):
                continue
            if rng.random() < ov.get("chance", 1.0):
                scenes, weights = simulate.scene_list(ov)
                scene = simulate.pick(rng, scenes, weights)
                return Pick(slot, scene, "holiday", ov["holiday"], ov.get("activity", ""),
                            cal_name[ov["holiday"]])
        # 2. 事件：文件顺序就是优先级，条件全中才 roll
        for i, event in enumerate(events):
            ok = True
            for key, value in event.get("conditions", {}).items():
                values = value if isinstance(value, list) else [value]
                actual = ctx[key]
                if isinstance(actual, set):
                    if not any(v in actual for v in values):
                        ok = False
                        break
                elif actual not in values:
                    ok = False
                    break
            if not ok:
                continue
            if rng.random() < event["chance"]:
                scenes, weights = simulate.scene_list(event)
                scene = simulate.pick(rng, scenes, weights)
                return Pick(slot, scene, "event", str(i), event.get("activity", ""), f"#{i}")
        # 3. 固定槽位：按 weight 加权
        cands = slot_index[(simulate.DAYS[day.weekday()], slot)]
        scenes = [c["scene"] for c in cands]
        weights = [c["weight"] for c in cands]
        scene = simulate.pick(rng, scenes, weights)
        activity = next((c.get("activity", "") for c in cands if c["scene"] == scene), "")
        # 4. 随机池：roll 中就把第 3 步换掉
        pool = pool_by_slot.get(slot) or pool_by_slot.get("any")
        if pool and rng.random() < pool["chance"]:
            pool_scenes, pool_weights = simulate.scene_list(pool)
            pool_scene = simulate.pick(rng, pool_scenes, pool_weights)
            return Pick(slot, pool_scene, "pool", str(pool["slot"]), "", str(pool["slot"]))
        return Pick(slot, scene, "slot", "-", activity, "固定槽位")

    days: list[Day] = []
    day = dt.date(YEAR, 1, 1)
    last = dt.date(YEAR, 12, 31)
    while day <= last:
        weather = rng.choices(weather_pool, weights=weather_w, k=1)[0]
        picks = [call(day, slot, weather) for slot in simulate.SLOTS]
        days.append(Day(day, weather, picks, day_entries.get(day, [])))
        day += dt.timedelta(days=1)
    return days


def summarize(days: list[Day], entries: list[dict]) -> dict:
    calls: collections.Counter[str] = collections.Counter()
    day_hits: collections.Counter[str] = collections.Counter()
    scenes: collections.Counter[str] = collections.Counter()
    month_scenes: dict[int, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    for day in days:
        seen: set[str] = set()
        for pick in day.picks:
            calls[pick.driver] += 1
            scenes[pick.scene] += 1
            month_scenes[day.date.month][pick.scene] += 1
            seen.add(pick.driver)
        for driver in seen:
            day_hits[driver] += 1

    off_days: set[dt.date] = set()
    fest_days: set[dt.date] = set()
    window_entries = []
    tagged: set[dt.date] = set()
    for entry in entries:
        tagged.update(entry["_dates"])
        if entry["_window"]:
            window_entries.append(entry)
        elif entry["kind"] in ("public", "substitute", "citizens"):
            off_days.update(entry["_dates"])
        else:
            fest_days.update(entry["_dates"])
    return {
        "total": sum(calls.values()),
        "calls": calls,
        "day_hits": day_hits,
        "scenes": scenes,
        "month_scenes": dict(month_scenes),
        "off_days": sorted(off_days),
        "fest_days": sorted(fest_days),
        "window_entries": window_entries,
        "tagged_days": tagged,
    }


def render_tag(entry: dict) -> str:
    if entry["_window"]:
        cls = "tag tag-window"
    elif entry["kind"] == "public":
        cls = "tag tag-public"
    elif entry["kind"] in ("substitute", "citizens"):
        cls = "tag tag-sub"
    else:
        cls = "tag tag-fest"
    title = (f"{entry['name']}（{entry.get('name_ja', '')}）"
             f"· {KIND_LABEL[entry['kind']]} · {entry['_span']}")
    label = SHORT_HOLIDAY.get(entry["id"], entry["name"])
    return (f'<span class="{cls}" data-holiday="{esc(entry["id"])}" '
            f'title="{esc(title)}">{esc(label)}</span>')


def render_pick(pick: Pick, name: dict[str, str]) -> str:
    title = f"{SLOT_LABEL[pick.slot]}｜{name[pick.scene]}｜"
    if pick.driver == "holiday":
        title += f"节日覆盖·{pick.label}"
    elif pick.driver == "event":
        title += f"事件 {pick.label}"
    elif pick.driver == "pool":
        title += f"随机池·{pick.label}"
    else:
        title += "固定槽位"
    if pick.activity:
        title += f"：{pick.activity}"
    return (f'<span class="s {DRIVER_CLASS[pick.driver]}" data-scene="{esc(pick.scene)}" '
            f'data-driver="{pick.driver}" title="{esc(title)}">{esc(SHORT[pick.scene])}</span>')


def render_day_cell(day: Day, name: dict[str, str]) -> str:
    date = day.date
    weekday = date.weekday()
    off = any(not e["_window"] and e["kind"] in ("public", "substitute", "citizens")
              for e in day.cal_entries)
    fest = any(not e["_window"] and e["kind"] == "festival" for e in day.cal_entries)
    cls = "day off" if off else ("day fest" if fest else "day")
    num_cls = "dnum"
    if off or weekday == 6:
        num_cls += " sun"
    elif weekday == 5:
        num_cls += " sat"
    tags = "".join(render_tag(e) for e in day.cal_entries)
    tag_text = " ".join(SHORT_HOLIDAY.get(e["id"], e["name"]) for e in day.cal_entries)
    label = f"{date.month}月{date.day}日 {WEEKDAY_CN[weekday]}"
    if tag_text:
        label += f" {tag_text}"
    chips = "".join(render_pick(p, name) for p in day.picks)
    return (
        f'<td class="{cls}" data-date="{date.isoformat()}" aria-label="{esc(label)}">'
        f'<div class="dhead"><span class="{num_cls}">{date.day}</span>'
        f'<span class="tags">{tags}</span></div>'
        f'<div class="slots" aria-label="五个时段">{chips}</div>'
        f"</td>"
    )


def render_month(month: int, days_by_date: dict[dt.date, Day], entries_by_month: dict,
                 name: dict[str, str]) -> str:
    weeks = pycal.Calendar(firstweekday=0).monthdayscalendar(YEAR, month)
    rows = []
    for week in weeks:
        cells = []
        for index, day_num in enumerate(week):
            if day_num == 0:
                cells.append('<td class="pad"></td>')
            else:
                cells.append(render_day_cell(days_by_date[dt.date(YEAR, month, day_num)], name))
        rows.append("<tr>" + "".join(cells) + "</tr>")

    entries = entries_by_month.get(month, [])
    if entries:
        holiday_list = "".join(
            f'<span class="mh"><b>{esc(e["name"])}</b> <i>{esc(e["_span"])}</i></span>'
            for e in entries
        )
    else:
        holiday_list = '<span class="mh muted">本月没有公休或行事，按作息走</span>'

    head_cells = []
    for index, label in enumerate(WEEKDAY_HEAD):
        cls = "wd sun" if index == 6 else ("wd sat" if index == 5 else "wd")
        head_cells.append(f'<th class="{cls}" scope="col">{label}</th>')

    day_count = sum(1 for week in weeks for n in week if n)
    return (
        f'<section class="month" id="m{month}" aria-labelledby="m{month}-h">'
        f'<div class="mhead"><h2 id="m{month}-h">{month} 月'
        f'<span class="cnt">{day_count} 天</span></h2>'
        f'<p class="mhol">{holiday_list}</p></div>'
        f'<table class="cal"><thead><tr>{"".join(head_cells)}</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
        f"</section>"
    )


CSS = """
*, *::before, *::after { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  padding: 22px 24px 48px;
  background: #f6f7f9;
  color: #101828;
  font-family: "Segoe UI", "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC",
    "Source Han Sans SC", system-ui, sans-serif;
  font-size: 14px;
  line-height: 1.5;
}
.wrap { max-width: 1232px; margin: 0 auto; }
h1 { margin: 0 0 6px; font-size: 25px; line-height: 1.25; letter-spacing: .01em; }
.sub { margin: 0; color: #667085; font-size: 12.5px; }
.sub code, .foot code { font-family: inherit; background: #eef2f6; border-radius: 3px; padding: 0 3px; }
.glance {
  margin: 12px 0 0;
  padding: 10px 14px;
  background: #fff;
  border: 1px solid #e4e7ec;
  border-left: 4px solid #b42318;
  border-radius: 8px;
  font-size: 13.5px;
}
.glance b { color: #b42318; font-weight: 600; }
.jump { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0 0; }
.jump a {
  padding: 1px 9px;
  border: 1px solid #e4e7ec;
  border-radius: 999px;
  background: #fff;
  color: #475467;
  font-size: 11.5px;
  text-decoration: none;
}
.jump a:hover { border-color: #98a2b3; }
.summary {
  display: grid;
  grid-template-columns: minmax(0, 1.05fr) minmax(0, 1.1fr) minmax(0, .95fr);
  gap: 12px;
  margin: 14px 0 18px;
  align-items: start;
}
.card {
  background: #fff;
  border: 1px solid #e4e7ec;
  border-radius: 10px;
  padding: 12px 14px 13px;
}
.card h2 {
  margin: 0 0 9px;
  color: #667085;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .08em;
}
.drv { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.drv th {
  padding: 0 0 4px;
  color: #98a2b3;
  font-size: 11px;
  font-weight: 600;
  text-align: right;
}
.drv th:first-child { text-align: left; }
.drv td { padding: 3px 0; border-top: 1px solid #f2f4f7; }
.drv td.num { text-align: right; color: #344054; font-variant-numeric: tabular-nums; }
.drv tr.total td { border-top: 1px solid #e4e7ec; color: #101828; font-weight: 600; }
.k { display: inline-flex; align-items: center; gap: 6px; }
.dot { display: inline-block; width: 9px; height: 9px; border-radius: 2px; }
.note { margin: 8px 0 0; color: #667085; font-size: 11px; line-height: 1.55; }
.top { margin: 0; padding: 0; list-style: none; font-size: 12.5px; }
.top li {
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr) 42px 60px;
  gap: 6px;
  align-items: center;
  padding: 2.5px 0;
}
.top .idx { color: #98a2b3; text-align: right; font-variant-numeric: tabular-nums; }
.top .nm { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.top .cnt { color: #475467; text-align: right; font-variant-numeric: tabular-nums; }
.top .bar { height: 6px; border-radius: 3px; background: #eef2f6; overflow: hidden; }
.top .bar i { display: block; height: 100%; background: #98a2b3; border-radius: 3px; }
.legend { display: grid; gap: 5px; font-size: 11.5px; color: #475467; }
.lg { display: flex; align-items: center; gap: 7px; }
.lg .cap { color: #667085; }
.lg-sep { height: 1px; margin: 3px 0; background: #f2f4f7; }
.months { display: grid; grid-template-columns: 1fr; gap: 16px; }
.month {
  background: #fff;
  border: 1px solid #e4e7ec;
  border-radius: 10px;
  padding: 10px 12px 12px;
}
.mhead { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 12px; margin-bottom: 6px; }
.mhead h2 { margin: 0; font-size: 15px; }
.mhead .cnt { margin-left: 5px; color: #98a2b3; font-size: 11px; font-weight: 500; }
.mhol { display: flex; flex-wrap: wrap; gap: 2px 10px; margin: 0; color: #667085; font-size: 11px; }
.mhol .mh b { color: #344054; font-weight: 600; }
.mhol .mh i { color: #98a2b3; font-style: normal; font-variant-numeric: tabular-nums; }
.mhol .muted { color: #98a2b3; }
table.cal { width: 100%; border-collapse: separate; border-spacing: 4px; table-layout: fixed; }
.cal th { padding: 1px 0 2px; color: #98a2b3; font-size: 11px; font-weight: 600; text-align: center; }
.cal th.sun { color: #b42318; }
.cal th.sat { color: #175cd3; }
.cal td {
  height: 56px;
  padding: 3px 4px 4px;
  vertical-align: top;
  background: #fff;
  border: 1px solid #eef0f3;
  border-radius: 6px;
}
.cal td.pad { background: transparent; border: 0; }
.cal td.day.off { background: #fffbfa; border-color: #f4d7d3; }
.cal td.day.fest { background: #fffafc; border-color: #f3dfe8; }
.dhead { display: flex; flex-wrap: wrap; align-items: center; gap: 2px 3px; min-height: 17px; }
.dnum { min-width: 15px; font-size: 12px; font-weight: 700; line-height: 1.2; }
.dnum.sun { color: #b42318; }
.dnum.sat { color: #175cd3; }
.tags { display: inline-flex; flex-wrap: wrap; gap: 2px; }
.tag {
  padding: 0 3px;
  border-radius: 3px;
  font-size: 9.5px;
  line-height: 1.4;
  white-space: nowrap;
}
.tag-public { background: #fee4e2; color: #b42318; }
.tag-sub { background: #f4f3ff; color: #5925dc; }
.tag-fest { background: #fdf2fa; color: #c11574; }
.tag-window { padding: 0 2px; border: 1px dashed #e4c581; color: #8a6a1a; }
.slots { display: flex; flex-wrap: wrap; gap: 2px; margin-top: 3px; }
.s {
  padding: 0 2.5px;
  border: 1px solid transparent;
  border-radius: 3px;
  font-size: 10.5px;
  line-height: 1.35;
  white-space: nowrap;
}
.s-holiday { background: #fee4e2; border-color: #fda29b; color: #b42318; }
.s-event { background: #fef0c7; border-color: #fec84b; color: #b54708; }
.s-slot { background: #f2f4f7; border-color: #e4e7ec; color: #475467; }
.s-pool { background: #eff8ff; border-color: #b2ddff; color: #175cd3; }
.foot {
  margin-top: 20px;
  padding-top: 12px;
  border-top: 1px solid #e4e7ec;
  color: #667085;
  font-size: 11.5px;
}
.foot p { margin: 0 0 4px; }
@media print {
  @page { size: A4 portrait; margin: 9mm 8mm; }
  body {
    padding: 0;
    background: #fff;
    color: #000;
    font-size: 9pt;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
  .wrap { max-width: none; }
  h1 { font-size: 15pt; }
  .sub { font-size: 7.5pt; }
  .glance { margin-top: 6px; padding: 6px 9px; font-size: 8.5pt; }
  .jump, .foot { display: none; }
  .summary { gap: 6px; margin: 8px 0; }
  .card { padding: 6px 8px; border-radius: 6px; }
  .card h2 { margin-bottom: 4px; font-size: 7.5pt; }
  .drv, .top, .legend { font-size: 7.5pt; }
  .note { font-size: 6.5pt; }
  .months { gap: 7px; }
  .month {
    padding: 4px 6px 6px;
    border-radius: 6px;
    break-inside: avoid;
    page-break-inside: avoid;
  }
  .mhead { margin-bottom: 3px; }
  .mhead h2 { font-size: 10pt; }
  .mhol { font-size: 7pt; }
  table.cal { border-spacing: 2px; }
  .cal th { font-size: 7pt; }
  .cal td { height: auto; padding: 1px 2px 2px; border-radius: 3px; }
  .dnum { font-size: 8pt; }
  .tag { font-size: 6.5pt; padding: 0 2px; }
  .s { font-size: 7pt; padding: 0 1.5px; border-radius: 2px; }
  .slots { gap: 1px; margin-top: 1px; }
}
"""


def build_html(model: dict, stats: dict) -> str:
    days: list[Day] = model["days"]
    name: dict[str, str] = model["name"]
    entries_by_month: dict = model["entries_by_month"]
    days_by_date = {day.date: day for day in days}

    total = stats["total"]
    calls = stats["calls"]
    day_hits = stats["day_hits"]
    scenes = stats["scenes"]
    top10 = scenes.most_common(10)
    max_count = top10[0][1] if top10 else 1
    top_name = name[top10[0][0]] if top10 else "—"
    top_count = top10[0][1] if top10 else 0

    glance = (
        f"看完一眼：2026 年 365 天里，<b>节日覆盖改写了 {day_hits.get('holiday', 0)} 天</b>"
        f"（{calls.get('holiday', 0)} 次通话），<b>事件落在 {day_hits.get('event', 0)} 天</b>"
        f"（{calls.get('event', 0)} 次）；固定槽位撑起 {day_hits.get('slot', 0)} 天、"
        f"随机池换掉 {day_hits.get('pool', 0)} 天。全年出现最多的是「{top_name}」"
        f"（{top_count} 次）。带节日/行事标签的日子共 {len(stats['tagged_days'])} 天。"
    )

    rows = []
    for driver in ("holiday", "event", "slot", "pool"):
        count = calls.get(driver, 0)
        share = 100.0 * count / total if total else 0.0
        rows.append(
            f'<tr><td><span class="k"><span class="dot" style="background:'
            f'{DRIVER_COLOR[driver]}"></span>{DRIVER_LABEL[driver]}</span></td>'
            f'<td class="num">{count}</td><td class="num">{share:.1f}%</td>'
            f'<td class="num">{day_hits.get(driver, 0)}</td></tr>'
        )
    driver_table = (
        '<table class="drv"><thead><tr><th>驱动</th><th>通话</th><th>占比</th><th>天数</th>'
        "</tr></thead><tbody>" + "".join(rows) +
        f'<tr class="total"><td>合计</td><td class="num">{total}</td>'
        f'<td class="num">100%</td><td class="num">365</td></tr></tbody></table>'
        f'<p class="note">节日标签：{len(stats["off_days"])} 天公休（含振替/国民休日）'
        f'· {len(stats["fest_days"])} 天单日行事 · {len(stats["window_entries"])} 段窗口'
        f"（同一天可叠加多个标签；「天数」列有重叠）。</p>"
    )

    top_items = []
    for index, (scene, count) in enumerate(top10, 1):
        width = max(2.0, 100.0 * count / max_count)
        top_items.append(
            f'<li><span class="idx">{index}</span>'
            f'<span class="nm" title="{esc(name[scene])}">{esc(name[scene])}</span>'
            f'<span class="cnt">{count}</span>'
            f'<span class="bar"><i style="width:{width:.1f}%"></i></span></li>'
        )
    top_list = '<ol class="top">' + "".join(top_items) + "</ol>"

    legend = (
        '<div class="legend">'
        '<div class="lg"><span class="s s-holiday">神社</span>'
        '<span class="cap">节日覆盖（holidays）</span></div>'
        '<div class="lg"><span class="s s-event">公园</span>'
        '<span class="cap">事件（events）</span></div>'
        '<div class="lg"><span class="s s-slot">教室</span>'
        '<span class="cap">固定槽位（slots）</span></div>'
        '<div class="lg"><span class="s s-pool">车站</span>'
        '<span class="cap">随机池（pools）</span></div>'
        '<div class="lg-sep"></div>'
        '<div class="lg"><span class="tag tag-public">元旦</span>'
        '<span class="cap">公休 / 振替 / 国民休日</span></div>'
        '<div class="lg"><span class="tag tag-sub">补休日</span>'
        '<span class="cap">补出来的休日</span></div>'
        '<div class="lg"><span class="tag tag-fest">七夕</span>'
        '<span class="cap">单日行事（节分・七夕・圣诞…）</span></div>'
        '<div class="lg"><span class="tag tag-window">初诣</span>'
        '<span class="cap">窗口期行事（虚线，整段有效）</span></div>'
        "</div>"
        '<p class="note">每格 5 块 = 早 → 深夜；悬停看场景全名、时段与 activity。</p>'
    )

    months_html = "".join(
        render_month(month, days_by_date, entries_by_month, name) for month in range(1, 13)
    )
    jump = "".join(f'<a href="#m{month}">{month} 月</a>' for month in range(1, 13))

    header = (
        '<header class="page-head">'
        "<h1>真乃 2026 年日历</h1>"
        '<p class="sub">365 天 × 5 个时段 = 1825 次通话 · 时区 Asia/Tokyo · '
        "固定种子 <code>random.Random(20260101)</code> · 数据："
        "<code>schedules.mano.week.draft.toml</code> + <code>holidays.toml</code> + "
        "<code>scenes.toml</code>（84 个场景）</p>"
        f'<p class="glance">{glance}</p>'
        f'<nav class="jump" aria-label="跳到月份">{jump}</nav>'
        "</header>"
    )
    summary = (
        '<section class="summary" aria-label="全年统计">'
        f'<div class="card"><h2>驱动来源（全年 1825 次通话）</h2>{driver_table}</div>'
        f'<div class="card"><h2>最常出现的 10 个场景</h2>{top_list}</div>'
        f'<div class="card"><h2>图例</h2>{legend}</div>'
        "</section>"
    )
    footer = (
        '<footer class="foot">'
        "<p>数据：<code>characters/schedules.mano.week.draft.toml</code>（slots / pools / "
        "holidays / events）· <code>characters/holidays.toml</code>（2026 公休 + 行事）· "
        "<code>characters/scenes.toml</code>（84 个场景）。</p>"
        "<p>选择顺序按 <code>characters/schedules.model.md</code>：节日覆盖 &gt; 事件 &gt; "
        "固定槽位 &gt; 随机池；时区 Asia/Tokyo（固定 +09:00）。</p>"
        "<p>固定随机种子 <code>random.Random(20260101)</code>，模拟脚本 "
        "<code>.scratch/schedule/calendar_2026.py</code>（选择逻辑复用 "
        "<code>.scratch/schedule/simulate.py</code>）；重跑同一天结果一致。只读渲染，不改排期数据。</p>"
        "</footer>"
    )

    return "\n".join([
        "<!doctype html>",
        '<html lang="zh-CN">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta name="color-scheme" content="light">',
        "<title>真乃 2026 年日历 · 全年场景排期</title>",
        '<meta name="description" content="真乃 2026 年 365 天 × 5 个时段的场景排期日历，'
        '按节日/事件/固定槽位/随机池着色。">',
        "<style>",
        CSS.strip(),
        "</style>",
        "</head>",
        "<body>",
        '<div class="wrap">',
        header,
        summary,
        '<main class="months">',
        months_html,
        "</main>",
        footer,
        "</div>",
        "</body>",
        "</html>",
        "",
    ])


def build_md(model: dict, stats: dict) -> str:
    days: list[Day] = model["days"]
    name: dict[str, str] = model["name"]
    entries_by_month: dict = model["entries_by_month"]
    calls = stats["calls"]
    day_hits = stats["day_hits"]

    lines = [
        "# 真乃 2026 年日历（速读）",
        "",
        "> 12 个月网格版（可离线双击打开）：`characters/schedules.mano.2026.html`",
        "",
        "- **数据**：`characters/schedules.mano.week.draft.toml`（slots / pools / holidays / "
        "events）+ `characters/holidays.toml` + `characters/scenes.toml`（84 个场景）",
        "- **选择顺序**：`characters/schedules.model.md`（节日覆盖 > 事件 > 固定槽位 > 随机池），"
        "时区 Asia/Tokyo",
        f"- **固定种子**：`random.Random({SEED})`——重跑同一天结果一致；365 天 × 5 段 = "
        f"{stats['total']} 次通话",
        f"- **驱动次数**：节日 {calls.get('holiday', 0)} · 事件 {calls.get('event', 0)} · "
        f"槽位 {calls.get('slot', 0)} · 池 {calls.get('pool', 0)}",
        f"- **覆盖天数**：节日 {day_hits.get('holiday', 0)} 天 · 事件 {day_hits.get('event', 0)} 天 · "
        f"槽位 {day_hits.get('slot', 0)} 天 · 池 {day_hits.get('pool', 0)} 天（同一天可叠加）",
        "- **口径**：每个特殊日一行，列出当天 5 个时段里出现过的场景（去重、按时段顺序）；"
        "窗口型行事（初诣 / 赏花 / GW / 夏祭 / お盆 / 红叶）不逐日展开，单列「窗口」一行。",
        "",
    ]

    for month in range(1, 13):
        month_days = [day for day in days if day.date.month == month]
        lines.append(f"## {month} 月")
        lines.append("")
        special = [day for day in month_days if any(not e["_window"] for e in day.cal_entries)]
        for day in special:
            primary = [e for e in day.cal_entries if not e["_window"]]
            label = "、".join(e["name"] for e in primary)
            scene_names = " / ".join(dict.fromkeys(name[p.scene] for p in day.picks))
            holiday_calls = sum(1 for p in day.picks if p.driver == "holiday")
            suffix = "" if holiday_calls else "（当天没走节日，按作息/事件/池子）"
            lines.append(f"- {day.date:%m-%d} {label} → {scene_names}{suffix}")
        if not special:
            lines.append("- 本月没有公休或单日行事。")
        windows = [e for e in entries_by_month.get(month, []) if e["_window"]]
        if windows:
            window_text = " · ".join(
                f"{e['name']} {e['_span']}（{len(e['_dates'])} 天）" for e in windows
            )
            lines.append(f"- 窗口：{window_text}")
        top2 = stats["month_scenes"].get(month, collections.Counter()).most_common(2)
        if top2:
            lines.append("- 本月 Top2：" + " · ".join(f"{name[s]} {c} 次" for s, c in top2))
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        f"全年：节日 {calls.get('holiday', 0)} 次 / 事件 {calls.get('event', 0)} 次 / "
        f"固定槽位 {calls.get('slot', 0)} 次 / 随机池 {calls.get('pool', 0)} 次；"
        f"带节日或行事标签的日子 {len(stats['tagged_days'])} 天。"
    )
    lines.append("")
    return "\n".join(lines)


def compute() -> tuple[dict, dict]:
    scenes_doc = simulate.load_toml(simulate.P_SCENES)
    holidays_doc = simulate.load_toml(simulate.P_HOLIDAYS)
    sched = simulate.load_toml(simulate.P_SCHEDULE)
    known = {row["id"] for row in scenes_doc["scenes"]}
    name = {row["id"]: row["name"] for row in scenes_doc["scenes"]}
    if set(SHORT) != known:
        raise SystemExit(f"SHORT 与 scenes.toml 不一致：多 {sorted(set(SHORT) - known)}，"
                         f"缺 {sorted(known - set(SHORT))}")

    entries, entries_by_date, entries_by_month = index_holidays(holidays_doc)
    cal_by_date = {day: {e["id"] for e in es} for day, es in entries_by_date.items()}
    cal_name = {h["id"]: h["name"] for h in holidays_doc["holidays"]}
    ov_by_date = index_overrides(sched)

    days = simulate_days(sched, cal_by_date, cal_name, ov_by_date, entries_by_date)
    stats = summarize(days, entries)

    if len(days) != 365:
        raise SystemExit(f"天数不是 365：{len(days)}")
    if stats["total"] != 365 * 5:
        raise SystemExit(f"通话次数不是 1825：{stats['total']}")
    for day in days:
        if len(day.picks) != 5:
            raise SystemExit(f"{day.date} 不是 5 个时段")
        for pick in day.picks:
            if pick.scene not in known:
                raise SystemExit(f"{day.date} 出现未知场景 {pick.scene}")
    if days[0].date != dt.date(YEAR, 1, 1) or days[-1].date != dt.date(YEAR, 12, 31):
        raise SystemExit("日期区间不对")

    model = {
        "days": days,
        "name": name,
        "known": known,
        "entries": entries,
        "entries_by_month": entries_by_month,
    }
    return model, stats


def main() -> None:
    model, stats = compute()
    html_text = build_html(model, stats)
    md_text = build_md(model, stats)
    P_HTML.write_text(html_text, encoding="utf-8", newline="\n")
    P_MD.write_text(md_text, encoding="utf-8", newline="\n")

    calls = stats["calls"]
    name = model["name"]
    print("== 真乃 2026 日历 ==")
    print(f"  天数 {len(model['days'])} · 通话 {stats['total']}")
    print("  驱动（次）：" + " · ".join(
        f"{DRIVER_LABEL[d]} {calls.get(d, 0)}" for d in ("holiday", "event", "slot", "pool")))
    print("  驱动（天）：" + " · ".join(
        f"{DRIVER_LABEL[d]} {stats['day_hits'].get(d, 0)}" for d in ("holiday", "event", "slot", "pool")))
    print("  Top5：" + " · ".join(f"{name[s]} {c}" for s, c in stats["scenes"].most_common(5)))
    print(f"  HTML：{P_HTML.relative_to(ROOT)} ({P_HTML.stat().st_size / 1024:.1f} KB)")
    print(f"  MD  ：{P_MD.relative_to(ROOT)} ({P_MD.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
