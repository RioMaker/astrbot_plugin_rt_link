# RTLink

<p><img src="logo.png" alt="RTLink 太鼓达人双鼓标志" width="128" height="128"></p>

RTLink 是 AstrBot 的太鼓达人成绩插件。支持菌菌和 Sakura 账号、单曲查分、个人画像、AI v2 Rating、练习推荐与段位道场查询。可可子可以在管理页绑定自己的独立游戏账号。

## 开始使用

在 AstrBot 插件管理中安装或更新 RTLink，重载插件。管理页需要支持 Plugin Pages 的宿主，最低版本见 [插件元数据](metadata.yaml)。

1. 在 QQ 私聊使用以下任一种绑定方式。菌菌的 `server` 可选 `cn`、`jp` 或 `custom`，省略时使用配置中的默认服务器。Sakura 由接口识别玩家。
2. 发送 `/rtlink` 强制同步当前来源，成功后生成个人画像。只想同步成绩时发送 `/rtlink update`。
3. 发送 `/rtlink score 鬼夏祭` 查单曲，或发送 `/rtlink help` 查看完整帮助长图。

```text
/rtlink bind <apikey> <player_id> [server]
/rtlink bind sakura <token>
```

两种来源可以同时绑定。绑定成功即选择该来源。`/rtlink source` 查看状态，`/rtlink source kinoko` 或 `/rtlink source sakura` 切换。`/rtlink unbind` 解绑当前来源并保留该来源的历史。请在私聊输入凭据；账号绑定与 AI 查询各用独立入口。详见 [多来源使用与存储](docs/data-sources.md)。

## QQ 指令

| 用途 | 指令 |
| --- | --- |
| 同步并生成个人画像 | `/rtlink` |
| 查看缓存可用时的个人画像 | `/rtlink profile` |
| 查看七维能力、强弱项和表现证据 | `/rtlink rating` |
| 查看 18 种配置在 7 个 BPM 档的评分、样本和历史 | `/rtlink progress` |
| 查看节奏型弱项与练习参考 | `/rtlink weakness` |
| 查看升评价的判定和连打路线 | `/rtlink improve 金雅 鬼` 或 `/rtlink 金雅 鬼` |
| 查段位课题曲及合格条件 | `/rtlink dan 2026 十段 国服` |
| 由歌曲反查段位 | `/rtlink dan 六天` |
| 查看公共谱面分析库的安装状态 | `/rtlink library` |
| 查看帮助 | `/rtlink help` 或 `/rtlink 帮助` |

命令参数、中文子指令、歌曲别名审批、存储管理和公共谱面库安装重试均见 [完整指令](docs/commands.md)。

## 可可子账号与 AI 查询

在 **AstrBot WebUI → 插件 → rt_link → 用户与可可子账号管理** 启用可可子的来源，也可搜索绑定用户、查看各来源的同步状态和当前 Rating。验证并保存后可手动同步、切换或解绑。操作详见 [账号管理说明](docs/account-management.md)。

- 「可可子，帮我查夏祭的成绩」「给我推荐 5 首练精度的歌」查询发言者的当前来源。
- 「可可子，你的 Rating 是多少」查询可可子的独立账号。比较双方时，各查一次，在结果里标明对象。
- 「六天属于哪些段位」「夏祭里谱的第 50 到 60 小节怎么配」可查公共资料。个人段位能力以课题曲最佳成绩为参考，实际参战和过段记录当前未接入。

