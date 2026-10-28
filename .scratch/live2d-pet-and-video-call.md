# 设计票：聊天角落立绘 + 通话「视频感」

## 背景

`corpus/stand` 里已有 8618 个 Spine 素材（2.8 GB，**spine 3.6.53**，与项目运行时同版本），
前端也已经有渲染能力，但只用在一个地方。

现有代码：

```
frontend/src/components/conversations/spineRuntime.ts   Spine 3.6 运行时
frontend/src/components/conversations/Stand.tsx         立绘组件
frontend/src/components/conversations/useStandOutfits.ts 换装清单
frontend/src/components/conversations/CallLayer.tsx     通话层（目前渲染立绘的地方）
backend: /api/characters 返回 stand.default_outfit
stands 服务：docker compose 里的 stands（宿主机 8765）
素材来源：corpus/stand/{outfits,source,thumbnails}
```

另外 `corpus/stand/imported/` 里有 20 个从 SC-Time 补来的造型（**尚未进 outfits 清单**）。

---

## 目标 1：聊天页角落的小人（半天）

**要什么**：对话页右下角（输入框上方）站一个小尺寸立绘，待机循环，
像桌面宠物；点一下有反应；她说话时切到说话状态。

| 项 | 决定 |
|---|---|
| 组件 | 新建 `ChatCompanion.tsx`，复用 `Stand.tsx` |
| 尺寸 | 宽约 110–130 px，高度按 spine 的 `height/width` 比例 |
| 位置 | 绝对定位，`right-4 bottom-24`（输入栏上方），移动端可改贴底 |
| 动画 | `idle` 循环；点击随机播一个 `reaction`；收到回复时播 `talk`（若有） |
| 遮罩 | 不挡输入；`pointer-events` 只在立绘本身 |
| 开关 | 设置 → 外观加一项「对话页显示立绘」（默认开），存本机 |
| 降级 | 素材 404 / WebGL 不可用时**整块不渲染**，不能留空白占位 |

**实现要点**

1. `Stand.tsx` 现在大概是按通话尺寸写的——先读它，抽出可传的 `width`/`height`/`scale` 参数，别复制代码
2. 动画名要从模型里读：加载后 `skeleton.data.animations` 里找 `idle`/`wait`/`stand`，找不到就用第一个
3. 只在对话页挂载；离开就销毁（Spine 播放器挺吃内存）
4. 页面隐藏（`document.hidden`）时暂停渲染，省电

**验收**

- 打开对话页，右下角出现她的小人，在动
- 点一下有反应动画
- 关掉设置项后消失
- 通话时它不出现（避免和通话层重复）
- 手机上不遮挡输入框、不引起滚动

---

## 目标 2：通话页「视频聊天」感（1–2 天）

**要什么**：通话时立绘占满屏幕（半身像），她的语音在播放时嘴在动，
表情跟着这句话的情绪变。

| 项 | 决定 |
|---|---|
| 布局 | 立绘贴底、高度约屏高 70–85%，上面留字幕区 |
| 口型 | 由 TTS 音频驱动：读音频音量包络，映射到 Spine 的嘴部参数/动画 |
| 表情 | 复用现有每条回复的情绪标记，切对应的面部动画 |
| 背景 | 先用现有通话背景；要做景深就模糊 + 压暗 |
| 降级 | 没有嘴部轨道时不做口型，只播待机 |

**实现要点（按风险排序）**

1. **先确认素材里有没有嘴部动画/参数**：读一个 `data.json`，
   在 `animations` 里找含 `mouth`/`lip`/`talk` 的名字，在 `skins`/`slots` 里找嘴的 `attachment`
   - 有 → 直接播
   - 没有 → 退而求其次：用 `slot` 的 attachment 交替切换（张嘴/闭嘴两张图）
2. **音频驱动**：`AudioContext` + `AnalyserNode` 取 `getByteTimeDomainData` 算 RMS，
   每帧（requestAnimationFrame）映射到 0–1，再设 Spine 参数或切动画
   - 注意：TTS 是 `<audio>` 播放，需要在用户手势后 resume AudioContext
3. **不要用 `setInterval`** 驱动，统一 `requestAnimationFrame`，页面隐藏时停
4. 通话结束时清理：停动画、断开 analyser、销毁 canvas

