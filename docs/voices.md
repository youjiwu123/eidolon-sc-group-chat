# SCSP 剧情原声台词库

`characters/voices.toml` 与 `characters/voices/` 的维护说明。表由
[`backend/scripts/build_voices.py`](../backend/scripts/build_voices.py) 生成；探索过程、失败分类和
选行依据见 `.scratch/voices/REPORT.md`。

## 1. 这是什么

392 条从 SCSP 剧情语音包（`root/raw/<story>.acb`）里切出来的角色台词。每条对应 ACB 里的一个
HCA subsong，转成单声道 mp3。

| 项 | 数值 |
|---|---|
| 条数 | 392 |
| `kind` | `quote` 100 / `birthday` 292 |
| 角色 | 29（`characters.toml` 里的全部偶像） |
| story / ACB | 180 个包 |
| 音频 | 392 个 mp3，约 24.2 MB（23.1 MiB），48 kHz 单声道；96 kbps（编码脚本对超过 200 KB 的会自动降到 48 kbps；当前没有触发） |
| 时长 | 合计约 33.4 分钟；中位 4.90 s，最短 0.38 s，最长 14.35 s |
| `subtitle` | 287/392 有民间汉化（`quote` 77/100，`birthday` 210/292）；105 条为空 |

文件布局：

```
characters/
  voices.toml                         # 索引（本页的主角）
  voices/<character>/<story>_<line>.mp3
  characters.toml                     # 角色 id / idol_id
```

音频文件名就是 `voices/<character>/<story>_<line>.mp3`，`voices.toml` 的 `audio` 字段是相对
`characters/` 的同一路径（和 `avatars/`、`backgrounds/` 的约定一致）。

**关于 102/290**：任务背景和旧报告写的是 `quote 102 / birthday 290`，那是并类修订前的历史数字。
2026-10-26 的修订把两条生日台词从 `quote` 改回 `birthday`：

- `hinana` / `s61_10123003_00` / `0010`
- `haruki` / `s61_10128002_00` / `0030`

所以**以 `voices.toml` 里实际的 `kind` 为准：100/292**。`voices.toml` 顶部注释如果还写着
102/290，那是旧表头；`emit` 会按实际数据重写表头。

## 2. `voices.toml` 字段

每条 `[[line]]`：

| 字段 | 类型 | 含义 |
|---|---|---|
| `character` | string | 仓库角色 id（`characters.toml` 的 `id`），如 `mano` |
| `story` | string | SCSP 剧本包 id，对应 `root/raw/<story>.acb`（实际文件名可能不带 `_00`，见 §4.2） |
| `line` | string（4 位） | 剧本行号；同 story 内唯一，排序用 `int(line)` |
| `text` | string | 日文剧本原文；保留原作换行，TOML 里写作 `\n` |
| `subtitle` | string | 民间汉化中文；没有时为空串（见 §6.1） |
| `audio` | string | 相对 `characters/` 的 mp3 路径 |
| `seconds` | float | mp3 的真实时长（ffprobe），用于排序/占位/字幕节拍 |
| `kind` | string | `quote` = 口癖/名台词；`birthday` = 制作人生日祝贺 |

`emit` 的排序是：`characters.toml` 的角色顺序 → `quote` 在 `birthday` 前 → `story` → `line`。
当前表里有两处 `story` 顺序相反，`emit` 会把受影响的 14 行搬回正常位置（内容不变，只是顺序）。

## 3. cue 名 ↔ 剧本行号 ↔ 角色码

完整 cue 名（也就是 vgmstream 的 `stream name`）的格式：

```
<story>_<line4>_<code2><romaji>
s01_02010000_05_0180_05mamimi
└──── story ────┘ └line┘ └code┘└romaji┘
```

- `line4`：剧本行号，和剧本 JSON key 的后缀 / storylog 记录里的行号一致；
- `code2`：角色码，正常情况下等于 `characters.toml` 的 `idol_id`（mamimi = 05）；
- `romaji`：角色 id（`mamimi`）。角色归属以它为准。

真实例子：`mamimi` 在 `s01_02010000_05` 的 `0180` 行。

`characters/voices.toml` 里的记录（`subtitle` 来自民间汉化）：

