# rt_link 全部指令说明

> `/rtlink help` 只显示普通用户指令，**不显示管理员指令**。管理员指令全部列在本文档。

**裸 `/rtlink`（不带子命令）默认返回实力画像图片**，等价于 `/rtlink rating`。

---

## 普通用户指令

| 指令 | 说明 | 示例 |
| --- | --- | --- |
| `/rtlink bind <apikey> <player_id> [server]` | 绑定当前 QQ 到菌菌账号（**仅私聊**）。`server` 默认 `cn`，可选 `cn`/`jp`/`custom` | `/rtlink bind tk_xxx 30053354 cn` |
| `/rtlink unbind` | 解绑当前 QQ | `/rtlink unbind` |
| `/rtlink score <曲名\|别名\|鬼夏祭>` | 查询指定曲目成绩；支持难度前缀组合名（`鬼夏祭`→鬼难度+夏祭）与别名（国服名/日文名/罗马字/常用简称） | `/rtlink score 鬼夏祭`、`/rtlink score 六天` |
| `/rtlink dan [年份] [区域] [段位] [曲名]` | 查段位道场课题曲、普通/金合格条件、开放时间与来源。参数顺序不限，均可省略：只给曲名时反查该曲出现过的段位；只给年份+段位时列出完整三曲。曲名支持别名，也可写「鬼 天竺2000」限定难度 | `/rtlink dan 2025 十段`、`/rtlink dan 十段 国服`、`/rtlink dan 六天` |
| `/rtlink 段位 …` | 上一条的中文写法 | `/rtlink 段位 2024 达人` |
| `/rtlink rating` | 生成完整实力画像图片（Rating 环 + 七维能力 + 强弱项 + 表现证据 + 冷门配置观察） | `/rtlink rating` |
| `/rtlink update` | 跳过缓存，立即从菌菌重新拉取成绩、计算 Rating 并追加历史快照 | `/rtlink update` |
| `/rtlink profile` | 生成个人画像图片：Rating、七维、强项/弱项、全连/咚大福与代表谱面 | `/rtlink profile` |
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

| 工具名 | 作用 | 参数 |
| --- | --- | --- |
| `query_taiko_score` | 查指定歌曲成绩/Rating（支持别名、难度前缀组合名） | `song_name`（必填）、`level`（难度别名，可选） |
| `search_scores` | **通用检索**：任意条件组合查成绩／谱面库（见下方参数表） | 见下方 |
| `get_song_full` | 查指定歌曲鬼/里全部难度 + 七维能力 | `song_name` |
| `get_player_rating` | 综合 Rating + 七维能力（文本） | 无 |
| `get_player_profile` | 实力画像文本（强项/弱项） | 无 |
| `get_rhythm_weakness` | 节奏型弱项与参考曲目 | 无 |
| `get_difficulty_stats` | 指定难度的统计 | `level`（int，0=鬼/里合计） |
| `get_rank_distribution` | 评价等级分布 | `level` |
| `get_genre_strength` | 各曲风强弱 | 无 |
| `get_accuracy_summary` | 精度概况 | `level` |
| `get_recent_scores` | 最近成绩 | `days`（默认 1） |
| `get_growth_trend` | 单曲成长趋势 | `song_name`（可选） |
| `get_improvement_candidates` | 「差一点全连/咚大福」清单 | `level` |
| `find_rank_improvements` | 「还差一点就能提升成绩评价」的曲目，按分区给出判定路线与连打路线（还差几打 / 总打数 / 秒速 / 是否打得出来；无黄条与必须全良会明确标注） | `target_rank`（可选，白粹/铜粹/银粹/金雅/粉雅/紫雅/极或 2-8）、`level`（可选） |
| `set_song_alias` | 发起歌曲别名设置（两步确认第一步） | `song`、`alias` |
| `query_dan_course` | 查段位道场课题曲、普通/金合格条件、开放时间与来源（曲名支持别名与难度前缀） | `year`、`region`、`rank`、`song_name`、`song_no`（均可省略） |
| `evaluate_player_dan` | 用玩家三首课题曲的最佳记录核对可计算的合格条件 | `year`、`rank`、`region`
| `generate_rating_image` | 生成实力画像图片并发送 | 无 |

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
- 每次使用裸 `/rtlink`、`/rtlink rating`、`/rtlink update` 或文本 Rating 工具，都会在 AstrBot 持久化数据目录追加快照；快照包含综合 Rating、七维、配置家族、全部节奏配置，以及算法/谱面库版本。未来绘制成长曲线时可按版本区间分段标注。

---

## `search_scores` 参数表

所有条件都是「且」的关系，全部可省略、可自由组合。

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
