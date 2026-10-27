# rt_link 全部指令说明

> `/rtlink help` 只显示普通用户指令，**不显示管理员指令**。管理员指令全部列在本文档。

**裸 `/rtlink`（不带子命令）先强制同步，再返回个人 Profile**。同步逻辑与 `/rtlink update` 相同，失败时返回错误提示；`/rtlink profile` 保留有效缓存读取行为。原详细实力报告保留在 `/rtlink rating`。

---

## 普通用户指令

| 指令 | 说明 | 示例 |
| --- | --- | --- |
| `/rtlink bind <apikey> <player_id> [server]` | 绑定当前 QQ 到菌菌账号（**仅私聊**）。`server` 默认 `cn`，可选 `cn`/`jp`/`custom` | `/rtlink bind tk_xxx 30053354 cn` |
| `/rtlink bind sakura <token>` | 绑定 Sakura（**仅私聊**），从接口核实玩家 ID，成功后选择 Sakura；保留菌菌绑定 | `/rtlink bind sakura <48位token>` |
| `/rtlink source [kinoko\|sakura]` | 查看或切换当前来源，成绩、缓存和历史独立保存 | `/rtlink source sakura` |
| `/rtlink unbind` | 解绑当前来源，保留历史与其他来源绑定 | `/rtlink unbind` |
| `/rtlink score <曲名\|别名\|鬼夏祭>` | 查询指定曲目成绩；支持难度前缀组合名（`鬼夏祭`→鬼难度+夏祭）与别名（国服名/日文名/罗马字/常用简称） | `/rtlink score 鬼夏祭`、`/rtlink score 六天` |
| `/rtlink dan [年份] [区域] [段位] [曲名]` | 查段位道场课题曲、普通/金合格条件、开放时间与来源（覆盖 2022–2026 日版/国际版，以及国服 2023/2024/2025，以及 2026 五级～十段）。参数顺序不限，均可省略：只给曲名时反查该曲出现过的段位；只给年份+段位时列出完整三曲。曲名支持别名，也可写「鬼 天竺2000」限定难度 | `/rtlink dan 2026 十段`、`/rtlink dan 十段 国服`、`/rtlink dan 六天` |
| `/rtlink 段位 …` | 上一条的中文写法 | `/rtlink 段位 2026 达人` |
| `/rtlink rating` | 生成完整实力画像图片（Rating 环 + 七维能力 + 强弱项 + 表现证据 + 冷门配置观察） | `/rtlink rating` |
| `/rtlink update` | 跳过缓存，立即从当前来源拉取成绩、计算 Rating 并追加历史快照 | `/rtlink update` |
| `/rtlink profile` | Rating 环、互斥评价/皇冠、能力行星、配置概览、BEST 20 与最多 8 首提升建议 | `/rtlink profile` |
| `/rtlink progress` | 全部 18 种配置 × 7 个 BPM 档的当前评分/理论满分、样本与同版本历史 | `/rtlink progress` |
| `/rtlink weakness` | 生成节奏型弱项图片：核心弱项排行、冷门配置观察、练习路径与参考谱面 | `/rtlink weakness` |
| `/rtlink improve [评价] [难度]` | 生成「提升评价」图片：按分区列出离目标评价最近的谱面，并给出判定路线（转几个「可」「不可」，是否必须全良）与连打路线（还差几打、总打数、秒速，是否打得出来；没有黄条的曲目直接标明）。评价与难度均可省略，评价默认取你最常拿到的评价的上一档 | `/rtlink improve 金雅`、`/rtlink improve 紫雅 鬼`、`/rtlink improve 5` |
| `/rtlink <评价> [难度]` | 上一条的简写，可以省略 `improve`。参数顺序不限；纯数字按「先评价、后难度」解析（`/rtlink 5 5` = 评价金雅 + 里谱面） | `/rtlink 金雅`、`/rtlink 紫雅 鬼`、`/rtlink 极 里` |
| `/rtlink alias <ID或曲名> <别名>` | 申请歌曲别名（返回歌曲信息确认，待管理员审核） | `/rtlink alias 夏祭り 夏祭` |
| `/rtlink help` / `/rtlink 帮助` | 返回包含绑定实图、指令、评级和安全说明的完整帮助长图 | `/rtlink 帮助` |
| `/rtlink about` | 查看插件信息 | `/rtlink about` |

## 管理员指令

