# 本地用 Playwright 验收

票里写「本地构建版上用 Playwright 验收」时照这里做。验收脚本是一次性的：放在 `frontend/scripts/_accept-*.mts`（这样才找得到 `playwright` 包），用 `node` 跑，验完删掉，不提交（规格「组件不写测试」）。截图写到 `.scratch/_accept/`，同样用完删掉。

## 起服务、停服务

前端跑构建版，不跑 `next dev`（dev 模式会卡）：

```sh
# 后端（:8000），.env 里要有 EIDOLON_DEV_LOGIN=1
cd backend && uv run --quiet --env-file=../.env eidolon serve
# 前端（:3000），在 frontend/ 下，先 npm run build
BACKEND_URL=http://localhost:8000 EIDOLON_STAND_ASSETS_URL=<同 .env> npm run start
```

两个都放后台跑。`EIDOLON_STAND_ASSETS_URL` 不带就看不到立绘（CSP 只许从这个地址加载）。停服务时，结束后台任务不够：`next start` 的子进程还占着 :3000，重新构建后它会继续服务旧页面。要按端口找到进程再结束（PowerShell：`Get-NetTCPConnection -LocalPort 3000 -State Listen` 拿 `OwningProcess`，再 `Stop-Process`），:8000 同理。改了前端代码要先停 :3000，再 `npm run build`，再起。

耗时长的活（`next build`、Playwright、后端完整 pytest）不要和别的 agent 同时跑，否则会卡住，一次只跑一个。

## 登录

用开发登录按名字登录。本地 `.env` 的 `EIDOLON_ADMINS` 里写 `github:<同一个名字>`（逗号分隔可以写多个），那个名字登录进来就是管理者：开发者登录会给账号记一条同名的 GitHub 身份，没有 OAuth 的本地部署也只有这样认得出管理员（ADR-0013）。原来的 `github:local-admin` 是曾经那份假 GitHub 登录的身份，留着不影响。请求要带 `Origin`，后端会检查：

```ts
await context.request.post(`${origin}/api/auth/dev-login`, { data: { name: "有机物" }, headers: { origin } });
```

`frontend/scripts/screenshots.mts` 的 `signIn` 也是这么写的。

## 好感度和礼物

开关默认开，本地 `.env` 配了判断模型、没设 `EIDOLON_AFFINITY_AND_GIFTS`，照常起后端就是开的。要看「未开放」时只在这次起的后端上关掉，不改 `.env`、不在后台改配置：

```sh
cd backend && EIDOLON_AFFINITY_AND_GIFTS=0 uv run --quiet --env-file=../.env eidolon serve
```

要的状态（背包里有几件、某位角色在冷却中、某一档）不靠抽奖和对话凑，造一个专用的开发登录用户（例如 `gift-accept`），同意条款（`POST /api/account/consent`，`{"agree_to_terms": true, "at_least_13": true}`），读一次 `/api/gifts` 让它建好行，再直接往 `backend/data/eidolon.db` 写：

- 背包：`INSERT INTO gift_backpacks VALUES ('<user_id>', '<礼物 id>', <件数>)`，礼物 id 和名字在 `characters/gifts.toml`
- 抽奖次数：`UPDATE gift_balances SET draws = <n> WHERE user_id = '<user_id>'`
- 好感度：`INSERT OR REPLACE INTO affinities (user_id, character_id, value, updated_at, cooling) VALUES ('<user_id>', '<角色 id>', <0–100>, '<ISO 时刻>', <冷却中 1，否则 0>)`

`user_id` 从 `GET /api/account` 拿。验完以这个用户登录调 `POST /api/account/delete`（`{"confirm": true}`），它的一切一起删掉，Sallyn 的数据不动。

## 通话

Chromium 用假麦克风，上下文给麦克风权限：

```ts
const browser = await chromium.launch({
  args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
});
const context = await browser.newContext({ viewport, permissions: ["microphone"] });
```

- 本地后端接得通，几秒到十几秒后变成「通话中」。但 Fish 直连不通，后端要走本机代理，否则接通了也没声音，日志里会有 `FishTTS … timed out during opening handshake`。语音服务不读 `HTTPS_PROXY`，只在这次起的后端上带上代理，不改 `.env`（地址取本机 `HTTPS_PROXY` 的值）：

  ```sh
  cd backend && EIDOLON_PROXY_URL=http://127.0.0.1:10808 EIDOLON_PROXY_SERVICES=judge,tts uv run --quiet --env-file=../.env eidolon serve
  ```

  假麦克风只发提示音，听不出她的声音。要听声音，让用户在本机浏览器里打开 :3000 自己打。
- 页首电话键在对话打开前是禁用的，先等它可点再点：

  ```ts
  await page.waitForFunction(() => !document.querySelector('button[aria-label="和櫻木真乃通话"]')?.hasAttribute("data-disabled"));
  ```

- 通话层滑上来要 410ms，量位置、截图前先等一下。
- `page.goto` 是整页重载，会挂断通话。通话中换页要点页面上的链接和按钮（客户端跳转）。

### 造出结束卡

通话「因故结束」在本地也造得出来：拦下建立通话的请求 `/api/offer`，换成后端拒绝时的回答。

| 回答 | 结束卡 |
| --- | --- |
| `429`，`{"detail": "…"}` | 超限额（主操作「去设置自带密钥」） |
| 其他错误状态 | 没接通（主操作「重拨」） |

先把请求挂起不回，等换到别的页面再放行，就能造出「在别的页面上因故结束」：

```ts
let held: Route | null = null;
await page.route("**/api/offer", (route) => void (held = route));
// …拨号、收起通话层、换到设置…
await held!.fulfill({ status: 429, contentType: "application/json", body: JSON.stringify({ detail: "这一小时的通话次数用完了" }) });
```

### 造出后端在通话里发的消息

`ended`（她挂断、到上限）、`done` 这些是接通以后从数据通道来的，拦 `/api/offer` 只能造出拨号被拒。要造它们，在页面里另起一个 `RTCPeerConnection` 冒充后端（Chromium 本机回环接得通）：

1. `context.addInitScript` 注入假后端：`setRemoteDescription(offer)`，把 offer 里的音频收发器改成 `sendrecv` 并换上一条 `AudioContext().createMediaStreamDestination()` 的音轨，`createAnswer`，等 ICE 收集完再交出 SDP；`ondatachannel` 收到 `client-ready` 就回 `{"label":"rtvi-ai","type":"bot-ready","id":<同 id>,"data":{"version":"1.0.0"}}`。
2. `page.route("**/api/offer")`：POST 用 `page.evaluate` 交给假后端应答，回 `{sdp, type: "answer", pc_id: "fake-pc"}`；PATCH（补发的 ICE 候选）交给它 `addIceCandidate`，回 `200 {}`。
3. 接通后由假后端发 `{"label":"rtvi-ai","type":"server-message","data":<服务器消息>}`；挂断再发 `{"type":"signalling","message":{"type":"peerLeft"}}`。

这样造出来的对话事件等只在页面上，库里没有；对话列表按接口重读，看不到它。