**验收**

- 通话时立绘明显变大、贴底，字幕不挡脸
- 她说话时嘴动，停顿时不张嘴
- 说完一句，表情回到待机
- 弱网/素材缺失时退回头像，不白屏

---

## 已知风险

| 风险 | 应对 |
|---|---|
| Spine 版本不匹配（素材 3.6.53） | 项目运行时已是 3.6，直接用；**不要**升级到 4.x |
| 立绘尺寸/锚点因模型而异 | 读 `skeleton.width/height` 归一化，别写死比例 |
| 手机 GPU 弱 | 小尺寸立绘用低分辨率纹理；通话页限制帧率 30 |
| 换装列表不含 `imported/` 的 20 个造型 | 本票不做；另开一张票补 `outfits/*.json` 与 `spine_manifest.json` |
| 通话层与角落小人重复渲染 | 路由判断：`/call` 下不渲染 `ChatCompanion` |

---

## 开工顺序

1. 读 `Stand.tsx` / `spineRuntime.ts` / `CallLayer.tsx`，确认参数化程度
2. 做目标 1（小、独立、能立刻看到效果）
3. 抽样检查素材的嘴部动画是否存在（决定目标 2 的做法）
4. 做目标 2 的布局，再加口型

## 相关文件

```
frontend/src/components/conversations/Stand.tsx
frontend/src/components/conversations/spineRuntime.ts
frontend/src/components/conversations/CallLayer.tsx
frontend/src/components/conversations/ConversationView.tsx   （挂 ChatCompanion 的地方）
frontend/src/components/settings/DisplaySettings.tsx          （加开关的地方）
corpus/stand/source/assets/spine/idols/stand/<enzaId>/        （素材）
```

---

## 目标 1：已完成（2026-10-25）

- 新组件 `ChatCompanion.tsx`，复用 `Stand`（取景 `full`）。宽 120px；高按载入后量出的整个人来定
  （`StandEngine.size` + `Stand` 的 `onMeasured`），换了衣装就按新的那套重算。`standAnimations` 里
  `wait` 缺失时依次退到 `idle`、`stand`、第一个动画，不再留下一条空的身体轨道。
- 挂在 `ConversationView` 消息区的右下角（那一块改成 `relative`），贴着输入栏上沿，`right-4`（手机 `right-2`）。
  只有画布收点击，底下照常点得到、竖向滚动照常（`touch-pan-y`），读屏里是一个「戳一下{角色名}」的按钮。
- 待机是 `CALM`（`wait` + `face_wait`）；点一下随机换 `happy` / `shy` / `surprised`，1.8 秒后回待机；
  她写完一条回复时嘴动一会儿（1.4 秒起、按字数加、最多 5 秒），她那条回复的「朗读」在放时也动嘴；
  她正在写回复时是 `thinking`。一直 `looking`（`eye_front`），冲着这个页面站着。
- 通话中（`layer` 不为 null，含收起后的通话条）和看历史对话时整块不渲染；页面隐藏时暂停。
- 设置「外观」加「对话页显示立绘」（`appearance.chatStand`，默认开，只记这台设备上）；一级摘要变成
  「SCSP 头像开／关 · 立绘开／关」。DESIGN.md 新增「对话页的立绘小人」，GLOSSARY 的「立绘」补上这个用法。
- 验收（本地构建版 + Playwright）：右下角出现、在动（两帧不同）、点一下有反应（截图）、关掉设置后消失、
  手机 390×844 上不压输入栏、不横向滚动；通话中（拨号时和收成通话条后）都不出现；素材缺失 / WebGL
  不可用时同样不出现（`Stand` 失败时什么都不画，这里也不给画布留位置，没有空白框）。
  验收脚本和截图是一次性的，按仓库规矩没提交（本机 `.scratch/_accept/`）。
- 取舍：打开对话页就会下载她这一套立绘素材（几 MB），不跟 `saveData` 走——先按「默认开」做，要省流量再说。
- 目标 2 的前置：真乃这套衣装里有 `lip_smile` / `lip_anger` 等口型（通话层已经在用），
  音量驱动口型可以直接接到现在这个 `speaking` 上；素材里没有嘴部通道的衣装按票里的降级处理。

