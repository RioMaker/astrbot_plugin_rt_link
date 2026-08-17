# rt_link 全部指令说明

> `/rtlink help` 只显示普通用户指令，**不显示管理员指令**。管理员指令全部列在本文档。

---

## 普通用户指令

| 指令 | 说明 | 示例 |
| --- | --- | --- |
| `/rtlink bind <apikey> <player_id> [server]` | 绑定当前 QQ 到菌菌账号（**仅私聊**）。`server` 默认 `cn`，可选 `cn`/`jp`/`custom` | `/rtlink bind tk_xxx 30053354 cn` |
| `/rtlink unbind` | 解绑当前 QQ | `/rtlink unbind` |
| `/rtlink score <曲名\|别名\|鬼夏祭>` | 查询指定曲目成绩；支持难度前缀组合名（`鬼夏祭`→鬼难度+夏祭）与别名 | `/rtlink score 鬼夏祭` |
| `/rtlink rating` | 生成实力画像图片（Rating 环 + 七维能力 + 强弱项 + 表现证据） | `/rtlink rating` |
| `/rtlink profile` | 文本画像：综合 Rating、七维、强项/弱项、全连/咚大福数 | `/rtlink profile` |
| `/rtlink weakness` | 节奏型弱项与参考曲目 | `/rtlink weakness` |
| `/rtlink alias <ID或曲名> <别名>` | 申请歌曲别名（返回歌曲信息确认，待管理员审核） | `/rtlink alias 夏祭り 夏祭` |
| `/rtlink help` | 查看帮助（仅普通指令） | `/rtlink help` |
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
| `search_scores` | 多条件检索成绩 | `query`、`level`、`constant_min`、`constant_max`、`rank_min`（均可选） |
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
| `set_song_alias` | 发起歌曲别名设置（两步确认第一步） | `song`、`alias` |
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
- 仅鬼/里（4/5）参与评级，1–3 难度查询会提示「不在评级范围内」。