```toml
[[line]]
character = "mamimi"
story = "s01_02010000_05"
line = "0180"
text = "んー\n……じゃ、やりますかぁ"
subtitle = "嗯——\n……那，继续吧"
audio = "voices/mamimi/s01_02010000_05_0180.mp3"
seconds = 5.23
kind = "quote"
```

资源库对这条 cue 的索引是：

```json
{"cue_index": 9, "cue_name": "s01_02010000_05_0180_05mamimi",
 "characters": [{"id": "05", "name": "田中 摩美々"}]}
```

ACB 里同一句的实际位置（`vgmstream-cli -m -s 0 -S 0` 的节选）：

```text
stream index: 7
stream name: s01_02010000_05_0180_05mamimi
play duration: 249543 samples (0:05.199 seconds)

stream index: 10
stream name: s01_02010000_05_0130_06sakuya
play duration: 174854 samples (0:03.643 seconds)
```

所以正确的 `?s.wav` 是 **`7.wav`**，不是 `cue_index + 1 = 10.wav`。本次验收实际切了这一个 ACB：

```text
$ python backend/scripts/build_voices.py decode --work .scratch/voices-port/final \
    --acb-dir .scratch/voices/acb --wav-dir .scratch/voices-port/final/wav \
    --story s01_02010000_05 --force
  s01_02010000_05         16 streams   1 条  mamimi/0180→7

7.wav  = 5.198813 s            # 正确的 mamimi 句
10.wav = 3.642792 s            # 用 cue_index+1 会切到的 sakuya 句
mp3    = 5.232 s               # 7.wav 编码后，属于正常的 mp3 编码延迟
```

并且重建出的 mp3 与仓库里已有的
`characters/voices/mamimi/s01_02010000_05_0180.mp3` **SHA256 完全相同**（`5786C38B…9EF3D`），
说明 stream name → wav → mp3 这条链是可复现的。

## 4. 两个必须知道的坑

### 4.1 `cue_index` 不是 subsong 序号

资源库的 `cue_index` 只是它自己索引里的序号，**不是 ACB 的 stream 顺序**。180 个用到的包里
26 个不能靠它定位：

- **18 个包真的错位**。上例 `mamimi 0180` 的 `cue_index=9`，实际是第 7 条 stream；
  `s01_02010000_05` 本身是 16 条 stream 对 16 条库 cue，没有多余流。
- **8 个单 subsong 包连 `stream index` 都不打印**（只有一个 `stream name`），例如
  `s06_02070000_01`。按索引写的代码会把它们判成「没有 stream」。

正确做法只有一个：`vgmstream-cli -m -s 0 -S 0 <acb>` 打印的 `stream name` 就是完整 cue 名，
拿它和 target 的 cue 名做**精确字符串匹配**。`-o ?s.wav` 的 `?s` 从 1 开始，数值上等于
`stream index`，不是 `cue_index`。本脚本的 `decode` 完全不读 `cue_index`。

规模核对（`check --deep` 实测）：180/180 个包里，库中的每个 cue 名都能在 ACB 的 stream name
里找到；1592 条库 cue 对 1601 条实际 stream。差额 9 条来自 `s43_02010000_00`：28 个 cue 名
对应 37 条 stream，多出的 9 条都是 `92multi` 同名重复流（多人齐声）。另有 8 个单 subsong 包
不打印 `stream index`，但每个仍只有 1 条 stream，按名匹配正常。`92multi` 不是仓库角色，未入表；
若以后要收多人齐声，需要另定规则（同名 stream 无法唯一定位）。

### 4.2 ACB 命名不统一

同一个 story id，资源库里的 ACB 文件名有两种写法：

```text
s01_01010000_00  ->  root/raw/s01_01010000_00.acb
s61_10101001_00  ->  root/raw/s61_10101001.acb      # 少了末尾 _00
```

`build_voices.py` 里的 `Library.resolve_bank()` 三级兜底，顺序固定：

1. `root/raw/<story>.acb`
2. `root/raw/<story 去掉末尾 _00>.acb`
3. `GET /api/resources?q=<去掉 _00>&category=audio_story` 搜索

第 3 步的查询词必须用去掉 `_00` 的前缀，否则 `s61_10101001_00` 搜不到
`s61_10101001.acb`（服务端是前缀匹配）。

