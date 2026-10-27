# astrbot_plugin_rt_link

将 NapCat 对话中的 QQ 号绑定到「菌菌控制台」的 apikey，据此查询太鼓达人指定曲目的成绩，并以 **AI v2 Rating**（Taiko Signal Rhythm v2）评估玩家实力，结合 AI 识别的节奏型画像给出「该练什么 + 参考曲目」建议。

## v0.18.0 评分规则

单谱 Rating 以该谱固定 AI 定数为上限，只有全良精度能达到定数。精度到 Rating 沿用按难度变化的非线性曲线，经过全良归一化与难度单调修正；没有重新训练或修改谱面定数。综合 Rating 量表上限同步改为 11.6，七维与配置评分重新计算。旧模型与新模型的 Rating 不直接判定涨跌，首次同步重建基线，最高分比较和历史原始成绩保留。OurTaiko-v1 参考算法保持原值。详见 [R2 评分规则与迁移](docs/rating-r2-constant-cap.md)。

## 功能

- 绑定管理：`bind` / `unbind` / `list`（管理员）
- 成绩查询：按曲名/别名模糊匹配（中文/日文/英文）
- **曲名别名索引**：内置别名表收「国服曲名 + 日文曲名 + 罗马字（ESE 谱面）+ 人工整理简称/黑话」，段位查询、查分、别名申请共用同一套匹配；`北埼玉`、`六天`、`罗特`、`顿卡马`、`天狗囃子` 这类叫法都能直接查到
- **难度筛选**：支持难度别名（鬼/魔王/里/里魔王/松/困难/竹/一般/梅/简单）与组合名（如「鬼夏祭」「里夏祭」）
- **歌曲别名**：两步确认（发起 → 管理员审核），审核通过后可用别名查询
- **玩家实力评级**：综合 Rating + 七维能力（谱面底力/持续耐力/爆发手速/击打精度/配置处理/节奏适应/读谱）+ 强项/弱项
- **单人分支成绩**：已核对的分支按实际音符数选择对应 AI 画像；同音符数存在不同路径时继续拒绝评级，不套用达人分支定数。详见[分支音符数核验与修正](docs/branch-note-audit-2026-10-16.md)。
- **实力画像图片**：`/rtlink rating` 在插件本地生成 `1440 × 2720` PNG 报告（Rating 环 + 能力星系 + 强弱项 + 表现证据 + 冷门配置观察）
- **个人画像图片**：`/rtlink` 或 `/rtlink profile` 输出宽 1440 的自适应长图：分段配色 Rating 环、互斥评价/皇冠统计、能力行星、配置评分概览、带皇冠和实际评价图标的 BEST 20、最多 8 首提升建议。表/里按独立谱面排序；BEST 20 的里谱保留淡色水印。提升建议采用双列卡片，区分当前与目标评价、最高分与目标分，以及判定/黄条连打补分参考；魔王和里魔王分别显示粉色与紫色难度图标。
- **配置评分详情**：`/rtlink progress` 展示 18 种配置 × 7 个 BPM 档的评分、理论满分与样本。满分由全曲库全良按同一算法计算；不足 3 个计分样本保留空值。积累至少两次有效同步后显示同版本历史曲线。
- **节奏型弱项图片**：`/rtlink weakness` 输出 `1440 × 2200` PNG；按「节奏型 × BPM 档」给出核心短板、练习路径和参考曲目
- **提升评价候选**：`/rtlink improve [评价] [难度]` 输出 `1440 × 2020` PNG，按曲风分区列出「离目标评价最近」的谱面，并给出两条路线：判定（把几个「可」「不可」打成「良」，必要时标注「必须全良」）与连打（还差几打、补完这局黄条共几打、对应秒速，以及是否超出该谱連打理論値）；没有黄条的曲目会直接写明「只能靠判定」。子 Agent 内部使用 `recommend_practice(goal="score_rank")` 获取候选与补分路线
- **冷门配置分组**：内置谱面库覆盖率低于 3% 的节奏配置单列观察，不进入核心弱项排行
- **成长记录**：仅在成功同步且评分输入变化时保存，查看图片/文本不会重复记点。新配置历史按玩家、服务器、数据源、算法和资源版本隔离，压缩保存计算输入与全部配置状态；谱面资源按哈希共享归档。
- **完整帮助长图**：`/rtlink help` 或 `/rtlink 帮助` 返回同一张说明图片，包含菌菌 apikey 四步绑定实图、常用指令、评级与安全说明
- LLM 工具：仅向主 AI 注册 `query_rtlink(question)`；临时子 Agent 在独立上下文内组合只读查询，主 AI 只收到简短概述和最终结论
- **段位道场查询**：`/rtlink dan [年份] [区域] [段位] [曲名]`（或 `/rtlink 段位 …`）查 2022–2026 日版/国际版与国服课题曲、普通/金合格条件、开放时间与来源；按曲名反查时同时给出国服名、日文名与 RTLink 曲目 ID，支持「鬼 天竺2000」这样带难度前缀
- **公开段位资料查询**：临时子 Agent 使用 `query_dan_course` 按曲名、别名或歌曲 ID 反查段位；主 AI 只需提交查询目标，无需绑定账号，与 `/rtlink dan` 使用同一套资料
- **AI 过段能力参考**：子 Agent 使用 `evaluate_player_dan` 核对课题最佳成绩与条件，并明确标注魂槽及连续演奏无法验证
- 本地存储：SQLite 持久化全部 1–5 难度成绩；当前最佳、同步批次、去重变化历史分表保存，原始字段完整保留
- 空间监管：`/rtlink storage` 查询用量，接近配额自动提醒管理员

