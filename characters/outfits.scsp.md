# SCSP 衣装数据能给我们什么

调查对象：`D:\SCSPDownloader\SCSPDownloader\` 里的 `wardrobe-data.json`、`official-current-index.json`、`character-data.json`（SCSP game 2.19.0 / resource `20006200@jSEgjcBSZG9ol5Cvnq67X3Y=`），对照 `corpus/stand/source/spine_manifest.json`（2,192 条立绘、1,502 张卡、28 位偶像）。

产物：[`characters/outfit-names.json`](outfit-names.json)（250 条，134 KiB）。

## 结论

- **没有一个能整表搬的 join。** SCSP 那 3,185 套衣装是 3D 游戏自己的衣装目录（默认服、`スーツ01`、`コスチューム01`、合作、`+` 强化版、3D 独占原创），我们的 1,502 张卡是 2D 手游的卡面衣装，两个目录只是**部分重合**。
- 唯一可靠的钥匙是**「角色 + 日文衣装名」两端都锁**：SCSP `sets[].character` == `idolId`，且两边 `【…】` 里的名字（NFKC、去掉全部空白后）完全相等。覆盖 **250 / 1,502 张卡（16.6%）**，折合 **255 / 2,192 条立绘（11.6%）**，用到 249 个 SCSP set、15 个衣装系列。
- 这 250 条的名字**和我们已有的名字一模一样**，所以「改名」收益是 0。真正新增的只有：250 条日文说明文、249 套的 dress/hair/accessory 结构、222 条图标路径（图标没下载）。
- **中文名：没有。** SCSP 只有一份 `localizetext.bytes`（日文）。`character-data.json` 里那 42 个名字是日文汉字（`櫻木 真乃`），不是中文译名；我们 app 的中文名只有角色名（`characters.toml` 的 `name_zh`），衣装名一直是日文（`stand_outfits.card_name()` 从 `【】` 里抠）。

## 1. 两边的数据

| | 我们 | SCSP |
| --- | --- | --- |
| 单位 | 卡（`enzaId`），一张卡一套私服 + 一套演出服 | 衣装 set（dress + hair + 若干 accessory） |
| 数量 | 1,502 张卡 / 2,192 条 manifest | 3,185 套 / 10,507 个部件 |
| 角色 | 28 位（`idolId` 1–28） | 40 位（我们这 28 位是 `01`–`28`，另有 `78`–`90` 的其它偶像，58 套） |
| 名字 | `dressName` = `【衣装名】偶像名` | `sets[].name` = `【衣装名】偶像 名`，另有 `description` |
| 编号 | `enzaId` = `PPP III SSSS`（103/104/105/193/194/300/400 + 偶像号 + 卡序号） | `sets[].id` / `records[].id`，SCSP 自己的商品号 |

我们 28 位偶像上，SCSP 有 3,127 套；其中只有 249 套和我们的衣装同名同角色。

## 2. 唯一的 join：角色 + 日文衣装名

### 2.1 规则

```
character := "%02d" % idolId                     # 01..28
title(s)  := 【…】 里的内容，NFKC 之后去掉所有空白
match     := title(dressName) == title(sets[].name) 且 sets[].character == character
```

- 名字这一端必须规范化：SCSP 写 `櫻木 真乃`（中间有空格），我们写 `櫻木真乃`；全角/半角也要归一。
- 角色这一端必须锁：`ジャージ`、`ホーリーナイトケープ` 这类是**全员衣装**，每个偶像都有一套自己的。只按名字匹配会多出 268 次跨角色歧义，全是错的（那是别人的那套）。

佐证（每个 set 的 3D 模型名是衣装名的罗马字压缩，不是随机编号：`hncp`、`ovcm`、`fliwbl`、`8thasy`、`jrsy`）：

| enzaId | 我们的 `dressName` | SCSP set | dress 部件 prefab |
| --- | --- | --- | --- |
| 3000010040 | `【ホーリーナイトケープ】櫻木真乃` | 1003 `【ホーリーナイトケープ】櫻木 真乃` | `m_dress_0308_hncp01_00.prefab` |
| 3000010070 | `【オーバーキャストモノクローム】櫻木真乃` | 201010 | `m_dress_0081_ovcm01_00.prefab` |
| 3000010410 | `【フローウィングベル】櫻木真乃` | 1021 | `m_dress_0683_fliwbl_00.prefab` |
| 3000010530 | `【レジスタンスオーダー・ネオス】櫻木真乃` | 1035 | `m_dress_2259_8thasy_00.prefab` |

### 2.2 为什么其他线索都不是 key

| 线索 | 结论 |
| --- | --- |
| `enzaId` | 2D 手游的卡号，SCSP 没有卡号，也没有卡表（wardrobe 按衣装组织，不是按卡） |
| `sets[].id` / `records[].id` | SCSP 自己的商品号（1001 / 201010 / 701005 …），和 `enzaId` 无交集 |
| `resource`（128、259、308 …） | 只出现在它的 prefab 名里（`m_dress_0128_01frlb_00`），我们的 manifest 里没有这个字段 |
| product icon | `product_icon_<group>_<7 位商品号>`，商品号是 SCSP 的 `records[].id`，不是 `enzaId` |
| `character-data.json` | 只有 42 个角色名，没有衣装 |
| 顺序 | 两边都按各自发布顺序排，但 SCSP 每角色 104–120 套（我们 30–62 张卡），且开头就不同（SCSP 第一套是 `【フロウリッシュブルーム】`，我们第一张卡是 `【ナチュラルモード】`）；没有位置对应 |
| `stand` / `stand_costume` | 同一张卡两条 manifest 的 `dressName` 完全相同（690 张双类卡，0 处不同），分开找不会多出匹配 |
| `+` 强化版 | SCSP 里 555 套带 `+`（`【バース オブ ウィング+】`），是**另一套**升级版，不能当我们的那套 |

## 3. 覆盖

| 指标 | 数字 |
| --- | --- |
| 匹配到的卡 | **250 / 1,502（16.6%）** |
| 匹配到的 manifest 条目 | **255 / 2,192（11.6%）** |
| 用到的 SCSP set | 249（`ルカ` 的 `3000260140`、`3000260410` 都叫 `【フローウィングベル】`，同一套 set 26021 对两张卡） |
| 衣装系列 | 15 |
| 带图标的卡 | 222 / 250（28 张 `ジャージ` 在 SCSP 里就没有图标） |
| 按稀有度 | `Special` 146、`Anniversary` 104；`P_SR`/`P_SSR`/`Mizugi`/`FesReward`/`FesTour`/`Other`/`P_UR` 一张都没有 |
| 按偶像 | 每位 8–11 张，28 位都有 |

### 15 个能对上的系列

| 衣装 | 卡数 | | 衣装 | 卡数 |
| --- | ---: | --- | --- | ---: |
| フローウィングベル | 29 | | パジャマ・デ・カブカブ | 1 |
| オーバーキャストモノクローム | 28 | | パジャマ・デ・ガオガオ | 1 |
| サンセットスカイパッセージ | 27 | | パジャマ・デ・ハムハム | 1 |
| ジャージ | 28 | | パジャマ・デ・ペンペン | 1 |
| ホーリーナイトケープ | 28 | | パジャマ・デ・ワンワン | 1 |
| ユナイトバースプラネタリ | 28 | | イノセントセーラー | 19 |
| リフレジェントプルマージュ | 28 | | エモーショナルユニフォーム | 2 |
| レジスタンスオーダー・ネオス | 28 | | | |

（睡衣那五套在 2D 里是每位偶像各自的名字，所以一个系列只有 1 张卡。）

### 10 行例子

| enzaId | 偶像 | 类型 | 我们的 `dressName` | SCSP set | set id | 图标 |
| --- | --- | --- | --- | --- | ---: | --- |
| 3000010030 | 樱木真乃 | Special | 【ジャージ】櫻木真乃 | 【ジャージ】櫻木 真乃のジャージ | 701005 | — |
| 3000010040 | 樱木真乃 | Special | 【ホーリーナイトケープ】櫻木真乃 | 【ホーリーナイトケープ】櫻木 真乃 | 1003 | `product_icon_24_0001003.png` |
| 3000010070 | 樱木真乃 | Anniversary | 【オーバーキャストモノクローム】櫻木真乃 | 【オーバーキャストモノクローム】櫻木 真乃 | 201010 | `product_icon_24_0201010.png` |
| 3000010100 | 樱木真乃 | Special | 【イノセントセーラー】櫻木真乃 | 【イノセントセーラー】櫻木 真乃 | 1034 | `product_icon_24_0001034.png` |
| 3000010140 | 樱木真乃 | Anniversary | 【サンセットスカイパッセージ】櫻木真乃 | 【サンセットスカイパッセージ】櫻木 真乃 | 201014 | `product_icon_24_0201014.png` |
| 3000010220 | 樱木真乃 | Anniversary | 【ユナイトバースプラネタリ】櫻木真乃 | 【ユナイトバースプラネタリ】櫻木 真乃 | 201024 | `product_icon_24_0201024.png` |
| 3000010410 | 樱木真乃 | Anniversary | 【フローウィングベル】櫻木真乃 | 【フローウィングベル】櫻木 真乃 | 1021 | `product_icon_24_0001021.png` |
| 3000010440 | 樱木真乃 | Special | 【リフレジェントプルマージュ】櫻木真乃 | 【リフレジェントプルマージュ】櫻木 真乃 | 1012 | `product_icon_24_0001012.png` |
| 3000010530 | 樱木真乃 | Special | 【レジスタンスオーダー・ネオス】櫻木真乃 | 【レジスタンスオーダー・ネオス】櫻木 真乃 | 1035 | `product_icon_24_0001035.png` |
| 3000020030 | 风野灯织 | Special | 【ジャージ】風野灯織 | 【ジャージ】風野 灯織のジャージ | 702005 | — |

## 4. 剩下的 1,252 张为什么对不上

- 我们这边多数是**卡面衣装**：P_SR/P_SSR 卡面画的那套（`【ナチュラルモード】`、`【ほわっとスマイル】`、`【ぐうぜんBOOKS】`…），2D 手游有、3D 游戏没做。
- SCSP 那边是它自己的衣装目录：`【デフォルトコスチューム】`、`【コスチューム01】`、`【スーツ01】`、`【Dsコラボジャージ・ホワイト】`、各种 `+` 强化版、3D 独占原创（`【フロウリッシュブルーム】`、`【バース オブ ウィング】`…）。我们 1,502 个衣装名里找不到对应的 SCSP set 有 2,936 / 3,185 套（反过来也一样）。
- 所以 1,252 张卡不是「匹配失败」，是**对方根本没有这套衣装**：换个匹配算法（模糊、读音、翻译）也不会凭空变出对应物。
- 我们还有 40 张卡的名字是空的（`【】櫻木真乃`）。SCSP 那边对应的位置是 `【デフォルトコスチューム】` 这类，不是同一套，不能拿来补名。

## 5. SCSP 能加什么（如果以后接线）

| 东西 | 数量 | 值不值得 |
| --- | --- | --- |
| 衣装名 | 250（和现在一模一样） | 0：换装面板显示的名字不会变 |
| 完整 set 名（带偶像名） | 250 | 0：客户端 `copy.conversation.outfits.cardName` 已经把名字包成 `【…】`，再接一次会变成双重方括号 |
| 日文说明文 | 250 条 | 可以当换装面板的 tooltip / 语音闲聊素材（例：`283プロのアイドル達が着用している クリスマスステージ衣装`） |
| set / parts 结构 | 249 套 | 只能说明「这套由 dress+hair+accessory 组成」，我们的立绘是整张图，颗粒度对不上 |
| 图标 | 222 张，12.3 MiB | 换装面板已有 Spine 渲染的 400×500 缩略图（4:5，正好是卡片比例），SCSP 图标是方形 3D 商品图，风格不统一；只适合给「清单收集」或设定页补图 |
| 中文名 | 0 | 没有 |

**结论：如果目标只是给换装面板加中文名或更好看的名字，SCSP 帮不上；它能补的是 250 条日文说明文和 222 张方形图标。**

## 6. 图标：路径与取用

### 6.1 路径 scheme

```
root/assetbundles/product_icon_<group>_<productId:07d>.png
```

- `group`：`24` = dress、`25` = hair、`26` = accessory（和 `records[].group` 一一对应）。
- `productId` 是 SCSP 的 `records[].id`（也就是 set 的 `dress_id` / `hair_id` / accessory id），**不是** `enzaId`。6 位的补前导零：set 201010 → `product_icon_24_0201010.png`。
- 一套衣装的图标 = 它 dress 部件的图标；例：set 1003 → `root/assetbundles/product_icon_24_0001003.png`（56,803 B）。
- 索引里每条都是独立条目，字段：`id`（上面的路径）、`label`、`name`、`type: "png"`、`size`、`file`（26 位 bundle key）、`catalog: "root/assetbundles"`。

### 6.2 数量

| 项 | 数量 |
| --- | ---: |
| `official-current-index.json` 全部条目 | 190,388 |
| 其中 png | 52,520 |
| `product_icon_<nn>_<7 位>` | 13,125 |
| └ dress（24） | 3,250 |
| └ hair（25） | 3,870 |
| └ accessory（26） | 3,328 |
| └ 其它前缀（卡片、商店、活动） | 2,677 |
| 其它 `product_icon*`（`shop_`、`store_`、`exchange_`、`_noframe` 等） | 1,747 |
| 全部 `product_icon*` png | 14,872（约 638.7 MiB） |
| 我们要的 222 张 | 12.3 MiB |

另外：3,128 / 3,185 套 set 的三个部件都有图标；缺图的基本是 `ジャージ` 这类（3,307 条 dress 记录里 57 条没有 `icon`），所以我们那 250 条里有 28 条拿不到图。dress 图标没有 `_noframe` 版本。

### 6.3 要接线还缺什么

- 两个导出的 JSON **都没有 CDN 基址、没有版本签名、也没有单个文件的下载 URL**：只有 `catalog`（`root/assetbundles`）+ `label` + `file`（bundle key）+ `size`。下载器内部知道怎么拼，但它没导出。
- 可选的路：① 走下载器的本地服务（`GET /api/resource?id=root/assetbundles/product_icon_24_0001003.png`，它自己回去取）；② 让导出多写一个 `base_url` / 预签名规则；③ 只把这 222 张（12.3 MiB）单独导出成一份清单。
- 这三条都要**下载游戏素材**，不在本任务范围内。本次只把路径写进了 `outfit-names.json` 的 `icon` 字段，没有下载任何东西。

## 7. 死路清单（不用再试）

1. **用 `enzaId` / 卡号去 SCSP 找卡**：SCSP 没有卡表，wardrobe 不按卡组织，索引里也没有 `card_*` / `idolcard_*` 的 2D 卡面资源。
2. **用 `resource`（128/259/308…）或 prefab 名反查**：纯 SCSP 内部编号，我们 manifest 没有这个字段。
3. **用图标商品号反查**：`product_icon_24_0001001` 的 `0001001` 是 SCSP 商品号，不是 `enzaId`。
4. **按顺序对齐**：两边发布顺序无关，SCSP 每角色套数约是我们的两倍，且首套就不同。
5. **指望 SCSP 给中文名**：只有一份日文 `localizetext.bytes`；`character-data.json` 的 42 个名字是日文汉字。
6. **拿 `+` 强化版凑数**：那是另一套（升级版），不是我们那套。
7. **拿 `デフォルトコスチューム` / `コスチューム01` 补我们 40 张空白名**：不是同一套衣装。
8. **模糊匹配 / 读音匹配**：能多捞到的只有 `(フード有り)` 这种同套变体（SCSP 里本来就另有 `(フードオフ)`、`(ジャケットオフ)` 等），收益 < 1%，风险是把两套不同的衣服并成一套。

## 8. 复现与校验

规则伪代码：

```python
for card in spine_manifest:                      # 1,502 个 enzaId
    character = f"{card.idolId:02d}"
    t = strip_ws(nfkc(title_of(card.dressName)))  # 【…】
    for s in wardrobe.sets where s.character == character and strip_ws(nfkc(title_of(s.name))) == t:
        yield card.enzaId, s
```

产物 `characters/outfit-names.json`（schema 1）：

```jsonc
"outfits": {
  "3000010040": {
    "ja_name": "ホーリーナイトケープ",
    "set_name": "【ホーリーナイトケープ】櫻木 真乃",
    "set_id": 1003,
    "idol_id": 1,
    "scsp_character": "01",
    "dress_type": "Special",
    "parts": { "dress": 1003, "hair": 1003, "accessories": [] },
    "icon": "root/assetbundles/product_icon_24_0001003.png",
    "icon_size": 56803,
    "description": "283プロのアイドル達が着用している\nクリスマスステージ衣装\n星たちが踊る 夜が始まる"
  }
}
```

校验（本地跑过，脚本在 `.scratch/scsp-join/`，不入库）：

- `json` 能解析；250 条；每个 `enzaId` 都在 `corpus/stand/source/spine_manifest.json` 里；每个 `set_id` 都在 `wardrobe.sets` 里。
- `ja_name` 去空白后等于该 set 名字的 `【…】`；`icon` 在 `official-current-index.json` 里存在（222 条）。
- 没有 `zh_name` 字段：SCSP 没有中文数据可搬；`join.zh_name` 明确写了 `null`。
