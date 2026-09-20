# astrbot_plugin_rt_link

将 NapCat 对话中的 QQ 号绑定到「菌菌控制台」的 apikey，据此查询太鼓达人指定曲目的成绩，并以 **AI v2 Rating**（Taiko Signal Rhythm v2）评估玩家实力，结合 AI 识别的节奏型画像给出「该练什么 + 参考曲目」建议。

## 功能

- 绑定管理：`bind` / `unbind` / `list`（管理员）
- 成绩查询：按曲名/别名模糊匹配（中文/日文/英文）
- **曲名别名索引**：内置别名表收「国服曲名 + 日文曲名 + 罗马字（ESE 谱面）+ 人工整理简称/黑话」，段位查询、查分、别名申请共用同一套匹配；`北埼玉`、`六天`、`罗特`、`顿卡马`、`天狗囃子` 这类叫法都能直接查到
- **难度筛选**：支持难度别名（鬼/魔王/里/里魔王/松/困难/竹/一般/梅/简单）与组合名（如「鬼夏祭」「里夏祭」）
- **歌曲别名**：两步确认（发起 → 管理员审核），审核通过后可用别名查询
- **玩家实力评级**：综合 Rating + 七维能力（谱面底力/持续耐力/爆发手速/击打精度/配置处理/节奏适应/读谱）+ 强项/弱项
- **实力画像图片**：`/rtlink rating` 或 AI 工具 `generate_rating_image` 在插件本地生成 `1440 × 2720` PNG 报告（Rating 环 + 能力星系 + 强弱项 + 表现证据 + 冷门配置观察）
- **个人画像图片**：`/rtlink` 或 `/rtlink profile` 输出宽 1440 的自适应长图：分段配色 Rating 环、互斥评价/皇冠统计、能力行星、配置评分概览、带皇冠和实际评价图标的 BEST 20、最多 8 首提升建议。表/里按独立谱面排序，只有里谱显示淡色魔王水印。
- **配置评分详情**：`/rtlink progress` 展示 18 种配置 × 7 个 BPM 档的评分、理论满分与样本。满分由全曲库全良按同一算法计算；不足 3 个计分样本保留空值。积累至少两次有效同步后显示同版本历史曲线。
- **节奏型弱项图片**：`/rtlink weakness` 输出 `1440 × 2200` PNG；按「节奏型 × BPM 档」给出核心短板、练习路径和参考曲目
- **提升评价候选**：`/rtlink improve [评价] [难度]` 输出 `1440 × 2020` PNG，按曲风分区列出「离目标评价最近」的谱面，并给出两条路线：判定（把几个「可」「不可」打成「良」，必要时标注「必须全良」）与连打（还差几打、补完这局黄条共几打、对应秒速，以及是否超出该谱連打理論値）；没有黄条的曲目会直接写明「只能靠判定」。LLM 工具 `find_rank_improvements` 返回同样内容的文本
- **冷门配置分组**：内置谱面库覆盖率低于 3% 的节奏配置单列观察，不进入核心弱项排行
- **成长记录**：仅在成功同步且评分输入变化时保存，查看图片/文本不会重复记点。新配置历史按玩家、服务器、数据源、算法和资源版本隔离，压缩保存计算输入与全部配置状态；谱面资源按哈希共享归档。
- **完整帮助长图**：`/rtlink help` 或 `/rtlink 帮助` 返回同一张说明图片，包含菌菌 apikey 四步绑定实图、常用指令、评级与安全说明
- LLM 工具：注册多个查询工具，模型可在自然对话中自动调用
- **段位道场查询**：`/rtlink dan [年份] [区域] [段位] [曲名]`（或 `/rtlink 段位 …`）查 2022–2026 日版/国际版与国服课题曲、普通/金合格条件、开放时间与来源；按曲名反查时同时给出国服名、日文名与 RTLink 曲目 ID，支持「鬼 天竺2000」这样带难度前缀
- **AI 段位资料查询**：LLM 工具 `query_dan_course` 与上面的命令走同一套查询（同样支持别名）
- **AI 过段能力参考**：LLM 工具 `evaluate_player_dan` 将三首课题曲的实际良/可/不可/连打与普通、金合格条件逐项对照，并明确标注魂槽及连续演奏无法验证
- 本地存储：SQLite 持久化全部 1–5 难度成绩；当前最佳、同步批次、去重变化历史分表保存，原始字段完整保留
- 空间监管：`/rtlink storage` 查询用量，接近配额自动提醒管理员