| 指令 | 说明 | 示例 |
| --- | --- | --- |
| `/rtlink aliaslist` | 查看待审批别名清单 | `/rtlink aliaslist` |
| `/rtlink aliasapprove all\|<编号...>` | 批量通过别名审批 | `/rtlink aliasapprove all` 或 `/rtlink aliasapprove 1 2` |
| `/rtlink list` | 查看全部绑定 | `/rtlink list` |
| `/rtlink storage` | 查看存储用量（含回收空页提示） | `/rtlink storage` |
| `/rtlink cleanup` | 回收数据库空页（VACUUM） | `/rtlink cleanup` |

---

## LLM 工具（模型可自动调用）

v0.20.0 只向主 AI 注册一个入口，其他查询函数均在临时子 Agent 内使用。要求 AstrBot ≥4.5.7（使用官方 `llm_generate` 和当前会话模型接口）。

| 工具名 | 功能 | 参数 |
| --- | --- | --- |
| `query_rtlink` | 独立上下文查询太鼓达人成绩、能力、历史、谱面及段位，只回传最终结果 | `question`（1–4000字的目标及必要条件） |

例如主 AI 调用 `query_rtlink(question="六天出现在哪些年份和区域的段位？")`，或提交“比较夏祭和六天的成绩、配置，并判断我在2025国服十段课题曲上的短板”。无需主 AI 构造函数列表或先查概览。

临时子 Agent 固定使用当前会话已经使用的同一模型通道，不支持另选提供商。通过 AstrBot `llm_generate` 建立受限查询循环，每次传入空历史、专用系统说明和当前目标/资料，不继承群聊历史、人设、图片或其他工具。JSON动作协议只允许只读查询或最终结论，程序在内部执行函数，不把规划、原始返回、修正过程、推理或调用链交给主 AI，也不将这些内容写入会话历史。

每条消息最多触发两次不同的临时查询，通常一次即可；批内的多项查询、补查和最终总结只计一次主入口预算。子 Agent 全程锁定当前用户的数据源和绑定，跨批复用一次分析结果；其他用户查询保持独立。查询采用原有缓存/同步规则，必要时仍会更新缓存或历史快照。“只读”指不允许绑定、切换来源、改别名及其他业务写入操作。

### 插件配置

| 配置 | 默认 | 作用 |
| --- | --- | --- |
| `query_agent_context_tokens` | `200000` | 0.2M tokens上下文上限，可设8192–2000000 |
| `query_agent_max_rounds` | `4` | 2–12轮，包含规划和最终总结，最后一轮只允许最终结论 |
| `query_agent_timeout` | `180` | 10–600秒总超时，包括排队、模型请求和查询 |
| `query_agent_output_mode` | `image` | `image`发最终图片并给主AI短概述；`text`返回最终文字；`both`兼有 |
| `query_agent_image_template` | `paper_v1` | 临时纸色卡片模板，当前仅此模板 |

每次模型请求前，按UTF-8字节保守估算输入token上界，计入领域说明、目标、查询材料、2048单位协议预留和最多4096输出tokens；无法放入上限的材料会缩减并在最终结果说明，仍超限则停止。这不是精确分词统计或多轮计费总量；提供商隐藏前缀不在本地估算内。配置太小时，可能连必要的领域说明都无法容纳，插件会直接返回未完成状态而不发起模型请求。

子 Agent 自带难度1–5、表/里与分支、良/可/不可、全连/全良、单曲评价与段位的区别、区域/年度口径、记录缺失、TJA适用范围等前置知识。必须先查询再给结论，无依据、无绑定、资料缺失、截断或连续演奏无法验证时应明确说明。

图片仅含最终标题、结论、数据项、来源和必要说明；`image`模式下主AI只收到最多160字概述和发送状态。图片发送失败时回退到最终文字。最终PNG位于插件数据目录`query_results/`，每个用户保留最近5张，不保存子Agent上下文。旧的`queries/export`参数不再属于主AI入口，也不自动发送原始JSON附件。

### 子 Agent 内部只读函数清单

下面全部20个已有只读查询和2个状态查询供子 Agent 使用，方法名不单独向主AI注册。每个内部批次最多24项，可以多曲、多难度、多年度或多偏移组合；相同参数在批内复用。`completed`只表示方法执行成功，子Agent仍必须读返回内容中的错误、缺数据提示或谱面status。

