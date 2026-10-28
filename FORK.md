# eidolon-sc 定制版（fork）说明

这是 [Sallyn0225/eidolon-sc](https://github.com/Sallyn0225/eidolon-sc) 的一个定制版本，基线是上游 `8a31a35`（PR #162 的合并点），在其上加了群聊、特殊档、地点、记忆等一整套功能，并做了本地化配置。

本副本已经去掉个人内容：`.scratch/`（研究与实验记录）、`.env`（密钥）、`certs/`（证书私钥）、`backups/`（用户数据库备份）、`corpus/`（原始语料，约 3 GB）、特殊档内容、语音原声切片。

## 这个版本多了什么

| 模块 | 内容 |
|---|---|
| 群聊 | 多角色群聊、邀请/改名、判断谁接话、流式逐条回复、常开自聊、群语音房、群通话 |
| 群聊细节 | 特殊档按人隔离、读心只在角色声明过时生效、群地点、群记忆、回复中按 Enter 插话 |
| 特殊档 | 每角色开关、任意好感档生效、后台按模式分格新建/编辑/删除、删模式清开关 |
| 好感度 | 六档提示词、后台按档编辑与新建档、好感锁（锁定后不增不减、不主动结束）、礼物与冷却 |
| 地点/场景 | 84 个场景、按角色的作息表、对话里说定就换场景、页首手动选地点（只作用当前对话）、场景背景图（手动选的、说定搬过去的、按作息算出来的都铺）、群地点 |
| 记忆 | 每回合后台提取、向量检索与重排阈值、取代链、跨角色共享、群聊也记、情绪激烈的事件也记且写得详细、可删除/清空 |
| 对话格式 | `（）`/`()` 写动作和心声、`“”`/`""` 写内心想法；只有设定或特殊档里声明过读心的角色能读到；`（）` 会显示也会朗读 |
| 语音/通话 | 通话 TTS、情绪判断、`（）` 心声显示并朗读、气泡旁「原声」、语音房（导航里的「名台词」页已移除） |
| 剧情回放 | 按路线、活动、特别企划、卡面（按角色）、主页营业、SCSP 分区回放剧情文本 |
| 生日彩蛋 | 制作人生日那天，一位角色送上一段生日祝福（音频来自原声表） |
| 搭话 / 开场白 | 每位角色会定时来搭话；29 人各有落地页招呼和通话开场白 |
| 后台 | 角色/特殊/好感三类提示词在线编辑、用户与好感管理、配置页 |
| 立绘与外观 | 对话页右下角常驻的小立绘（点一下有反应、外观里可关）、通话层立绘、外观设置 |
| 角色内容 | 29 位角色设定卡（每人 4–7k 字）、剧情提炼语料、作息表、场景表 |

## 数据与素材（重要）

| 资源 | 位置 | 本版本是否包含 | 说明 |
|---|---|---|---|
| 场景图 ×84 | `characters/scenes/` | ✅ 9.5 MB | **未被 git 跟踪**：发布/克隆后请确认它们被提交，否则页首与聊天背景没有图 |
| 角色背景图 ×30 | `characters/backgrounds/` | ✅ 3.2 MB | 已跟踪 |
| 头像 ×29 | `characters/avatars/`、`avatars-scsp/` | ✅ 0.4 MB | 已跟踪 |
| 剧情语料 | `characters/story/` | ✅ 6.3 MB | 1589 个文件，可删（删了剧情页没有内容） |
| 作息表 | `characters/schedules/`（29 份草案）+ `schedules.mano.*` | ✅ | 每天 5 个时段 × 每格 2 个候选（场景 + activity + 权重）；没有它「现在」只能回落到行为兜底 |
| 场景表 | `characters/scenes.toml` | ✅ | 场景名、hint 和图片文件名；图在 `characters/scenes/` |
| 礼物图 / 音效 | `frontend/public/gifts/`、`sounds/` | ✅ 0.6 MB | |
| 语音原声 | `characters/voices/` + `characters/voices.toml` | ❌（约 23 MB） | 台词/生日祝福的 mp3。导航里的「名台词」页已从这个版本移除；气泡旁的「原声」和生日语音仍然保留，前提是部署里放回这份数据；**不影响通话**（通话用部署者自己的 TTS key） |
| Live2D 立绘 | `corpus/stand/` | ❌（约 3 GB） | 用 `deploy/stand-sync.sh` 拉取，并在 `.env` 配 `EIDOLON_STAND_ASSETS_URL`；不配时只有背景图，没有立绘 |

## 成人向内容开关（部署者级）

这是**部署者**的开关，不是用户设置，页面上没有前端入口，也不按用户或角色单独设置。

- **关掉它**：`.env` 里写 `EIDOLON_EXPLICIT_CONTENT=0`（`1` 是打开）。
  `.env.example` 里已经默认写成 `0` 并带注释；**代码在不写这一项时按打开处理**——`docs/explicit.md` 写的是「默认关」，与当前代码不一致；在意的话请显式写 `0`。
- **后台覆盖**：管理员也可以 `PUT /api/admin/config/explicit_content`，请求体 `{"enabled": false}`；
  覆盖值存在 `config_overrides` 表里，优先级高于 `.env`，在后台恢复这一项后重新按 `.env` 生效。
- **年龄闸门（当前有已知问题）**：设计上 `characters.toml` 里 `age` 缺失或未满 18 的角色不产生任何相关提示词，
  但**当前代码只拦 `age < 1`**（`backend/src/eidolon/explicit.py`），所以 29 位角色里 17 位未满 18 岁这件事它拦不住。
  对应的 `backend/tests/test_explicit.py` 有 4 条测试因此是红的。
- **生效范围**：文字回合、通话回合、搭话都走同一个 `_prompt`，开关对三条路都生效；**群聊提示词不经过这个开关**。
- **照片**始终只有全年龄内容（ADR-0023），开关打开也不会改变生图内容。

在意的话，请在部署时自己设 `EIDOLON_EXPLICIT_CONTENT=0`，或者用后台那条接口关掉；本版本没有替你改这几处代码。

## 部署

1. `cp .env.example .env`，至少填对话模型（及判断/重排/TTS，按需）。
2. `docker compose up -d --build`。前端构建要访问 Google Fonts；构建机访问不了时用
   `docker build --network=host -t eidolon-sc-main-frontend:latest frontend`。
3. 手机要用麦克风时走 HTTPS：生成证书（`scripts/make-lan-cert.py`，或 `tailscale cert`），
   再 `docker compose --profile https up -d`。
4. 开发登录默认关闭。要开后门才设 `EIDOLON_DEV_LOGIN=1`，并把 `EIDOLON_ADMINS` 写成
   `github:<开发登录用的名字>`；**公网部署不要开**。

## 关于特殊档

本版本**不带**任何特殊档：`characters/modes.toml` 已移除（代码、接口、后台都保留）。
后台「特殊提示词」里可以自己新建，每条只有名字 / 说明 / 提示词三个字段，保存后按角色开关生效
（所有好感档都生效）。测试在文件缺失时会跳过对应断言。

## 与上游同步

```sh
git remote add upstream https://github.com/Sallyn0225/eidolon-sc.git
git fetch upstream
git rebase upstream/main
```

冲突通常集中在 `backend/src/eidolon/app.py`、`engine.py`、`frontend/src/components/conversations/`。

## 版权与使用

角色、剧情、语音、立绘等素材的版权属于 Bandai Namco Entertainment / 原作方，本仓库仅用于个人学习与自用部署，请勿商用或再分发素材。代码沿用上游的 AGPL-3.0（见 `LICENSE`）。