## 命令

```
/rtlink bind <apikey> <player_id> [server]  绑定当前 QQ（server 默认 cn，仅私聊）
/rtlink unbind                              解绑当前 QQ
/rtlink score <曲名|别名|鬼夏祭>             查询指定曲目成绩（支持难度前缀组合名）
/rtlink rating                              生成实力画像图片
/rtlink update                              跳过缓存，从菌菌重新拉取并记录历史快照
/rtlink profile                             生成个人 Profile（与裸 /rtlink 相同）
/rtlink progress                            查看全部配置评分、理论满分、样本与历史曲线
/rtlink weakness                            生成节奏型弱项与练习建议图片（冷门配置单列）
/rtlink improve [评价] [难度]                生成「提升评价」图片（分区列出最接近目标的谱面）
/rtlink <评价> [难度]                        等价于 /rtlink improve，省略 improve 的简写
/rtlink dan [年份] [区域] [段位] [曲名]       查段位道场课题曲、合格条件与来源（支持曲名别名）
/rtlink alias <ID或曲名> <别名>              申请歌曲别名（待管理员审核）
/rtlink help                                查看帮助
/rtlink 帮助                                查看同一张完整帮助长图
/rtlink about                               查看插件信息

裸 `/rtlink`（不带子命令）默认返回新版个人画像，等价于 `/rtlink profile`。原详细实力报告保留在 `/rtlink rating`。
评价简写示例：`/rtlink 金雅`、`/rtlink 紫雅 鬼`、`/rtlink 极`。
段位查询示例：`/rtlink dan 2025 十段`、`/rtlink dan 十段 国服`、`/rtlink dan 六天`、`/rtlink dan 鬼 天狗囃子`。

管理员指令不在此列出，完整指令（含管理员）见 [docs/commands.md](docs/commands.md)。
```

也可以直接自然语言询问，例如：「可可子，我的实力怎么样」「可可子，我该练什么」「可可子，哪些歌我零不可」「可可子，我打得最好的定数 10.5 的歌」「可可子，有哪些歌我还没打过」。

## AI 检索能力

LLM 工具 `search_scores` 是一个通用检索入口：曲名/日文名/分区/别名、难度、定数、单谱 Rating、精度、分数、音符数、评价等级、「可」「不可」数量、全连/全良状态、距目标评价的缺口，全部可作为筛选条件自由组合，并支持排序、分页与翻页。

- 匹配方式：`contains`（包含，默认）/ `exact`（精确相等）/ `regex`（正则）/ `all`（空格分词全部命中）/ `any`（任一分词命中）
- 检索范围：`played`（已有成绩，默认）/ `unrated`（打过但未参与评级）/ `unplayed`（没打过）/ `all`（全部 1393 张谱面）
- 指定 `target_rank` 后，每条结果都会附上目标门槛、还差多少分、判定路线（转几个「可」「不可」，是否必须全良）与连打路线（还差几打、总打数、秒速、是否打得出来）

具体参数表见 [docs/commands.md](docs/commands.md)。

## 难度筛选与别名

- 难度别名：`鬼/魔王/4`、`里/里鬼/里魔王/5`、`松/困难/3`、`竹/一般/2`、`梅/简单/1`（仅鬼/里参与评级）。
- 组合名：查询时可用「鬼夏祭」「里夏祭」这类「难度前缀 + 曲名」写法。
- 歌曲别名：`/rtlink alias <ID或曲名> <别名>` 发起（返回歌曲 ID/名称等信息供确认），管理员用 `/rtlink aliaslist` 查看、`/rtlink aliasapprove` 批量通过；通过后即可用别名查询。
- LLM 工具 `set_song_alias` 支持让模型代用户发起别名设置；查询工具 `query_taiko_score` / `search_scores` 支持 `level` 难度参数与别名。

## 评级说明