## 命令

支持菌菌与 Sakura 分别绑定、独立保存成绩和历史。私聊发送 `/rtlink bind sakura <token>` 绑定 Sakura；`/rtlink source` 查看当前来源，`/rtlink source kinoko` 或 `/rtlink source sakura` 切换。绑定成功后自动选择该来源；`unbind` 只解绑当前来源。旧菌菌绑定与数据库原样沿用。详见 [多来源成绩与独立存储](docs/data-sources.md)。

```
/rtlink bind <apikey> <player_id> [server]  绑定当前 QQ（server 默认 cn，仅私聊）
/rtlink unbind                              解绑当前 QQ
/rtlink score <曲名|别名|鬼夏祭>             查询指定曲目成绩（支持难度前缀组合名）
/rtlink rating                              生成实力画像图片
/rtlink update                              跳过缓存，从当前来源拉取并记录历史快照
/rtlink profile                             生成个人 Profile（使用有效缓存）
/rtlink progress                            查看全部配置评分、理论满分、样本与历史曲线
/rtlink weakness                            生成节奏型弱项与练习建议图片（冷门配置单列）
/rtlink improve [评价] [难度]                生成「提升评价」图片（分区列出最接近目标的谱面）
/rtlink <评价> [难度]                        等价于 /rtlink improve，省略 improve 的简写
/rtlink dan [年份] [区域] [段位] [曲名]       查段位道场课题曲、合格条件与来源（支持曲名别名）
/rtlink alias <ID或曲名> <别名>              申请歌曲别名（待管理员审核）
/rtlink help                                查看帮助
/rtlink 帮助                                查看同一张完整帮助长图
/rtlink about                               查看插件信息

裸 `/rtlink`（不带子命令）先执行与 `/rtlink update` 相同的强制同步，成功后返回个人画像；同步失败时返回错误提示。`/rtlink profile` 保留有效缓存读取行为。原详细实力报告保留在 `/rtlink rating`。
评价简写示例：`/rtlink 金雅`、`/rtlink 紫雅 鬼`、`/rtlink 极`。
国服段位资料已更新至 2026-10-14 开放的五级～十段；人字段尚未确认。资料来源与重算记录见 [本次维护说明](docs/data-refresh-2026-10-14.md)。

段位查询示例：`/rtlink dan 2025 十段`、`/rtlink dan 十段 国服`、`/rtlink dan 六天`、`/rtlink dan 鬼 天狗囃子`。

管理员指令不在此列出，完整指令（含管理员）见 [docs/commands.md](docs/commands.md)。
```

