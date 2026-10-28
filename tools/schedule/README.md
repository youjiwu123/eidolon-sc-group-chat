# 作息工具（可选）

仓库里带 29 份作息草案（`characters/schedules/*.week.draft.toml`）。这个目录里的脚本只做
**校验、模拟和渲染**，不生成草案本身——草案是拿 `characters/schedules/*.stats.json` 和剧情摘要
人工整理出来的，生成流水线不在仓库里。

## 用法

在仓库根目录：

```sh
python tools/schedule/simulate.py        # 校验 + 跑一遍 2026 全年，打印分布
python tools/schedule/calendar_2026.py   # 生成 characters/schedules.mano.2026.{md,html}
```

需要 Python 3.11+（`tomllib`）。不需要联网、不需要模型、不需要 `.env`。

`simulate.py` 会在同目录写一份 `simulate.report.txt`（已在 `.gitignore` 里）。

## 它读什么

| 文件 | 用途 |
|---|---|
| `characters/scenes.toml` | 场景表（84 条），校验引用的 scene id，并给出名字 |
| `characters/holidays.toml` | 节日表，校验覆盖与日期镜像 |
| `characters/schedules.mano.week.draft.toml` | 用来校验的那份最全的作息（有 slots / pools / events / holidays） |

## 它检查什么

- 所有被引用的 `scene` id 都在场景表里；
- 槽位 / 池子 / 节日 / 事件的结构自洽（池子与固定槽位不重叠、日常场景一个不落）；
- `holidays.toml` 与作息文件里的日期镜像一致、每个节日都有覆盖条目；
- 按「节日 > 事件 > 槽位 > 池子」的顺序跑一遍全年 365 天 × 5 个时段，打印
  场景可达数、节日驱动占比、前 10 分布和事件/节日命中明细。

## 改自己的作息

写法见 `characters/schedules.model.md`，步骤见 `docs/deploy-fork.md` 第 9 节。
改完重启后端（`docker compose restart backend`）才会生效。
