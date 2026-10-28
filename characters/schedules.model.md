# 一次通话怎么挑背景（schedules.model.md）

按下面的顺序定她身后那张背景，前一步命中就不再看后面的。

1. **节日覆盖**（`schedules.mano.week.draft.toml` 的 `[[holidays]]`）
   日期落在某条的 `dates`/`ranges`（只有一天/一段时可以写 `date`/`range`）里、当前时段也在它的 `slots` 里
   就算候选；按 `priority` 从大到小过，每条过自己的 `chance`（默认 1.0），命中就按 `scenes`/`weights`
   加权抽一个。窗口期节日 chance 没中，就继续看下一条覆盖同一天的节日。日历本体在 `characters/holidays.toml`。
2. **事件**（`[[events]]`）：按文件顺序逐条看 `conditions`，全部命中才 roll 它的 `chance`，第一次成功即采用。
   所以**文件顺序就是优先级**，节日专属的事件排在最前面。
3. **固定槽位**（`[[slots]]`）：用星期几 + 时段找到候选，按 `weight` 加权抽一个。
4. **随机池**（`[[pools]]`）：最后一步，roll 一次 `chance` 决定「这一天要不要不按作息走」，命中就用池子里的
   地点**替换**第 3 步的结果。`slot` 更具体的池子优先（夜里的 `night` 池压过 `any` 池）。

## 字段

- `day`：`mon`..`sun`（槽位）/ `any`（池子）。`slot`：`morning`(6-10)、`noon`(10-14)、`afternoon`(14-18)、
  `evening`(18-22)、`night`(22-2)。`night` 跨零点，日期取这一段**开始**的那天：1 月 1 日 00:30 的电话
  走的是 12-31 的 night（大晦日/初詣的深夜参拜），不是元旦的白天。
- `weight`：同一格里的相对权重，不是概率。`chance`：0-1 的概率，每次通话 roll 一次。
- `priority`：节日之间的强弱，越大越先。100 元日 / 95 初詣 / 90 公休 / 85 振替・国民の休日 /
  80 大晦日・圣诞 / 70 花見・お盆・夏祭り / 65 GW / 60 七夕・紅葉狩り・万圣节 / 55 節分・雏祭・情人节。
- `scenes` + `weights`：候选地点与权重，id 必须来自 `characters/scenes.toml` 的 84 条；`scene` 是单候选简写。
- `conditions`：`season` = spring(3-5)/summer(6-8)/autumn(9-11)/winter(12-2)；`weather` = clear/cloudy/rain/snow
  （真实天气或调用时传入）；`holiday` = `holidays.toml` 的 id；`weekday` = weekday/weekend；`slot` = 上面五段。
  值是数组时命中任一即可，多个键之间是 AND。
- `activity`：这一格她在做什么，进提示词。`why`：出处/推断说明，给人看，不进提示词。
- 节日条目的 `dates`/`ranges` 是 `holidays.toml` 的镜像，改日期只改 `holidays.toml`；
  `.scratch/schedule/simulate.py` 会断言两边一致，并跑 365 天（2026 全年）打印可达数、分布、节日占比。

## 时区

一律 **Asia/Tokyo**（`[calendar].timezone`）。日本没有夏令时，所以全年是固定的 +09:00。

## 场景分桶（84 条）

- **日常 69** = 固定槽位 32 + 随机池 37，两边不重叠、一个不落（校验脚本断言）。
- **事件/节日专用 14**：stage、backstage（演出）、banquet（宴会）、beach（远行）、flower_field、cherry、
  ginkgo（季节限定）、hospital_corridor、exam_room（生病）、hall（学园祭/合唱祭）、izakaya、bar（未成年，
  只在忘年会里喝ウーロン茶）、airport（出远门）、bowling（要专门约）。不进池子，只在事件/节日里出现。
- **兜底 1**：`sky`（说不准），判断模型挑不出地点时用，不参与随机。