也可以直接自然语言询问，例如：「可可子，我的实力怎么样」「可可子，推荐 5 首练精度的歌」「可可子，推荐我没玩过的练习曲」「可可子，夏祭的成绩和配置怎么样」「可可子，评估我过 2025 国服十段的条件」。

## AI 检索能力

v0.20.0 主 AI 只看到 `query_rtlink(question)`。识别太鼓达人查询需求后，主 AI 提交目标及必要条件，插件创建临时查询子 Agent，查询结束后只返回最终概述和结论；主 AI 不再接收原始查询 JSON、调用链或思考过程。旧的 `queries/export` 参数及其余五个独立 AI 入口不再向主 AI 提供；全部 20 个已有只读查询和 2 个状态查询仍供子 Agent 内部使用。手动命令保持可用。

子 Agent 固定使用当前群聊/会话已经使用的同一模型通道，不配置其他提供商。它只接收查询目标、太鼓达人前置知识和本次必要资料；不继承主 AI 人格、群聊历史、图片或其他工具。使用受限 JSON 查询协议执行只读函数，规划、查询材料和修正都留在临时内存，不写入 AstrBot 会话历史，也不自动导出中间附件。

整个临时查询固定开始时的数据源和绑定，跨批复用同一份玩家分析结果，失败的同步也不重复尝试。一个子查询失败不影响其他项；不允许指定其他玩家、读取凭据或调用写入方法。公开段位和谱面查询无需绑定。

`recommend_practice` 一次返回必要玩家背景、5 首候选、逐曲依据和练习目标。支持综合练习、节奏补弱、精度、全连、评价提升和未玩曲探索。符合条件不足 5 首时明确说明，不凑数；不要求 AI 先查画像或逐曲补查。

推荐使用本地成绩与预计算配置，无额外模型调用。一般练习以该难度前 20 张成绩的谱面定数中位数为锚点，筛选其 −1.5～+0.5 的谱面；这是训练启发式。未玩曲还必须有配置匹配及已玩参考曲，排除已玩但未评级、原始同步数据已有记录及路线未经确认的分支谱面。评价提升沿用现有门槛与判定/连打算法，保留估算或资料不足的标记，不把差距直接当成成功率。

单条消息最多触发两次不同的临时查询，通常一次即可；子 Agent 内部的规划和多批取数不重复消耗主入口预算。默认最多 4 轮模型请求、180 秒总超时，每批最多组合 24 项查询。最后一轮只允许最终结论；格式错误或无查询依据的回答不会直接返回给主 AI。

上下文上限默认 **200000 tokens（0.2M）**，可在 AstrBot 插件配置中修改。每次模型请求发送前，使用 UTF-8 字节作保守 token 上界估算，计入领域说明、问题、查询材料、协议开销和输出预留；材料过长会截断并在结论中标注，仍超限则停止。它是本地输入上下文约束，不是各轮计费 tokens 的累计限额；提供商内部隐藏前缀不在本地估算内。

返回格式可选 `image`（默认）、`text`、`both`。图片使用临时 `paper_v1` 纸色卡片模板，展示标题、最终结论、数据项、来源和必要说明；图片模式下主 AI 只得到最多 160 字概述及发送状态，发送失败会降级为最终文字。仅最终 PNG 保存在数据目录 `query_results/`，按用户保留最近 5 张；不保存子 Agent 上下文或推理。 [临时模板预览](docs/query-result-paper-v1.png)。

子 Agent 可组合多曲成绩、指定小节、历史、筛选和段位查询；检索/谱面仍遵守 `limit/offset`，推荐仍最多 5 首，不表示已查询全库或全部历史。完整内部函数清单和配置见 [命令与 AI 工具说明](docs/commands.md)。公共 TJA 数据包见 [公共 TJA 分析库](docs/chart-library.md)。