- 主 Rating 采用 **AI v2**（Taiko Signal Rhythm v2），参考 OurTaiko-v1 公式（MIT，来源 [OurTaiko/taiko-rating-analyzer](https://github.com/OurTaiko/taiko-rating-analyzer)）。
- **仅评估鬼/里（魔王/里魔王）谱面**，1–3 难度无谱面定数，不参与评级。
- 谱面元数据打包在 `resource/charts.v1.json.gz`（1393 张，覆盖 95% 谱面）。
- Rating 历史保存在 AstrBot 的 `data/plugin_data/astrbot_plugin_rt_link/rt_link.db`，插件更新不会覆盖；快照不保存 apikey。
- 每次菌菌同步都会记录同步批次；曲目成绩状态发生变化时追加到 `score_history`，相同状态不会重复占用空间。旧数据库启动时自动增量迁移。
- 升级到新版后，旧 Rating 缓存不会被当作“全难度已同步”。首次发送 `/rtlink`、`/rtlink score <曲名>`、`/rtlink rating`、`/rtlink profile` 或 `/rtlink weakness` 会自动补同步；也可用 `/rtlink update` 手动强制同步。同步失败时会返回这些操作提示。
- 每份快照记录 `algorithmVersion`、`catalogVersion` 和 `catalogSchemaVersion`；后续算法升级后可按版本区间标注曲线，避免把算法变化误判为玩家进步。

## スコアランク（成绩评价）说明

`/rtlink improve` 与 `/rtlink score` 里的「评价」指街机版的 **スコアランク**，共 8 档：

| 档 | 名称 | 门槛（＝该谱極スコア × 比例） | 数值约 |
| --- | --- | --- | --- |
| 1 | 无 | < 50% | < 50 万 |
| 2 | 白粹 | ≥ 50% | ≥ 50 万 |
| 3 | 铜粹 | ≥ 60% | ≥ 60 万 |
| 4 | 银粹 | ≥ 70% | ≥ 70 万 |
| 5 | 金雅 | ≥ 80% | ≥ 80 万 |
| 6 | 粉雅 | ≥ 90% | ≥ 90 万 |
| 7 | 紫雅 | ≥ 95% | ≥ 95 万 |
| 8 | 极 | ≥ 100%（即極スコア 本身） | ≥ 100 万 |

> 门槛是**该谱極スコア的固定比例**，不是天井スコア的比例，也不是固定的绝对分数。
> 極スコア ≈ 100 万，所以「数值约」那一列看起来像整数万，但各曲之间有 ±1% 浮动 ——
> 实测 1390 条成绩：「極スコア × 比例」错判 2 条（99.86%），固定绝对值错判 22 条，
> 「天井スコア × 比例」错判 24 条。见 [docs/score-rank.md](docs/score-rank.md)。
>
> **「极」不要求全良**：極スコア 是分数门槛，黄条每打固定 100 分，
> 判定上留下的「可」可以用多打连打补回来。

算分公式（AC16 ニジイロ～）：

```
スコア = 良 × 基本点 + 可 × ⌊基本点 / 2⌋ + 黄色連打打数 × 100
基本点 = 天井スコア ÷ 总音符数      （每谱固定、10 的整数倍）
天井スコア ≈ 1,000,000              （各曲 98.4 万 ~ 100.5 万）
極スコア = 天井スコア + 必要連打打数 × 100
```

因此「把 1 个『可』打成『良』」等价于 **+半个基本点** 的分数，`/rtlink improve` 就是据此把分数缺口换算成所需良数；连打每打固定 100 分，可作为不动判定时的补充手段。

- 每曲的真实「天井スコア / 極スコア / 必要連打打数」来自 [太鼓の達人 譜面とか Wiki](https://wikiwiki.jp/taiko-fumen/作品/新AC/極スコア/おに)，打包在 `resource/score_rank.v1.json.gz`（覆盖内置谱面库 96.6%）。未覆盖的曲目按「基本点 = 100 万 ÷ 总音符数」估算，图中标注「估算」。
- 详细推导、实测验证与已知偏差见 [docs/score-rank.md](docs/score-rank.md)。

### 连打（黄色連打）与秒速

把分数缺口换算成连打时，必须知道这张谱的黄条到底有多长、有没有黄条：

```
連打秒数   = 60 ÷ BPM起点 × (拍数 − 1/12)        每条黄条分别计算后求和
連打理論値 = ⌈(連打秒数 + 0.001) × 60⌉            逐条取整后求和（即每秒最多约 60 打）
秒速       = 黄色連打打数 ÷ 合計黄色連打秒数      風船連打不计入
```

- 每条谱面的黄条条数、合計秒数、連打理論値与风船资料打包在 `resource/rolls.v1.json.gz`
  （由 `scripts/build_rolls.py` 从 ESE 的 TJA 谱面按上式算出，再用 wiki 公布的
  「極スコア要求連打速度」交叉校验；覆盖 95.2% 谱面）。
- 「极」要求的连打速度通常落在 **16.6 ~ 18 打/秒**，所以结果里超过 30 打/秒时会额外提示偏高。
- **没有黄条的谱面**（库里 130 张只有风船、108 张连风船都没有）无法靠连打补分，只能走判定路线；
  如果只靠判定就必须把现有「可」「不可」全部打成「良」，文案会直接写「必须全良」。
- 连打打数超过該谱連打理論値时，说明这条路打不出来，文案会给出「理論値共 N 打，还差 M 打」。
- 国服接口的結算連打数包含风船打数，插件按谱面资料把风船部分扣除后再算秒速（`BALLOON_NOMINAL_SPEED` 兜底封顶）。

### 曲名与别名

同一首歌在不同资料里叫法不同：国服（菌菌）用国服曲名，日文 wiki 与段位道场用日文曲名，
ESE 谱面里还带一份罗马字/英文曲名，玩家口语又常简称（北埼玉、六天、罗特、顿卡马…）。

```
归一化 key = NFKC → 大小写折叠 → 片假名折平假名 → 繁简折算 → 去掉空白与标点
匹配优先级 = 完全相等 > 前缀 > 包含（同级按难度与曲目 ID 排序）
```

- 全部写法打包在 `resource/aliases.v1.json.gz`（1393 张谱面、5500+ 条写法），
  由 `scripts/build_aliases.py` 合并「谱面库 + ESE 谱面 + 段位资料 + 人工别名表」生成；
  人工整理部分在 [`scripts/data/song_aliases.json`](scripts/data/song_aliases.json)，可直接编辑后重跑脚本。
- 段位查询、`/rtlink score`、成绩检索 `search_scores`、别名申请解析共用这张表；
  用户通过 `/rtlink alias` 提交且审核通过的别名优先级更高。
- 详细规则、来源与维护方式见 [docs/song-aliases.md](docs/song-aliases.md)。

## 目录结构

```
astrbot_plugin_rt_link/
├── main.py             # 插件入口（Star 类 + 命令 + LLM 工具）
├── dan_query.py        # 段位资料查询与 LLM 文本格式化（曲名走别名索引）
├── song_alias.py       # 曲名/别名归一化索引（国服名 / 日文名 / 罗马字 / 简称）
├── rating.py           # 玩家 Rating 算法（AI v2 主 + OurTaiko-v1 参考 + 节奏型画像）
├── score_rank.py       # スコアランク（成绩评价）门槛、「提升评价」候选分析与连打路线计算
├── improve_text.py     # 「还差多少 / 怎么补」的文案渲染（判定路线 + 连打路线）
├── report_image.py     # 与鼓迹网站同源版式的固定像素 Pillow 渲染器
├── profile_image.py    # /rtlink profile 玩家画像渲染器
├── weakness_image.py   # /rtlink weakness 弱项渲染器（冷门配置单列）
├── improve_image.py    # /rtlink improve 提升评价候选渲染器
├── help_image.py       # /rtlink help 完整说明长图渲染器
├── storage.py          # SQLite 成绩、Rating 历史快照与空间计量
├── service.py          # 核心服务（绑定/同步/评级/查询）
├── api_client.py       # 菌菌公开 API 客户端（标准库实现）
├── resource/           # 谱面、段位道场、评价门槛、连打与别名静态资源（压缩 JSON + manifest）
├── scripts/            # 静态资源构建脚本（联网/读本地 TJA，仅构建期使用）
│   └── data/           # 人工维护的数据（曲名别名表）
├── test_api.py         # API 连通性测试（读取 apikey.key）
├── metadata.yaml       # 插件元数据
├── _conf_schema.json   # WebUI 配置项
├── docs/
│   ├── agent-tasks.md  # 开发任务清单
│   ├── commands.md     # 完整指令清单（含管理员）
│   ├── data-fields.md  # 菌菌成绩数据字段含义
│   ├── score-rank.md   # スコアランク 算分公式、门槛推导、连打秒速与数据来源
│   └── song-aliases.md # 曲名别名索引：来源、构建、匹配规则与维护
└── test/               # mock AstrBot + 本地模拟测试
```

## 菌菌公开 API（已实测）

| 项 | 值 |
| --- | --- |
| Base URL | `https://kinoko.zorua.cn/api/v1` |
| 鉴权 | `Authorization: Bearer <tk_... API Key>` |
| 成绩端点 | `GET /scores/hiroba`、`/scores/kinoko`、`/scores/hiroba/recent`、`/scores/kinoko/recent` |

评级使用 `/scores/kinoko`（全历史）取每张谱面的最佳成绩；`/scores/hiroba`（最新）同步并转义落库作为快照。

## 配置项

| 键 | 说明 | 默认 |
| --- | --- | --- |
| `base_url` | API Base URL | `https://kinoko.zorua.cn/api/v1` |
| `default_server` | 默认服务器 | `cn` |
| `request_timeout` | 请求超时（秒） | `30` |
| `sync_ttl` | 同步缓存有效期（秒） | `300` |
| `storage_quota_mb` | 本地存储配额（MiB） | `256` |
| `storage_warn_ratio` | 存储告警阈值（占用比例） | `0.8` |

## 安全说明

- apikey 仅保存在插件服务端的 KV 存储中，**不会**发送给大模型。
- LLM 只能通过工具查询成绩/画像文本，返回内容不含 apikey。
- `bind` / `unbind` / `list` / `storage` / `cleanup` 是聊天命令而非 LLM 工具；且命令一旦返回结果，AstrBot 不会再调用大模型处理该条消息。
- `bind` 命令仅允许在私聊中使用，避免 apikey 泄露到群聊。
- 请勿在普通对话中直接粘贴 apikey。

## 成绩图渲染

- 图片在 AstrBot 插件进程内生成，不访问额外的生图 API，不要求 Node.js、浏览器或独立后端。
- 固定输出 `1440 × 2720` PNG，并使用随插件打包的 `resource/NotoSansCJKsc-Regular.otf`，避免服务器缺少中文字体时出现方框、乱码或平台间排版漂移。
- 数据摘要、颜色、分区层级、Rating 环、能力星系、诊断卡和证据表均与「鼓迹」网站的导出报告保持一致。
- 每次生成使用新的文件名，避免 QQ/AstrBot 复用旧图片缓存；同一用户、同一图片类型仅保留最近 3 张。

## 开发

1. 将本目录软链/复制到 AstrBot 的插件目录（`data/plugins/`）。
2. 在 AstrBot 的插件管理界面中加载插件。
3. 绑定后即可用命令或自然语言查询成绩与实力评级。

### 本地测试 API

```bash
python test_api.py hiroba   # 或 kinoko
```

### 本地模拟

```bash
python test/simulate.py demo                       # 跑一组完整场景
python test/simulate.py bind <player_id> [server]  # 用 apikey.key 绑定
python test/simulate.py score <曲名>               # 查询指定曲目
python test/simulate.py unbind                     # 解绑
```

### 重新构建谱面数据

谱面元数据从 `taiko-star-rating-system-cal-by-ai` 的 `public/data/charts.v1.json` 裁剪压缩而来：

```bash
python scripts/build_charts.py --src ../taiko-star-rating-system-cal-by-ai/public/data/charts.v1.json
```

段位资料由仓库内已审阅 Markdown 构建：

```bash
python scripts/build_dan_courses.py                       # 默认读取 DAN_I_DOJO_2022_2026.md
```

构建脚本会按「曲名归一化 → 难度 → 音符数」把课题曲映射到谱面库，并写出映射报告
`resource/dan_courses.mapping.json`；尚未进入评级曲库的新曲（如 2026 届《鈍響ライクリフド》）
会记为 `not_in_chart_resource`，等曲库更新后重跑即可自动映射。

### 重新构建评价门槛数据

从谱面 wiki 抓取每曲天井スコア / 極スコア / 必要連打打数，并与谱面库按曲名匹配（构建期联网，运行期只读本地压缩资源）：

```bash
python scripts/build_score_rank.py
```

## 参考

- 插件开发指南：https://docs.astrbot.app/dev/star/plugin-new.html
- AI / LLM 工具：https://docs.astrbot.app/dev/star/guides/ai.html
- 评级公式：https://github.com/OurTaiko/taiko-rating-analyzer
- 谱面特征：taiko-star-rating-system-cal-by-ai（AI v2 / Taiko Signal Rhythm v2）
- 配点与天井スコア / 極スコア：[太鼓の達人 譜面とか Wiki · 配点](https://wikiwiki.jp/taiko-fumen/システム/配点)、[極スコア表(おに)](https://wikiwiki.jp/taiko-fumen/作品/新AC/極スコア/おに)