| 子查询名 | 内容 | 参数 |
| --- | --- | --- |
| `get_player_overview` | 玩家概览、主要弱项和证据 | 无 |
| `get_player_rating` | Rating、七维能力、覆盖谱面 | 无 |
| `get_player_profile` | 强弱项、全连/全良与七维能力 | 无 |
| `get_rhythm_weakness` | 常见节奏弱项及冷门配置观察 | 无 |
| `get_difficulty_stats` | 谱面数、全连率、均值与最高定数 | `level` 可选 |
| `get_rank_distribution` | 评价档数量与代表曲 | `level` 可选 |
| `get_genre_strength` | 曲风分区统计 | 无 |
| `get_accuracy_summary` | 平均精度、区间、最好/最差曲目 | `level` 可选 |
| `query_taiko_score` | 单曲成绩与 Rating | `song_name` 必填，`level` 可选 |
| `query_song_brief` | 单曲成绩和公共谱面摘要 | `song_name` 必填，`level` 可选 |
| `get_song_full` | 单曲鬼/里完整能力 | `song_name` 必填 |
| `search_scores` | 组合筛选、排序、门槛和补分路线 | 见下文自定义检索参数；`level` 支持 `4,5` |
| `get_recent_scores` | 最近更新的最佳成绩（非逐局游玩流水），最多 10 项 | `days` 可选，1–3650，默认 1 |
| `get_growth_trend` | 已存单曲历史成绩变化 | `song_name` 可选，默认 Rating 最高曲目 |
| `get_improvement_candidates` | 接近全连/全良的候选 | `level` 可选 |
| `find_rank_improvements` | 分区升评价候选与完整补分路线 | `target_rank`、`level` 可选 |
| `recommend_practice` | 5 首练习推荐及背景/依据 | `goal`、`level`、`target_rank`、`scope` 可选 |
| `get_chart_analysis` | TJA 整曲、指定小节或特征 | `song_name` 必填；`level`、`route`、`detail`、`start_measure`、`end_measure`、`limit`、`offset` 可选 |
| `query_dan_course` | 段位曲目、条件、歌曲反查 | `year`、`region`、`rank`、`song_name`、`song_no` 可选 |
| `evaluate_player_dan` | 用课题最佳成绩核对段位条件 | `year`、`rank` 必填，`region` 可选 |
| `get_library_status` | 公共谱面库和安装状态 | 无 |
| `get_source_status` | 当前数据源、绑定状态和服务器 | 无 |


`set_song_alias`与`generate_rating_image`不在子Agent白名单中；用户仍可通过原手动命令申请别名或生成报告。检索limit最多200，详细谱面limit最多20；分页、单曲最佳记录及原有推荐条数限制仍适用，最终结论不能声称覆盖未查询的结果。

内部协议示例（主AI无需构造）：

```json
{
  "action": "query",
  "queries": [
    {"tool": "get_rank_distribution"},
    {"tool": "get_accuracy_summary", "args": {"level": "鬼"}},
    {"tool": "query_dan_course", "args": {"song_name": "六天"}}
  ]
}
```

`recommend_practice`内部参数：`goal`为general/weakness/accuracy/full_combo/score_rank/explore；`level`为鬼/4或里/5；仅score_rank可用`target_rank`，explore用unplayed，精度/全连/升评价用played。最多推荐5首，不足时说明，不编造候选。原始谱面指标不能直接换算成个人精度或过关概率。

---

## 难度别名与组合名

| 难度 | 别名（数字/中文/英文） |
| --- | --- |
| 鬼（魔王） | `4` / `鬼` / `魔王` / `oni` / `mania` |
| 里鬼（里魔王） | `5` / `里` / `里鬼` / `里魔王` / `ura` |
| 松（困难） | `3` / `松` / `困难` / `hard` |
| 竹（一般） | `2` / `竹` / `一般` / `普通` / `normal` |
| 梅（简单） | `1` / `梅` / `简单` / `easy` |

- 组合名：查询时可写 `鬼夏祭`、`里夏祭`（难度前缀 + 曲名）。
- 曲名支持**别名**：国服名、日文名、罗马字（ESE 谱面）与人工整理的简称/黑话，
  例如 `六天`（第六天魔王）、`北埼玉`、`罗特`、`顿卡马`、`天狗囃子`。
  匹配规则与维护方式见 [song-aliases.md](song-aliases.md)。
- 仅鬼/里（4/5）参与评级，1–3 难度查询会提示「不在评级范围内」。
- 节奏配置按内置谱面库覆盖率分组；覆盖率低于 3% 的冷门配置不进入核心弱项排行，仅单列观察。
- 成功同步且评分输入变化时才写历史；查看图片或文本不会重复追加。新版配置历史按绑定玩家、服务器、数据源、算法和资源哈希隔离，不混用旧 BPM 档。`/rtlink progress` 显示最近 90 次有效同步，少于两次时提示等待更多记录。
- BPM 档：超慢速 `[0,110)`、慢速 `[110,140)`、常规 `[140,180)`、高速 `[180,220)`、超高速 `[220,280)`、急速 `[280,330]`、激光级 `>330`。分母为全曲库全良按相同配置算法计算的理论满分；无配置或计分样本不足显示 `—`。
- 配置表按当前评分 / 配置理论满分配色。BEST 20 分列单谱 Rating、固定 AI 定数与精度；表现配色按当前 Rating / 全良 Rating 上限沿用 50/60/70/80/90/95/100% 门槛，定数单独展示。评价图标仍取真实 `bestScoreRank`；全良皇冠产生淡彩虹边框，精度实际达到 100% 时精度文字才用彩虹色。同步升降只追踪最高分与玩家 Rating。