## 难度筛选与别名

- 难度别名：`鬼/魔王/4`、`里/里鬼/里魔王/5`、`松/困难/3`、`竹/一般/2`、`梅/简单/1`（仅鬼/里参与评级）。
- 组合名：查询时可用「鬼夏祭」「里夏祭」这类「难度前缀 + 曲名」写法。
- 歌曲别名：`/rtlink alias <ID或曲名> <别名>` 发起（返回歌曲 ID/名称等信息供确认），管理员用 `/rtlink aliaslist` 查看、`/rtlink aliasapprove` 批量通过；通过后即可用别名查询。
- AI 单曲入口 `query_song_brief` 支持难度参数、内置及已审核别名；别名申请继续使用 `/rtlink alias`。

## 评级说明

- 主 Rating 采用 **AI v2**（Taiko Signal Rhythm v2），参考 OurTaiko-v1 公式（MIT，来源 [OurTaiko/taiko-rating-analyzer](https://github.com/OurTaiko/taiko-rating-analyzer)）。
- **仅评估鬼/里（魔王/里魔王）谱面**，1–3 难度无谱面定数，不参与评级。
- 谱面元数据打包在 `resource/charts.v1.json.gz`（1421 张，其中 1413 张有 AI v2 定数）。2026-10-16 补算了 86 张已核对的国服单人谱；双打、需 P1 映射复核及缺 TJA 的谱面未估填，见[逐谱审计](docs/cn-constant-backfill-2026-10-16.html)。
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
  「極スコア要求連打速度」交叉校验；覆盖 96.5% 谱面）。
- 「极」要求的连打速度通常落在 **16.6 ~ 18 打/秒**，所以结果里超过 30 打/秒时会额外提示偏高。
- **没有黄条的谱面**（库里 131 张只有风船、108 张连风船都没有）无法靠连打补分，只能走判定路线；
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

- 全部写法打包在 `resource/aliases.v1.json.gz`（1524 首、1849 个鬼/里身份、6853 条写法），
  由 `scripts/build_aliases.py` 合并「国服公开曲库 + 菌菌曲库 + ESE 谱面 + 段位资料 + 人工别名表」生成；
  人工整理部分在 [`scripts/data/song_aliases.json`](scripts/data/song_aliases.json)，可直接编辑后重跑脚本。
- 段位查询、`/rtlink score`、成绩检索 `search_scores`、别名申请解析共用这张表；
  用户通过 `/rtlink alias` 提交且审核通过的别名优先级更高。
- 详细规则、来源与维护方式见 [docs/song-aliases.md](docs/song-aliases.md)。
- [完整可搜索审核表](docs/song-alias-audit-2026-10-14.html)包含逐名来源、全部冲突与段位映射；国服名优先显示，未评级新歌也可按真实 ID 查询。

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
- 依赖为 `Pillow>=10.0`，与 AstrBot Core 的版本约束共同解析；已验证 `Pillow 12.3.0`，无需降级核心依赖。
- 固定输出 `1440 × 2720` PNG，并使用随插件打包的 `resource/NotoSansCJKsc-Regular.otf`，避免服务器缺少中文字体时出现方框、乱码或平台间排版漂移。
- 数据摘要、颜色、分区层级、Rating 环、能力星系、诊断卡和证据表均与「鼓迹」网站的导出报告保持一致。
- 每次生成使用新的文件名，避免 QQ/AstrBot 复用旧图片缓存；同一用户、同一图片类型仅保留最近 3 张。
- 推荐卡片的难度素材沿用用户已有的「鼓迹」网站原图：`resource/profile/oni.png` 对应魔王，`ura.png` 对应里魔王（与网站的 `li_oni.png` 原图一致）。图标未经重绘，不另行声明独立开源许可。

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
`resource/dan_courses.mapping.json`；曲目身份同时读取独立公开名称快照。尚无评级数据的新曲
（如 2026 十段 ID 1502/1503）标为 `catalog_verified_unrated`，可以查名称与谱面分析，保留未评级提示。

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