### 4.3 124 个 story 的剧本 JSON 不在资源库里

探索时资源库对 **124 个 story** 不提供 `root/raw/<story>.json`（只有 asset/storylog）；
`.scratch/corpus/scsp_storylogs/<story>_storylog.bytes` 里的记录自带 cue 名和台词，靠它补齐了
123 个 story 的文本，A 批命中才从 87 涨到 113。**补文本时如果只读 `scsp_raw/*.json`，这些行
会整批漏掉。**

当前本地 `.scratch/corpus/scsp_raw/` 有 131 个 story 的 JSON，仍缺 49 个；这 49 个都有
storylog，也正好是 §6.1 里 `subtitle` 为空的 49 个 story。`check` / `emit` 不依赖这些导出；
只有重新选行时才会用到，见 REPORT。

## 5. 怎么增补

前置：本地资源库 `http://127.0.0.1:8891` 已启动；vgmstream 和 ffmpeg 路径见 §7。默认工作目录
是 `.scratch/voices-build`（可随手改 `--work`），已有 `.scratch/voices/acb/` 时可以加
`--acb-dir .scratch/voices/acb` 复用，不必重下。

1. 找到目标行：`story`、4 位 `line`、`character`。行号来自剧本 JSON key 的后缀；没有 JSON 的
   story 从 storylog 的 cue 名取。**不要用 `cue_index` 猜。**
2. 在 `characters/voices.toml` 追加一条 `[[line]]`。`text` 写日文原文（换行写 `\n`），
   `subtitle` 有民间汉化就填、没有留空，`kind` 按用途写。`audio` 先写规范路径
   `voices/<character>/<story>_<line>.mp3`，`seconds` 先写 `0.0`；`encode`/`emit` 会重算。
3. 跑：

```powershell
python backend/scripts/build_voices.py targets --story <story>
python backend/scripts/build_voices.py fetch   --story <story> --acb-dir .scratch/voices/acb
python backend/scripts/build_voices.py decode  --story <story> --acb-dir .scratch/voices/acb
python backend/scripts/build_voices.py encode  --story <story>
python backend/scripts/build_voices.py emit
python backend/scripts/build_voices.py check --deep
```

- `targets` 会把整表读回来并在库里核对 cue 名；`--story` 只影响本次目标，但 `targets.json`
  会写成过滤后的子集。之后如果再加行，**重新跑 targets**。
- `decode` 默认不覆盖已有 wav；`encode` 默认跳过已有非空 mp3，要重编就加 `--force`。
- `emit` 重写整张表（会补 `seconds`、`audio`、表头统计并重排）；提交前 review diff。
- 新增角色：先在 `characters/characters.toml` 加 `[[characters]]`（至少 `id`、`idol_id`），
  再按上面的流程加行。cue 名尾部的 romaji 必须等于 `id`；角色码一般等于 `idol_id`，`hazuki`
  是唯一例外（cue 90 / idol_id 91）。
- 生日彩蛋：s61 每个角色一个 block（2–3 个 story，6–12 句）。选 block 的规则见 REPORT
  §1 的 B 批；本工具不再重跑 persona/corpus 的匹配，只负责把已选好的行切成音频。

全量重建（一般不需要；会重下缺失 ACB、重切所有 story；已有 mp3 默认复用，`--force` 才重编）：

```powershell
python backend/scripts/build_voices.py build --work .scratch/voices-build --acb-dir .scratch/voices/acb
```

## 6. 已知限制

### 6.1 `subtitle` 是民间汉化，不是官方中译