---

## 子 Agent 检索函数 `search_scores` 参数表

以下作为子 Agent 内部函数的开发参考；主 AI 不直接调用。所有条件都是「且」的关系，全部可省略、可自由组合。

### 匹配

| 参数 | 说明 |
| --- | --- |
| `query` | 关键词。可加难度前缀（`鬼夏祭`），可按 `match_mode` 分词 |
| `match_mode` | `contains`（包含，默认）/ `exact`（精确相等）/ `regex`（正则）/ `all`（空格分词全部命中）/ `any`（任一分词命中） |
| `match_fields` | `any`（曲名 + 日文名 + 分区 + 别名，默认）/ `title` / `titleJa` / `genre` / `alias` |
| `scope` | `played`（已有成绩并已评级，默认）/ `unrated`（打过但未参与评级）/ `unplayed`（没打过）/ `all`（全部谱面） |

### 筛选

| 参数 | 说明 |
| --- | --- |
| `level` | `4`/`鬼`/`魔王`、`5`/`里`/`里魔王`；多个用逗号，如 `4,5` |
| `genre` | 曲风分区关键词（`ナムコ`、`アニメ`、`J-POP`…） |
| `song_no` | 精确曲目 ID |
| `constant_min` / `constant_max` | 定数范围 |
| `rating_min` / `rating_max` | 单谱 Rating 范围 |
| `accuracy_min` / `accuracy_max` | 精度范围，可写 `0~1` 或 `0~100` |
| `score_min` / `score_max` | 分数范围 |
| `notes_min` / `notes_max` | 音符数范围 |
| `rank_min` / `rank_max` | 评价等级 1–8（1 无 / 2 白粹 / 3 铜粹 / 4 银粹 / 5 金雅 / 6 粉雅 / 7 紫雅 / 8 极） |
| `ok_min` / `ok_max` | 「可」数量范围；`ok_max=0` = 零「可」 |
| `ng_min` / `ng_max` | 「不可」数量范围；`ng_max=0` = 零「不可」 |
| `combo` | `full`（已全连）/ `no-fc`（未全连）/ `dondaful`（已全良）/ `no-miss`（零不可）/ `miss`（有不可） |
| `target_rank` | 目标评价；填了会给每条结果附上门槛、缺口、判定路线（转几个「可」「不可」，是否必须全良）与连打路线（还差几打 / 总打数 / 秒速 / 是否打得出来；无黄条会明确标注） |
| `reached` | `no`（只看未达成）/ `yes`（只看已达成） |
| `gap_max` | 距 `target_rank` 的最大分数缺口（填了会自动排除已达成） |

### 输出

| 参数 | 说明 |
| --- | --- |
| `sort` | `rating`（默认）/ `score` / `accuracy` / `constant` / `notes` / `gap` / `rank` / `updated` / `title` / `id`，也接受中文（`精度`、`分数`、`定数`…） |
| `order` | `desc`（默认）/ `asc` |
| `detail` | `brief`（默认，一行）/ `full`（附良/可/不可/连打/全连/全良与更新时间） |
| `limit` | 返回条数，默认 20，上限 200 |
| `offset` | 翻页偏移 |

**「不限」的写法**：下限用 `0`，上限用 `-1` 或直接省略；定数／Rating／精度／分数／音符数的上限传 `0` 也按「不限」处理。
`ok_max` / `ng_max` / `gap_max` 的 `0` 是有效条件，不会被忽略。

**示例**

```
query=夏, match_mode=all, levels=(5,)                     → 里谱面里同时含「夏」的曲目
ng_max=0, sort=accuracy, order=asc                        → 零不可里精度最低的
constant_min=10.5, constant_max=10.7, sort=accuracy       → 该定数段最需要提精度的
target_rank=紫雅, gap_max=3000, sort=gap, order=asc        → 差一点就能升到紫雅的
scope=unplayed, genre=ナムコ, sort=notes                   → 没打过的 Namco 曲，按音符数排
query=2000$, match_mode=regex                             → 曲名以 2000 结尾
```
