#!/usr/bin/env python3
"""排期数据校验 + 一年覆盖模拟。

跑的是一整年（2026-01-01 .. 2026-12-31，逐日、每天五个时段），不是抽样：
一年 365 天 x 5 = 1825 次通话，2026 年的公休/行事全部在区间里，一条都不会漏。

做四件事：
  1. tomllib 解析 characters/holidays.toml 和 characters/schedules.mano.week.draft.toml；
  2. 断言所有被引用的 scene id 都在 characters/scenes.toml 的 84 条里，并检查
     槽位/池子/节日/事件的结构一致性（池子与固定槽位不重叠、日常场景一个不落、
     holidays.toml 与排期文件日期镜像一致、每个节日都有覆盖条目……）；
  3. 按 schedules.model.md 的顺序（节日 > 事件 > 槽位 > 池子）跑一遍全年，打印
     场景可达数、节日驱动占比、前 10 分布、事件/节日命中明细；
  4. 抽出周一、周六、2026-01-01、2026-07-07、2026-12-24 五天（取全年那一次的真实结果），
     打印每个时段选中的场景。

用法：python .scratch/schedule/simulate.py
同时写一份 UTF-8 报告到 .scratch/schedule/simulate.report.txt。
"""

from __future__ import annotations

import collections
import datetime as dt
import pathlib
import random
import sys
import tomllib

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001 - 老终端不支持就算了，报告文件仍是 UTF-8
    pass

ROOT = pathlib.Path(__file__).resolve().parents[2]
P_SCENES = ROOT / "characters" / "scenes.toml"
P_HOLIDAYS = ROOT / "characters" / "holidays.toml"
P_SCHEDULE = ROOT / "characters" / "schedules.mano.week.draft.toml"
P_REPORT = pathlib.Path(__file__).resolve().parent / "simulate.report.txt"

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
SLOTS = ["morning", "noon", "afternoon", "evening", "night"]
SEASON = {
    3: "spring", 4: "spring", 5: "spring",
    6: "summer", 7: "summer", 8: "summer",
    9: "autumn", 10: "autumn", 11: "autumn",
    12: "winter", 1: "winter", 2: "winter",
}
COND_KEYS = {"season", "weather", "holiday", "weekday", "slot"}

# 事件/节日专用，不进日常随机池（理由见 characters/schedules.model.md）
SPECIAL = {
    "stage": "演出（周六下午固定槽位）",
    "backstage": "演出（周六中午固定槽位）",
    "banquet": "宴会厅：打ち上げ / 圣诞会",
    "beach": "海边：要出远门（夏日事件 + 海の日）",
    "flower_field": "季节限定（山の日）",
    "cherry": "季节限定（花見）",
    "ginkgo": "季节限定（紅葉狩り）",
    "hospital_corridor": "生病（冬天事件）",
    "exam_room": "生病（冬天事件）",
    "hall": "礼堂：学园祭/合唱祭（文化の日）",
    "izakaya": "未成年，只在忘年会事件里",
    "bar": "未成年，只在忘年会事件里",
    "airport": "出远门",
    "bowling": "要专门约",
}
FALLBACK = {"sky"}

out: list[str] = []


def p(*parts: object) -> None:
    line = " ".join(str(x) for x in parts)
    out.append(line)
    print(line)


def flush() -> None:
    P_REPORT.parent.mkdir(parents=True, exist_ok=True)
    P_REPORT.write_text("\n".join(out) + "\n", encoding="utf-8")


def die(msg: str) -> None:
    p("\nFATAL:", msg)
    flush()
    sys.exit(2)


def load_toml(path: pathlib.Path) -> dict:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def dates_of(entry: dict) -> set[dt.date]:
    got: set[dt.date] = set()
    if "date" in entry:  # 单条简写
        got.add(dt.date.fromisoformat(entry["date"]))
    for s in entry.get("dates", []):
        got.add(dt.date.fromisoformat(s))
    ranges = list(entry.get("ranges", []))
    if "range" in entry:  # 单条简写
        ranges.append(entry["range"])
    for r in ranges:
        cur = dt.date.fromisoformat(r["from"])
        end = dt.date.fromisoformat(r["to"])
        while cur <= end:
            got.add(cur)
            cur += dt.timedelta(days=1)
    return got


