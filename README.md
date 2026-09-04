# astrbot_plugin_rt_link

将 NapCat 对话中的 QQ 号绑定到「菌菌控制台」的 apikey，据此查询太鼓达人指定曲目的成绩，并以 **AI v2 Rating**（Taiko Signal Rhythm v2）评估玩家实力，结合 AI 识别的节奏型画像给出「该练什么 + 参考曲目」建议。

## 功能

- 绑定管理：`bind` / `unbind` / `list`（管理员）
- 成绩查询：按曲名/别名模糊匹配（中文/日文/英文）
- **难度筛选**：支持难度别名（鬼/魔王/里/里魔王/松/困难/竹/一般/梅/简单）与组合名（如「鬼夏祭」「里夏祭」）
- **歌曲别名**：两步确认（发起 → 管理员审核），审核通过后可用别名查询
- **玩家实力评级**：综合 Rating + 七维能力（谱面底力/持续耐力/爆发手速/击打精度/配置处理/节奏适应/读谱）+ 强项/弱项
- **实力画像图片**：`/rtlink rating` 或 AI 工具 `generate_rating_image` 在插件本地生成 `1440 × 2720` PNG 报告（Rating 环 + 能力星系 + 强弱项 + 表现证据 + 冷门配置观察）
- **个人画像图片**：`/rtlink profile` 输出 `1440 × 1800` PNG，集中展示 Rating、七维轮廓、强弱项、全连/全良与代表谱面
- **节奏型弱项图片**：`/rtlink weakness` 输出 `1440 × 2200` PNG；按「节奏型 × BPM 档」给出核心短板、练习路径和参考曲目
- **冷门配置分组**：内置谱面库覆盖率低于 3% 的节奏配置单列观察，不进入核心弱项排行
- **成长记录**：每次获取 Rating 或执行 `/rtlink update` 都会追加一份轻量历史快照，完整保留七维、全部常见/冷门节奏配置，以及算法和谱面库版本
- **完整帮助长图**：`/rtlink help` 或 `/rtlink 帮助` 返回同一张说明图片，包含菌菌 apikey 四步绑定实图、常用指令、评级与安全说明
- LLM 工具：注册多个查询工具，模型可在自然对话中自动调用
- **AI 段位资料查询**：LLM 工具 `query_dan_course` 可按年份、区域、段位、曲名或 `song_no` 查询 2022–2025 日版/国际版与国服课题曲、条件和来源
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
/rtlink profile                             生成个人强项/弱项画像图片
/rtlink weakness                            生成节奏型弱项与练习建议图片（冷门配置单列）
/rtlink alias <ID或曲名> <别名>              申请歌曲别名（待管理员审核）
/rtlink help                                查看帮助
/rtlink 帮助                                查看同一张完整帮助长图
/rtlink about                               查看插件信息

裸 `/rtlink`（不带子命令）默认返回实力画像图片，等价于 `/rtlink rating`。

管理员指令不在此列出，完整指令（含管理员）见 [docs/commands.md](docs/commands.md)。
```

也可以直接自然语言询问，例如：「可可子，我的实力怎么样」「可可子，我该练什么」「可可子，2025 国服十段是什么」「可可子，《天狗囃子》出现在哪届段位」。

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
- 每份快照记录 `algorithmVersion`、`catalogVersion` 和 `catalogSchemaVersion`；后续算法升级后可按版本区间标注曲线，避免把算法变化误判为玩家进步。

## 目录结构

```
astrbot_plugin_rt_link/
├── main.py             # 插件入口（Star 类 + 命令 + LLM 工具）
├── dan_query.py        # 段位资料查询与 LLM 文本格式化
├── rating.py           # 玩家 Rating 算法（AI v2 主 + OurTaiko-v1 参考 + 节奏型画像）
├── report_image.py     # 与鼓迹网站同源版式的固定像素 Pillow 渲染器
├── profile_image.py    # /rtlink profile 玩家画像渲染器
├── weakness_image.py   # /rtlink weakness 弱项渲染器（冷门配置单列）
├── help_image.py       # /rtlink help 完整说明长图渲染器
├── storage.py          # SQLite 成绩、Rating 历史快照与空间计量
├── service.py          # 核心服务（绑定/同步/评级/查询）
├── api_client.py       # 菌菌公开 API 客户端（标准库实现）
├── resource/           # 谱面与段位道场静态资源（压缩 JSON + manifest）
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
python scripts/build_dan_courses.py
```

## 参考

- 插件开发指南：https://docs.astrbot.app/dev/star/plugin-new.html
- AI / LLM 工具：https://docs.astrbot.app/dev/star/guides/ai.html
- 评级公式：https://github.com/OurTaiko/taiko-rating-analyzer
- 谱面特征：taiko-star-rating-system-cal-by-ai（AI v2 / Taiko Signal Rhythm v2）