模型注册六个只读入口。统一入口 `query_rtlink` 每次可组合最多 24 项查询，包含多曲对比、成绩筛选、同账号历史、谱面小节和段位资料；按需同步成绩，并在大结果时尝试发送 JSON 附件。每条消息最多执行两次不同查询。完整工具参数和示例见 [AI 查询说明](docs/commands.md#llm-工具模型可自动调用)。

## 数据与评分

玩家成绩按 QQ 或可可子身份、来源、游戏账号和服务器归属。菌菌与 Sakura 分别使用独立数据库并保留全部难度。当前最佳、同步批次、变化历史和 Rating 缓存分开保存。游戏账号换绑后，单曲成长查询只展示可确认属于当前账号与服务器的记录。详见 [数据来源与本地存储](docs/data-sources.md)及[菌菌成绩字段](docs/data-fields.md)。

| 内置资源 | 当前随插件提供的数据 |
| --- | --- |
| 评级谱面 | 1,421 张谱面，其中 1,413 张带 AI v2 特征。仅鬼和里魔王参与 Rating。已核验的单人分支按实际音符数匹配路线。 |
| 配置评分 | 1,413 张配置画像、116 个配置组合。理论满分按当前 R2 算法用全良重算，样本不足时留空。 |
| 段位目录 | 167 个课程、501 条课题曲引用。覆盖 2022–2026 年日版 / 国际版及已收录的国服课程，2026 国服收录五级至十段。 |
| 曲名别名 | 1,524 首歌、1,849 个谱面身份、6,978 条写法，含国服名、日文名、罗马字与常用别名。 |
| 成绩评价与连打 | 评价表含 1,345 张谱面的实测门槛资料。连打表覆盖 1,414 张谱面。门槛缺失时标记估算，连打数据缺失时标记资料不足。 |
| 公共 TJA 分析库 | 数据版 `2026-10-16.1`，随插件打包。可查询整曲特征、分支路线与指定小节。 |

AI v2 单谱 Rating 以固定 AI 定数为上限，全良达到该定数，综合量表上限为 11.6。成绩评价是由该谱極分数确定的八档分数门槛。「极」可以通过判定或黄条连打补分。计算细节见 [R2 Rating](docs/rating-r2-constant-cap.md)、[成绩评价与连打](docs/score-rank.md)及[单人分支核验](docs/branch-note-audit-2026-10-16.md)。

字节哈希以当前资源各自的 manifest 为准。`data_refresh.manifest.json` 记录 2026-10-16 回填时的快照，配置理论满分随后重算。详见 [谱面回填说明](docs/cn-constant-backfill-2026-10-16.md)、[公共谱面库](docs/chart-library.md)及[别名维护](docs/song-aliases.md)。

## 配置

| 配置项 | 用途 | 默认值 |
| --- | --- | --- |
| `base_url` | 菌菌 API 基础地址 | `https://kinoko.zorua.cn/api/v1` |
| `default_server` | 菌菌绑定时的默认服务器 | `cn` |
| `request_timeout` | 成绩接口请求超时，单位为秒 | `30` |
| `sync_ttl` | 账号成绩缓存有效期，单位为秒 | `300` |
| `storage_quota_mb` | 每个来源的本地存储告警配额，单位为 MiB | `256` |
| `storage_warn_ratio` | 存储告警比例 | `0.8` |
| `chart_library_auto_install` | 后台安装公共 TJA 分析库 | `true` |
| `chart_library_download_url` | 公共谱面库 HTTPS 镜像地址 | 留空时从插件安装 |
| `chart_library_quota_mb` | 公共谱面库配额，单位为 MiB，包含旧版及暂存文件 | `512` |

配置定义见 [_conf_schema.json](_conf_schema.json)。API Key 和 Token 保存在服务端绑定存储中；报表、AI 查询与管理页响应均使用脱敏后的玩家资料。菌菌与 Sakura 的上游协议另见 [菌菌 API 快照](docs/kinoko-api/README.md)和 [Sakura API 快照](docs/sakura-api/README.md)。

## 本地开发

插件由 `main.py` 注册，QQ 指令及帮助共用 `command_catalog.py`。`source_service.py` 按当前来源路由，`service.py` 负责同步及查询，`storage.py` 管理 SQLite。AI 批查询位于 `query_gateway.py`，管理 API 与页面位于 `account_admin.py` 和 `pages/manage/`。

```powershell
python -m pip install -r requirements.txt pytest
python -m pytest -q
```

自动化测试使用模拟接口。另可执行 `python test_api.py hiroba` 验证本机真实菌菌接口，需本地 `apikey.key`，会生成响应快照。请妥善保存凭据和快照。

成绩图由 Pillow 在插件进程中生成，随插件提供中文字体。每次生成使用新文件名，同个用户、同种图片保留最近 3 张。实力报告为 1440 × 2720 PNG；Profile 高度随内容变化。画像内容及难度素材见 [Profile 说明](docs/profile-v7.md)。

静态数据的入口在 `resource/`，构建脚本在 `scripts/`。如维护公开资源，可分别运行 `scripts/build_charts.py`、`scripts/build_dan_courses.py` 和 `scripts/build_score_rank.py`；源文件及参数见 [数据维护记录](docs/data-refresh-2026-10-14.md)、[段位原表](DAN_I_DOJO_2022_2026.md)和[评价资料构建说明](docs/score-rank.md)。
