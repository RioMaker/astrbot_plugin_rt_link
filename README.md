# astrbot_plugin_rt_link

将 NapCat 对话中的 QQ 号绑定到「菌菌控制台」的 apikey，据此查询太鼓达人指定曲目的成绩，并以 **AI v2 Rating**（Taiko Signal Rhythm v2）评估玩家实力，结合 AI 识别的节奏型画像给出「该练什么 + 参考曲目」建议。

## 功能

- 绑定管理：`bind` / `unbind` / `list`（管理员）
- 成绩查询：按曲名/别名模糊匹配（中文/日文/英文）
- **难度筛选**：支持难度别名（鬼/魔王/里/里魔王/松/困难/竹/一般/梅/简单）与组合名（如「鬼夏祭」「里夏祭」）
- **歌曲别名**：两步确认（发起 → 管理员审核），审核通过后可用别名查询
- **玩家实力评级**：综合 Rating + 七维能力（谱面底力/持续耐力/爆发手速/击打精度/配置处理/节奏适应/读谱）+ 强项/弱项
- **实力画像图片**：`/rtlink rating` 或 AI 工具 `generate_rating_image` 生成 PNG 报告（Rating 环 + 七维雷达 + 强弱项 + 表现证据）
- **节奏型弱项**：按「节奏型 × BPM 档」给出短板与参考曲目
- LLM 工具：注册多个查询工具，模型可在自然对话中自动调用
- 本地存储：SQLite 持久化菌菌 hiroba/kinoko 同步数据（转义落库，关键信息不缺失）
- 空间监管：`/rtlink storage` 查询用量，接近配额自动提醒管理员

## 命令

```
/rtlink bind <apikey> <player_id> [server]  绑定当前 QQ（server 默认 cn，仅私聊）
/rtlink unbind                              解绑当前 QQ
/rtlink score <曲名|别名|鬼夏祭>             查询指定曲目成绩（支持难度前缀组合名）
/rtlink rating                              生成实力画像图片
/rtlink profile                             查看强项/弱项画像
/rtlink weakness                            查看节奏型弱项与参考曲目
/rtlink alias <ID或曲名> <别名>              申请歌曲别名（待管理员审核）
/rtlink help                                查看帮助
/rtlink about                               查看插件信息

管理员指令不在此列出，完整指令（含管理员）见 [docs/commands.md](docs/commands.md)。
```

也可以直接自然语言询问，例如：「我的实力怎么样」「我该练什么」「我的《夏祭り》成绩是多少」。

## 难度筛选与别名

- 难度别名：`鬼/魔王/4`、`里/里鬼/里魔王/5`、`松/困难/3`、`竹/一般/2`、`梅/简单/1`（仅鬼/里参与评级）。
- 组合名：查询时可用「鬼夏祭」「里夏祭」这类「难度前缀 + 曲名」写法。
- 歌曲别名：`/rtlink alias <ID或曲名> <别名>` 发起（返回歌曲 ID/名称等信息供确认），管理员用 `/rtlink aliaslist` 查看、`/rtlink aliasapprove` 批量通过；通过后即可用别名查询。
- LLM 工具 `set_song_alias` 支持让模型代用户发起别名设置；查询工具 `query_taiko_score` / `search_scores` 支持 `level` 难度参数与别名。

## 评级说明

- 主 Rating 采用 **AI v2**（Taiko Signal Rhythm v2），参考 OurTaiko-v1 公式（MIT，来源 [OurTaiko/taiko-rating-analyzer](https://github.com/OurTaiko/taiko-rating-analyzer)）。
- **仅评估鬼/里（魔王/里魔王）谱面**，1–3 难度无谱面定数，不参与评级。
- 谱面元数据打包在 `resource/charts.v1.json.gz`（1393 张，覆盖 95% 谱面）。

## 目录结构

```
astrbot_plugin_rt_link/
├── main.py             # 插件入口（Star 类 + 命令 + LLM 工具）
├── rating.py           # 玩家 Rating 算法（AI v2 主 + OurTaiko-v1 参考 + 节奏型画像）
├── storage.py          # SQLite 存储层 + 空间计量
├── service.py          # 核心服务（绑定/同步/评级/查询）
├── api_client.py       # 菌菌公开 API 客户端（标准库实现）
├── resource/           # 谱面元数据（charts.v1.json.gz + manifest）
├── test_api.py         # API 连通性测试（读取 apikey.key）
├── metadata.yaml       # 插件元数据
├── _conf_schema.json   # WebUI 配置项
├── docs/
│   ├── agent-tasks.md  # 开发任务清单
│   └── data-fields.md  # 菌菌成绩数据字段含义
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

## 参考

- 插件开发指南：https://docs.astrbot.app/dev/star/plugin-new.html
- AI / LLM 工具：https://docs.astrbot.app/dev/star/guides/ai.html
- 评级公式：https://github.com/OurTaiko/taiko-rating-analyzer
- 谱面特征：taiko-star-rating-system-cal-by-ai（AI v2 / Taiko Signal Rhythm v2）
