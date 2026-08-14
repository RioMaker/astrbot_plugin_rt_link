# 菌菌成绩数据字段含义（hiroba 风格）

数据来源：`GET /api/v1/scores/hiroba`（鉴权 `Authorization: Bearer <tk_...>`）。
字段含义以官方 API 指南「第 4 节 · 兼容成绩端点 · 公共成绩字段」为准（已核对）。
完整快照暂存于 `cache/scores_hiroba.json`（**不入 git**）。

---

## 顶层 `data.playedRecords`

| 字段 | 含义 |
| --- | --- |
| `userid` | 玩家 ID（字符串；国服为纯数字，日服可能以 `0` 开头） |
| `server` | 服务器：`cn` 国服 / `jp` 日服 / `custom` 虚拟账号 |
| `scoreInfo` | 成绩数组，每个元素 = 某首歌某个难度的成绩 |

---

## 公共成绩字段（`scoreInfo[]` 每条）

| 字段 | 类型 | 官方含义 |
| --- | --- | --- |
| `song_no` | integer | 游戏侧歌曲 ID |
| `level` | integer | 难度，1–5 对应 Easy、Normal、Hard、Mania、Ura（见下方难度映射） |
| `high_score` | integer | 最高分 |
| `best_score_rank` | integer | 最高分评价等级 |
| `good_cnt` | integer | 良数量 |
| `ok_cnt` | integer | 可数量 |
| `ng_cnt` | integer | 不可数量 |
| `pound_cnt` | integer | 连打数量 |
| `combo_cnt` | integer | 最大连击数 |
| `option_flg` | array | 演奏选项 |
| `tone_flg` | array | 音色数据 |
| `stage_cnt` | integer | 游玩次数 |
| `clear_cnt` | integer | 通关次数 |
| `full_combo_cnt` | integer | 全连次数 |
| `dondaful_combo_cnt` | integer | 全良次数（即「咚大福」） |
| `highscore_datetime` | string 或 null | 最高分时间，格式 `YYYY-MM-DD HH:mm:ss` |
| `highscore_mode` | integer | 最高分模式标记 |
| `update_datetime` | string 或 null | 快照更新时间，格式 `YYYY-MM-DD HH:mm:ss` |

> 备注：实测部分记录额外含 `kinoko_id`（菌菌内部歌曲 ID），官方「公共成绩字段」表未列出，属接口额外字段。

---

## `song_detail{}` 歌曲信息（hiroba 独有）

| 字段 | 类型 | 官方含义 |
| --- | --- | --- |
| `id` | integer | 游戏侧歌曲 ID；缺少曲库资料时为 `-1` |
| `type` | string | 分区名称（J-POP、アニメ、ナムコオリジナル 等） |
| `genreType` | integer | 分区 ID |
| `song_name_jp` | string | 日文标题 |
| `song_name` | string | 官方标注「中文标题，缺失时回退日文标题」；**实测返回为罗马字/英文标题**（如 `Natsumatsuri`、`Tokyo Shandy Rendezvous`） |
| `subtitle` | string | 中文副标题 |
| `level_1` ~ `level_5` | integer 或 string | 五个难度的星级；缺失时为 `"-"` |
| `sort` | integer | 兼容字段 |
| `open_day` | string | 兼容字段 |
| `isPlayed` | boolean | 兼容字段，当前为 `true` |

---

## 难度映射（太鼓达人，从低到高）

| level | 官方英文 | 名称 |
| --- | --- | --- |
| 1 | Easy | 梅（简单） |
| 2 | Normal | 竹（一般） |
| 3 | Hard | 松（困难） |
| 4 | Mania | 魔王 |
| 5 | Ura | 里魔王 |

> 约定：返回给 agent / LLM 的成绩文本中，难度一律以「难度N·名称」注明，
> 例如「难度4·魔王：1005660 评分8｜…」。

---

## 附：`#同步状态字段` 说明

官方文档中的「同步状态字段」属于**第 8 节 · 玩家同步**，是 `POST /players/{bind_id}/sync` 与
`GET /players/{bind_id}/sync-status` 的响应结构，**与成绩数据无关**，且只接受 `oa_`（OAuth）令牌，个人 `tk_` API Key 不可用：

| 字段 | 说明 |
| --- | --- |
| `schema_version` | 当前为 `1` |
| `bind.bind_id` | 绑定 ID |
| `bind.server` | `cn` / `jp` / `custom` |
| `bind.player_id` | 玩家 ID |
| `update_status.status` | `idle` / `queued` / `running` / `completed` / `failed` |
| `update_status.message` | 可向用户显示的脱敏状态信息 |
| `update_status.started_at` | 开始时间（UTC ISO 8601） |
| `update_status.finished_at` | 完成时间（UTC ISO 8601） |