def scene_list(entry: dict) -> tuple[list[str], list[int]]:
    if "scene" in entry:
        return [entry["scene"]], [1]
    scenes = list(entry["scenes"])
    return scenes, list(entry.get("weights", [1] * len(scenes)))


def pick(rng: random.Random, scenes: list[str], weights: list[int]) -> str:
    return rng.choices(scenes, weights=weights, k=1)[0]


def main() -> None:  # noqa: C901 - 校验脚本，拆开反而难读
    for path in (P_SCENES, P_HOLIDAYS, P_SCHEDULE):
        if not path.exists():
            die(f"缺文件 {path}")

    scenes_doc = load_toml(P_SCENES)
    holidays_doc = load_toml(P_HOLIDAYS)
    sched = load_toml(P_SCHEDULE)

    scene_rows = scenes_doc["scenes"]
    known = {row["id"] for row in scene_rows}
    name = {row["id"]: row["name"] for row in scene_rows}

    p("== 0. 解析 ==")
    p(f"  scenes.toml    : {len(scene_rows)} 个场景")
    p(f"  holidays.toml  : {len(holidays_doc.get('holidays', []))} 条日历")
    p(f"  schedules draft: slots={len(sched.get('slots', []))} pools={len(sched.get('pools', []))} "
      f"holidays={len(sched.get('holidays', []))} events={len(sched.get('events', []))}")

    errors: list[str] = []
    missing_scene: list[str] = []

    def check_scenes(where: str, scenes: list[str]) -> None:
        for s in scenes:
            if s not in known:
                missing_scene.append(f"{where}: {s}")

    if len(known) != 84:
        errors.append(f"scenes.toml 不是 84 条，是 {len(known)}")

    slots = sched.get("slots", [])
    pools = sched.get("pools", [])
    overrides = sched.get("holidays", [])
    events = sched.get("events", [])
    cal = {h["id"]: h for h in holidays_doc.get("holidays", [])}
    cal_dates = {hid: dates_of(h) for hid, h in cal.items()}

    # ---- scene id 存在性 + 字段 ----
    fixed_scenes: list[str] = []
    for i, s in enumerate(slots):
        if s.get("character") != "mano":
            errors.append(f"slot[{i}] character={s.get('character')!r}")
        if s.get("day") not in DAYS:
            errors.append(f"slot[{i}] day={s.get('day')!r}")
        if s.get("slot") not in SLOTS:
            errors.append(f"slot[{i}] slot={s.get('slot')!r}")
        check_scenes(f"slot[{i}]", [s["scene"]])
        fixed_scenes.append(s["scene"])
        if not isinstance(s.get("weight"), int) or s["weight"] < 1:
            errors.append(f"slot[{i}] weight={s.get('weight')!r}")

    for i, pool in enumerate(pools):
        sc, wt = scene_list(pool)
        check_scenes(f"pool[{i}]", sc)
        if len(sc) != len(wt):
            errors.append(f"pool[{i}] scenes/weights 不等长 {len(sc)} vs {len(wt)}")
        if not (0.15 <= pool.get("chance", 0) <= 0.25):
            errors.append(f"pool[{i}] chance={pool.get('chance')!r} 不在 0.15-0.25")
        if pool.get("day") != "any":
            errors.append(f"pool[{i}] day={pool.get('day')!r}")

    for h in cal.values():
        sc, wt = scene_list(h)
        check_scenes(f"holidays.toml[{h['id']}]", sc)
        if not (1 <= len(sc) <= 3):
            errors.append(f"holidays.toml[{h['id']}] scenes 不是 1-3 条：{len(sc)}")
        if len(sc) != len(wt):
            errors.append(f"holidays.toml[{h['id']}] scenes/weights 不等长")
        if h.get("kind") not in {"public", "substitute", "citizens", "festival"}:
            errors.append(f"holidays.toml[{h['id']}] kind={h.get('kind')!r}")
        if not dates_of(h):
            errors.append(f"holidays.toml[{h['id']}] 没有 dates/ranges")
        if not h.get("activities"):
            errors.append(f"holidays.toml[{h['id']}] 没有 activities")

    for i, ov in enumerate(overrides):
        hid = ov.get("holiday")
        if hid not in cal:
            errors.append(f"override[{i}] holiday={hid!r} 不在 holidays.toml")
            continue
        sc, wt = scene_list(ov)
        check_scenes(f"override[{hid}]", sc)
        if len(sc) != len(wt):
            errors.append(f"override[{hid}] scenes/weights 不等长")
        if not isinstance(ov.get("priority"), int):
            errors.append(f"override[{hid}] 没有 priority")
        for slot in ov.get("slots", SLOTS):
            if slot not in SLOTS:
                errors.append(f"override[{hid}] slots 里有 {slot!r}")
        if dates_of(ov) != cal_dates[hid]:
            diff = sorted(dates_of(ov) ^ cal_dates[hid])
            errors.append(f"override[{hid}] 日期和 holidays.toml 不一致：{diff[:4]}")

    for i, ev in enumerate(events):
        sc, wt = scene_list(ev)
        check_scenes(f"event[{i}]", sc)
        if len(sc) != len(wt):
            errors.append(f"event[{i}] scenes/weights 不等长")
        c = ev.get("chance")
        if not isinstance(c, (int, float)) or not (0.03 <= c <= 0.12):
            errors.append(f"event[{i}] chance={c!r} 不在 0.03-0.12")
        for key in ev.get("conditions", {}):
            if key not in COND_KEYS:
                errors.append(f"event[{i}] 未知 condition {key!r}")

    # ---- 结构：池子 vs 固定槽位 ----
    fixed_set = set(fixed_scenes)
    pool_set: set[str] = set()
    for pool in pools:
        pool_set |= set(scene_list(pool)[0])
    daily = known - set(SPECIAL) - FALLBACK
    if pool_set & fixed_set:
        errors.append(f"池子和固定槽位重叠：{sorted(pool_set & fixed_set)}")
    if daily - fixed_set - pool_set:
        errors.append(f"日常场景既不在槽位也不在池子：{sorted(daily - fixed_set - pool_set)}")

    # ---- 每个节日都有覆盖条目；每个专用场景都有规则能到 ----
    ov_ids = {ov.get("holiday") for ov in overrides}
    if set(cal) - ov_ids:
        errors.append(f"holidays.toml 里这些日子没有 [[holidays]] 覆盖：{sorted(set(cal) - ov_ids)}")

    reachable_by_rule: set[str] = set(fixed_set) | pool_set
    for ov in overrides:
        reachable_by_rule |= set(scene_list(ov)[0])
    for ev in events:
        reachable_by_rule |= set(scene_list(ev)[0])
    if set(SPECIAL) - reachable_by_rule:
        errors.append(f"这些专用场景没有任何规则能到达：{sorted(set(SPECIAL) - reachable_by_rule)}")

    # ---- 槽位完整性 ----
    slot_index: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    for s in slots:
        slot_index[(s["day"], s["slot"])].append(s)
    for d in DAYS:
        for sl in SLOTS:
            if (d, sl) not in slot_index:
                errors.append(f"槽位缺 {d}/{sl}")

    p("\n== 1. scene id / 结构校验 ==")
    p("  被引用但 scenes.toml 里没有的 id：", missing_scene if missing_scene else "无 ✓")
    p(f"  固定槽位 {len(fixed_set)} 个场景；随机池 {len(pool_set)} 个；重叠 {len(pool_set & fixed_set)} 个（应为 0）")
    p(f"  日常场景 {len(daily)} = 槽位日常 {len(fixed_set & daily)} + 池子 {len(pool_set)}"
      f"（池子只放日常：{pool_set <= daily}）")
    p(f"  事件/节日专用 {len(SPECIAL)} 个；兜底 {len(FALLBACK)} 个（{', '.join(sorted(FALLBACK))}）")
    p(f"  规则上可到达 {len(reachable_by_rule)}/{len(known)}；除 sky 外全覆盖={reachable_by_rule == known - FALLBACK}")
    if errors:
        p("\n== ERRORS ==")
        for e in errors:
            p("  ✗", e)
        die("数据校验没过，先修上面的问题")
    p("  结构校验：全部通过 ✓")

    # -------------------------------------------------------------------
    # 全年模拟（2026-01-01 .. 2026-12-31，逐日）
    # -------------------------------------------------------------------
    rng = random.Random(20260101)
    weather_pool = ["clear", "cloudy", "rain", "snow"]
    weather_w = [0.50, 0.27, 0.18, 0.05]

    cal_by_date: dict[dt.date, set[str]] = collections.defaultdict(set)
    for hid, ds in cal_dates.items():
        for day in ds:
            cal_by_date[day].add(hid)
    ov_by_date: dict[dt.date, list[dict]] = collections.defaultdict(list)
    for i, ov in enumerate(overrides):
        for day in dates_of(ov):
            ov_by_date[day].append({**ov, "_i": i})
    for day in ov_by_date:
        ov_by_date[day].sort(key=lambda o: (-o["priority"], o["_i"]))

    pool_by_slot = {pool["slot"]: pool for pool in pools}

    sample_dates = [
        dt.date(2026, 1, 5),    # 周一
        dt.date(2026, 1, 10),   # 周六
        dt.date(2026, 1, 1),    # 元日
        dt.date(2026, 7, 7),    # 七夕
        dt.date(2026, 12, 24),  # クリスマスイブ
    ]
    sample_picks: dict[dt.date, list[tuple[str, str, str, str]]] = {}
    weather_of: dict[dt.date, str] = {}

    def call(day: dt.date, slot: str, weather: str) -> tuple[str, str, str]:
        ctx = {
            "season": SEASON[day.month],
            "weather": weather,
            "holiday": cal_by_date.get(day, set()),
            "weekday": "weekend" if day.weekday() >= 5 else "weekday",
            "slot": slot,
        }
        # 1. 节日覆盖（priority 从大到小，窗口期 chance 没中就继续看下一条）
        for ov in ov_by_date.get(day, ()):
            if slot not in ov.get("slots", SLOTS):
                continue
            if rng.random() < ov.get("chance", 1.0):
                sc, wt = scene_list(ov)
                return pick(rng, sc, wt), "holiday", ov["holiday"]
        # 2. 事件（文件顺序=优先级）
        for i, ev in enumerate(events):
            ok = True
            for key, val in ev.get("conditions", {}).items():
                vals = val if isinstance(val, list) else [val]
                actual = ctx[key]
                if isinstance(actual, set):
                    if not any(v in actual for v in vals):
                        ok = False
                        break
                elif actual not in vals:
                    ok = False
                    break
            if not ok:
                continue
            if rng.random() < ev["chance"]:
                sc, wt = scene_list(ev)
                return pick(rng, sc, wt), "event", str(i)
        # 3. 固定槽位
        cands = slot_index[(DAYS[day.weekday()], slot)]
        scene = pick(rng, [c["scene"] for c in cands], [c["weight"] for c in cands])
        # 4. 随机池：中签就覆盖第 3 步
        pool = pool_by_slot.get(slot) or pool_by_slot.get("any")
        if pool and rng.random() < pool["chance"]:
            sc, wt = scene_list(pool)
            return pick(rng, sc, wt), "pool", str(pool["slot"])
        return scene, "slot", "-"

    reached: collections.Counter[str] = collections.Counter()
    drivers: collections.Counter[str] = collections.Counter()
    holiday_hits: collections.Counter[str] = collections.Counter()
    event_hits: collections.Counter[int] = collections.Counter()
    total = 0
    day = dt.date(2026, 1, 1)
    last = dt.date(2026, 12, 31)
    while day <= last:
        weather = rng.choices(weather_pool, weights=weather_w, k=1)[0]
        weather_of[day] = weather
        rows = []
        for slot in SLOTS:
            scene, driver, tag = call(day, slot, weather)
            total += 1
            reached[scene] += 1
            drivers[driver] += 1
            if driver == "holiday":
                holiday_hits[tag] += 1
            elif driver == "event":
                event_hits[int(tag)] += 1
            rows.append((slot, scene, driver, tag))
        if day in sample_dates:
            sample_picks[day] = rows
        day += dt.timedelta(days=1)

    p("\n== 2. 全年模拟（2026-01-01 .. 2026-12-31，逐日，5 时段）==")
    p(f"  通话次数 {total}（365 天 x 5 时段）")
    p(f"  到达过的场景 {len(reached)}/{len(known)}")
    daily_reached = daily & set(reached)
    special_reached = set(SPECIAL) & set(reached)
    p(f"  日常场景 {len(daily_reached)}/{len(daily)}；事件/节日专用 {len(special_reached)}/{len(SPECIAL)}；"
      f"兜底 {len(FALLBACK & set(reached))}/{len(FALLBACK)}（sky 不参与随机）")
    never = sorted(known - set(reached))
    p(f"  一年里一次都没到的：{never if never else '无 ✓'}")

    p("\n  驱动来源：")
    for drv, label in (("holiday", "节日覆盖"), ("event", "事件"), ("slot", "固定槽位"), ("pool", "随机池")):
        c = drivers[drv]
        p(f"    {label:<6} {c:5d}  {100.0 * c / total:5.1f}%")
    p(f"  节日驱动占比 = {100.0 * drivers['holiday'] / total:.2f}%（{drivers['holiday']} 次）")

    p("\n  前 10 场景：")
    for i, (sid, c) in enumerate(reached.most_common(10), 1):
        p(f"    {i:2d}. {sid:<18} {name[sid]:<10} {c:4d}  {100.0 * c / total:5.1f}%")

    p("\n  节日命中明细（holidays.toml id）：")
    for hid, c in holiday_hits.most_common():
        p(f"    {hid:<26} {cal[hid]['name']:<10} {c:4d}")
    miss_holiday = sorted(set(cal) - set(holiday_hits))
    p(f"  一年里没被任何通话命中的节日：{miss_holiday if miss_holiday else '无 ✓'}")

    p("\n  事件命中次数：")
    for i, ev in enumerate(events):
        sc, _ = scene_list(ev)
        label = sc[0] if len(sc) == 1 else "/".join(sc)
        cond = ", ".join(
            f"{k}={'/'.join(v) if isinstance(v, list) else v}" for k, v in ev.get("conditions", {}).items()
        )
        p(f"    event[{i:2d}] {ev['chance']:.2f}  {label:<34} {event_hits[i]:4d}  {cond or '-'}")

    # -------------------------------------------------------------------
    # 样例日（取上面全年那次真实结果）
    # -------------------------------------------------------------------
    p("\n== 3. 五个样例日（取全年那次真实结果，每格 = 场景(驱动)）==")
    p("  驱动：H=节日覆盖  E=事件  S=固定槽位  P=随机池")
    letter = {"holiday": "H", "event": "E", "slot": "S", "pool": "P"}
    for day in sample_dates:
        hids = sorted(cal_by_date.get(day, ()))
        label = ", ".join(cal[h]["name"] for h in hids) if hids else "（平日）"
        p(f"\n  {day.isoformat()}  {DAYS[day.weekday()]}  {weather_of[day]:<7} 日历：{label}")
        for slot, scene, driver, tag in sample_picks[day]:
            mark = letter[driver]
            if driver == "holiday":
                mark += f":{tag}"
            elif driver == "event":
                mark += f" #{tag}"
            elif driver == "pool":
                mark += f":{tag}"
            p(f"    {slot:<9} {scene:<20} {name[scene]:<12} {mark}")

    p("\n== 4. 结论 ==")
    ok_daily = daily <= set(reached)
    p(f"  日常场景全部可达：{ok_daily}（{len(daily_reached)}/{len(daily)}）")
    p(f"  84 条里除 sky 外全部可达：{known - FALLBACK <= set(reached)}")
    p(f"  errors: {errors if errors else '无 ✓'}")
    flush()
    sys.exit(0 if ok_daily and known - FALLBACK <= set(reached) else 1)


if __name__ == "__main__":
    main()