## 后续（2026-10-25）：能改大小、能说话、说话时头顶有气泡

1. **大小与位置**：拖她脚边的把手改大小（往左放大，80–480px，键盘上是左右方向键；放不下时按消息区高度缩回、
   比例不变），拖她本人换位置（拖动超过 4px 才算挪她，否则就是点她一下）；两个都记在这台设备上
   （`lib/chatCompanion.ts`），位置按消息区里空出来的地方的比例记，换窗口大小也不会跑出去。
   手机上把手一直在，电脑上悬停她时才出来。
2. **小台词**：点她一下随机说一句，头顶出气泡，并放她说的那一句；正在说话（这句、或者那条回复的
   「朗读」）时点她不再打断。语料从 SC-Time 的首页台词（`myPageComments`）整理：
   `scripts/import-sc-time-small-talk.py --source <SC-Time>/resources/idols` 把每句的日语、中文、
   口型推出的心情、时段、身体动作和表情（`animation1` / `animation2`）和 `Voices/<voice>.m4a`
   拷到 `corpus/small-talk/<角色标识>/`（`corpus/` 不进仓库，和立绘一样只留在部署机上；
   默认路径可用 `EIDOLON_SMALL_TALK_PATH` 改）。
   后端 `GET /api/characters/<id>/small-talk?hour=<本地钟点>` 随机挑一句，`.../<line>/voice` 发那一句的录音；
   前端把这一句的身体和脸照原作播（衣装里没有那个动画时按心情挑），气泡里是这句话。
   这一位没有语料、或者这一句没有录音时只换一个表情，不出气泡。
   - 不用合成：放的是原作里她那句录音（m4a），不花 TTS 的钱，也不经过模型；28 位、约 2100 句、190MB。
   - 时段：SC-Time 里标了 morning / afternoon / night 的句子只在那一时段说，其余什么时候都能说。
3. **气泡**：实底、圆角、没有尾巴，最多 16rem，日语原文在上、中文字幕在下；说完再留一会儿自己收起来。
4. **按语气摆姿势**：她回完一条回复以后，判断模型按整条回复判一次情绪（和通话里同一个判断模型），
   后端在 `done` 之后多发一条 `emotion` 事件（不拖慢回复），宠物照着摆 15 秒，同意或否定时点头、
   摇头；判不出来、没配判断模型、或者这一回合用的是用户自带 LLM 时不摆。
   判断在 `EmotionJudging.answer()`；文字回合的整条回复当成一段问（`SegmentToJudge`）。
   这一边把判出来的把握（`strength`）一起发：≥ 0.6 用强一档的动作和脸，≥ 0.85 用哭脸/闭眼笑，
   门槛也从 0.5 降到 0.3（宁可给一个鲜明的表情，也不要一句「平静」）；判断的问题改成
   「最明显、最外露的那个，别轻易选平静」。
   注意：她刚说完话时动作会连着换（想事情 → 待机 → 按语气），引擎里「先放下手再换」的接力在
   3.6 里连做两次会把排在后面的动作卡掉，人就停在半路——所以正在放 `arm_down*` 时不再接力，
   直接换过去（`StandEngine.playBody`）。
5. **复读语音也有表情**：点她那条回复旁的「朗读」时，按这条回复的语气摆，一直摆到念完（长度跟语音走），
   念完回待机。这条回复的语气**用回复时判的那一次**（后端按消息 id 记在进程里，`GET /api/messages/<id>/emotion`
   直接给同一个答案），所以回复时和复读时摆出来的动作一样；没判过（老消息、后端重启过）才现判一次。
   不依赖回复时那条 `emotion` 事件，老消息、重开页面也都有。
6. **通话里也是同一套**：每段的 `emotion` 消息带上判断的把握（`strength`），通话立绘按同一套分级
   （≥ 0.6 强一档、≥ 0.85 最夸张的脸）换表情和动作，平静的段沿用上一段的心情和把握。
   嘴还是按「她的声音在放」开合（`segment-playing` / `bot-started-speaking`），不是音量包络——
   要按音量张口得给 WebRTC 的音频挂 `AnalyserNode`，那是另一块。