- 来源：本地汉化库 `D:\xue\SONGforPRISM\scsp_localify\scenario\`（按
  `sXX/NNNNNNNN/<story>.json` 存放）；**不在仓库里**，也不是官方文本。
- 覆盖率：392 条里 287 条有中文（`quote` 77/100，`birthday` 210/292）。空的 105 条分布在 49 个
  story：主要是 19 个 `s44_*` 和 28 个 `s61_*_0003_00`，另有 `s42_01250100_04`、
  `s43_02030000_99`。这 49 个 story 在汉化库里没有文件；它们同时也没有本地剧本 JSON（见 §4.3）。
- 本流水线**不生成、不校验翻译**；`check` 只验证字幕字段是字符串，不验证译文质量。要补空字幕，
  得另找汉化/翻译来源，不能拿现有中文当官方台词用。

### 6.2 没有做 STT 听写核对

没有可用的 ASR 凭据/服务，392 条没有逐条听写。替代的客观校验：

- `check --deep`：每条 mp3 对应的 ACB stream 时长与 ffprobe 时长相差 **最大 0.052 s**（392/392），
  错位会明显偏离；
- 探索阶段统计：音频时长与台词字数（去换行）的 Pearson 相关 = 0.861（n=392）；
- 抽查过 `mamimi`、`hinana`、`sakuya` 等条目（见 REPORT §5 和本文 §3）。

发版前仍建议人工抽听，尤其是最长/最短和跨角色对话附近的条目。

### 6.3 生日是「每角色一个 block」，不是一话

s61 每个 ACB 只有 4 个 cue，一位角色的完整生日祝贺横跨 2–3 个 story，每个角色取了 cue 最多的
那个 block（6–12 句）。前端要「一话」的演出感，需要自己截取或按 `story`/`line` 分组；表里没有
「第几话」字段。

### 6.4 其他

- 同一 `(story, line)` 只保留一条；persona 的 quote 与生日行重合时 `quote` 优先（历史上合并了
  14 条）。同一条台词在多个 story 出现时取第一处，不保留不同语气版本。
- `text` 保留原作 `\n`、空格和标点，没有清洗；可能和音频有细微出入（探索期手工改过的文本会
  被精确匹配挡掉）。
- A 批的 303 条 persona quote 里，184 条在语料里没有逐字出现（`no_corpus_match`），6 条落到了
  别的角色（`cue_other_character`），都没有入表；这是宁可漏不可错。
- `92multi`（多人齐声）和 `93shacho`（天井社长）不是仓库角色，排除。
- `emit` 的确定性顺序会把当前表里 14 行搬位置（两处 story 顺序反了），内容不变。

## 7. 校验与依赖

只读校验（不下载、不写表、不写 mp3）：

```powershell
python backend/scripts/build_voices.py check --deep
```

本次实测输出（当前表）：

```text
读取 characters/voices.toml：392 条（quote 100 / birthday 292），29 位角色，180 个 story

[1/5] 字段/路径        392/392
[2/5] 音频文件         392/392
[3/5] 时长/seconds    392/392
[4/5] cue 名映射       392/392
[5/5] 重复 (story,line) 0 条
      角色码            392/392 已核对（378 与 idol_id 一致；14 条已知例外：hazuki cue=90 / idol_id=91）

深度校验（--deep，按 vgmstream stream name）
  ACB 可读             180 个（缺 0 个）
  库内 cue 全覆盖      180/180 个 ACB
  目标 cue 唯一命中    392/392
  stream 时长 ≈ mp3    392/392（最大差 0.052s）

392/392 条通过
```

`--check` 是 `check` 的别名，所以 `python backend/scripts/build_voices.py --check --deep` 也可以。
`--fast` 跳过 ffprobe（只做结构和 cue 校验）。

依赖：

| 依赖 | 默认值 | 覆盖方式 |
|---|---|---|
| 本地资源库 | `http://127.0.0.1:8891` | `--api` / `EIDOLON_SCSP_API` |
| vgmstream | `D:\SCSPDownloader\SCSPDownloader\tools\vgmstream\r2117\vgmstream-cli.exe` | `--vgmstream` / `EIDOLON_VGMSTREAM` |
| ffmpeg | `D:\MOZA Pit House\bin\ffmpeg.exe` | `--ffmpeg` / `EIDOLON_FFMPEG` |
| ffprobe | 同目录 `ffprobe.exe` | `--ffprobe` / `EIDOLON_FFPROBE` |

资源库起不来时，`targets` / `fetch` / `check` 会直接报「本地资源库 … 连不上」并退出；不会静默
用旧数据。`check` 会读 `.scratch/voices/` 下的 `bank_ids.json`、`banks/` 缓存（只读），没有缓存
时走 API。

详细探索记录：`.scratch/voices/REPORT.md`。
