# rt_link 插件 · Agent 开发任务清单

> 本文档是 rt_link 插件的开发路线图与任务拆解，供开发 agent / 协作方执行与追踪。
> 状态标记：`⬜ 未开始` `🟦 进行中` `✅ 已完成` `⛔ 阻塞` `🔁 待讨论`

---

## 0. 项目概述

| 项 | 内容 |
| --- | --- |
| 插件名 | `rt_link` |
| 类型 | AstrBot Star 插件 |
| 一句话定位 | 将 NapCat 对话中的 QQ 号绑定到「菌菌控制台」的 apikey，据此查询对应玩家成绩信息，并把绑定关系与数据持久化在插件内部，供后续操作复用 |
| 核心链路 | QQ 号 ↔ (玩家ID + apikey) 绑定 → HTTP Header 鉴权 + 指定玩家ID 调用菌菌 API → 获取成绩 → 持久化/缓存 → 命令或 LLM 拦截返回 |
| 绑定模型 | 一个 QQ 号 ↔ 一个玩家 ID ↔ 一个 apikey（三要素一对一绑定） |
| 触发方式 | 命令为主 + LLM 请求/回复拦截 |
| 外部依赖 | 菌菌控制台 HTTP API + 本地持久化存储 |
| 运行环境 | AstrBot（Python 3.10+，NapCat 平台适配器） |

---

## 1. 里程碑（Phase）

| Phase | 目标 | 状态 |
| --- | --- | --- |
| P0 | 搭建插件基础框架、可加载、可响应命令 | ✅ 已完成 |
| P1 | 明确菌菌控制台 API 与绑定/查询交互设计 | ✅ 已完成 |
| P2 | 实现核心功能（绑定管理 / 成绩查询 / API 客户端 / LLM 工具） | ✅ 已完成 |
| P3 | 配置化、持久化与健壮性 | ✅ 已完成（含 AI v2 评级 + SQLite 持久化 + 空间监管） |
| P4 | 测试、文档与发布 | 🟦 进行中（本地冒烟通过，实机验证待做） |

---

## 2. 任务清单

### P0 · 基础框架（✅ 已完成）

| ID | 任务 | 目标 / 验收标准 | 状态 |
| --- | --- | --- | --- |
| T0-1 | 目录与元数据 | `metadata.yaml` 信息完整，`name/desc/version/author` 可用 | ✅ |
| T0-2 | 插件入口 | `main.py` 使用 `@register` + `Star`，可被 AstrBot 加载 | ✅ |
| T0-3 | 命令组骨架 | `/rtlink help\|ping\|about` 可正常响应 | ✅ |
| T0-4 | 配置 schema | `_conf_schema.json` 结构合法，`get_config()` 可读取 | ✅ |
| T0-5 | 仓库基础 | `.gitignore`、`README.md` 就绪 | ✅ |

### P1 · 需求与设计（🟦 进行中）

| ID | 任务 | 目标 / 验收标准 | 状态 |
| --- | --- | --- | --- |
| T1-1 | 确认菌菌控制台 API | ✅ 已实测：Base `/api/v1`、`Authorization: Bearer tk_...`、4 个成绩端点及字段（见「菌菌 API 契约」） | ✅ |
| T1-2 | 绑定模型设计 | ✅ 已定：一个 QQ 号绑定一个玩家 ID 对应一个 apikey（三要素一对一） | ✅ |
| T1-3 | 命令交互设计 | 定义 bind / unbind / list / score 等命令的参数与返回格式 | ⬜ |
| T1-4 | LLM 拦截策略 | 定义哪些自然语言触发（如「我的成绩」）时如何注入查询结果 | ⬜ |
| T1-5 | 持久化方案 | 选定绑定表/缓存的存储方式与文件结构 | ⬜ |
| T1-6 | 评审 | 需求文档经需求方确认 | ⬜ |

### P2 · 核心功能实现（✅ 已完成，实机验证见 T4-4）

| ID | 任务 | 目标 / 验收标准 | 状态 |
| --- | --- | --- | --- |
| T2-1 | 绑定管理命令 | `bind <apikey> <player_id> [server]` / `unbind` / `list`（管理员）已实现，写入/删除/查询绑定表 | ✅ |
| T2-2 | API 客户端 | `api_client.py` 已实现（鉴权/超时/错误处理），真实数据验证通过 | ✅ |
| T2-3 | 成绩查询命令 | `score <曲名>` 按曲名模糊匹配并格式化返回（已验证匹配逻辑） | ✅ |
| T2-4 | LLM 工具 | `@filter.llm_tool` 注册 `query_taiko_score`，模型可自动调用 | ✅ |
| T2-5 | 缓存 | 全量成绩内存缓存（60s TTL）已实现 | ✅ |

### P3 · 配置、持久化与健壮性（⬜ 未开始）

| ID | 任务 | 目标 / 验收标准 | 状态 |
| --- | --- | --- | --- |
| T3-1 | 配置项完善 | `_conf_schema.json` 覆盖 API 地址、超时、缓存时长、权限开关等 | ⬜ |
| T3-2 | 持久化 | 绑定表（必选）与成绩缓存（可选）落地到插件数据目录 | ⬜ |
| T3-3 | 日志与监控 | 绑定/查询/API 调用关键路径有日志 | ⬜ |
| T3-4 | 异常兜底 | 未绑定、apikey 失效、API 超时/报错等场景给出友好提示 | ⬜ |

### P4 · 测试、文档与发布（⬜ 未开始）

| ID | 任务 | 目标 / 验收标准 | 状态 |
| --- | --- | --- | --- |
| T4-1 | 功能测试 | 覆盖绑定/解绑/查询主流程与边界场景 | ⬜ |
| T4-2 | 文档完善 | README 补充用法、配置说明、API 对接说明与示例 | ⬜ |
| T4-3 | 版本与发布 | 确定版本号、打 tag、发布到插件仓库/市场 | ⬜ |
| T4-4 | 上线验收 | 在真实 AstrBot + NapCat 实例中验证稳定运行 | ⬜ |

---

## 3. 菌菌 API 契约（已实测）

> 来源：对 kinoko.zorua.cn 前端 bundle 与 DocsPage 内嵌文档反向解析，并用 `apikey.key` 实测验证（`test_api.py`）。

| 项 | 值 |
| --- | --- |
| 公开 API Base URL | `https://kinoko.zorua.cn/api/v1` |
| 鉴权 | `Authorization: Bearer <tk_... API Key>` |
| 请求/响应 | JSON；成功与错误均为 `Cache-Control: no-store` |

成绩端点（均 GET，个人 API Key 可用）：

| 端点 | 说明 |
| --- | --- |
| `/scores/hiroba` | 鼓众广场风格，按谱面返回最新有效成绩 |
| `/scores/kinoko` | 菌菌风格，按谱面返回全部有效成绩历史 |
| `/scores/hiroba/recent` | 最近一天游玩的谱面最新有效成绩 |
| `/scores/kinoko/recent` | 最近一天菌菌风格成绩 |

查询参数：`player_id`（string，可选，账号拥有的玩家 ID）、`server`（`cn`/`jp`/`custom`，可选）。省略 `player_id` 时用账号第一个活跃绑定。

`hiroba` 响应：`{"data":{"playedRecords":{"userid","server","scoreInfo":[{song_no, level, high_score, best_score_rank, good_cnt, ok_cnt, ng_cnt, pound_cnt, combo_cnt, clear_cnt, full_combo_cnt, dondaful_combo_cnt, highscore_datetime, song_detail:{song_name, song_name_jp, ...}}]}}}`

`kinoko` 响应：`{"data":{"playedRecords":{"player_id","server","scoreInfo":[{song_no, level, title, title_cn, genre, subTitle, scoreInfo:[...历史...]}]}}}`

---

## 4. 开放问题（🔁 待与需求方讨论）

- **Q1（✅ 已解决）**：菌菌控制台 API —— 见「3. 菌菌 API 契约（已实测）」。
- **Q2（✅ 已确认）**：玩家标识 —— apikey 对应账号，查询时需额外指定玩家/角色 ID；QQ 号绑定到该玩家 ID。
- **Q3（✅ 已确认）**：绑定关系 —— 一个 QQ 号绑定一个玩家 ID 对应一个 apikey（三要素一对一）。
- **Q3.1（待确认）**：是否允许用户自行解绑/换绑？管理操作（如 `list` 查看全部绑定）是否仅限管理员？
- **Q4**：成绩展示 —— 需要返回哪些字段、以什么格式展示（纯文本 / 图片 / 表格）？
- **Q5**：缓存与刷新 —— 成绩是否需要缓存？缓存多久？是否需要手动刷新命令？
- **Q6**：发布形式 —— 本地自用 / 开源 / 上架插件市场？

---

## 5. 执行约定

- 每个任务完成后更新上表状态与验收证据（截图/日志/测试结果）。
- **改完即本地提交**：每完成一项修改（代码 / 资源 / 文档）并通过测试后，立即在本仓库执行
  `git commit`（只提交本地，不做 push）。提交信息用中文说明「改了什么、为什么、如何验证」，
  一次提交对应一件事，不要把无关改动混在一起。
- 被阻塞的任务在「开放问题」中记录阻塞原因，不臆造需求。
- 优先完成 P1 的需求确认（尤其 Q1 API 细节），再进入 P2 实现，避免返工。

---

## 6. 变更记录

### 2026-09-19 · 段位道场资料更新到 2026 届

| 项 | 内容 |
| --- | --- |
| 背景 | 段位资料只到 2025 届，而 2026 届五级～十段已于 2026-06-06 开放、玄人～达人也于 2026-09-12 追加 |
| 资料 | `DAN_I_DOJO_2022_2025.md` 改名 `DAN_I_DOJO_2022_2026.md` 并新增第 7 节：19 个段位 × 3 曲、魂槽、普通/金合格条件、逐曲「可」上限与连打要求；来源为官方公告 `taiko-ch.net/blog/?p=16229` 与 wiki 段位道場索引页 + 各段位攻略页 |
| 构建 | `scripts/build_dan_courses.py`：`DATA_VERSION=2026-09-19.1`、新增 2026 数据与逐段位来源 id（`reference_2026_十段` 等）；课程数 133 → 152、课题曲条目 399 → 456 |
| 映射修正 | 同名曲目改为按「难度 → 音符数 → ID」排序取主 ID：`エンジェル ドリーム`（2026 四段）此前会绑到デレマス版（ID 153、694 音符），现正确绑到ナムコオリジナル版（ID 433、765 音符）；新增 `mapping_evidence` 记录每条映射依据 |
| 缺口登记 | 2026 新曲《鈍響ライクリフド》《活声ライクリフド》《resume:story》《HYPERNOVA》《Vrykolakas》《Nivalis*Anima》《魔宵月》《銀の黎明か、黒の晶華か。》尚未进入评级曲库，按 `not_in_chart_resource` 登记（查询会显示「当前曲库无此曲」），曲库更新后重跑构建即自动映射 |
| 配套 | 重跑 `scripts/build_aliases.py`（段位写法 7 → 8 条、写法总数 5509）；新增 `scripts/survey_dan_coverage.py` 统计段位写法与曲库曲名的吻合度（国服名 144 / 日文名 282 / 靠别名 19 / 未收录 11） |
| 验收 | `python -m pytest test -q` 241 通过（新增 2026 课程、映射顺序、逐曲条件用例）；预览见 `test/tmp/dan2026_dump.txt` 与 `test/tmp/dan2026_preview.txt` |

### 2026-09-19 · 提升评价补齐「连打路线」的可行性与秒速

| 项 | 内容 |
| --- | --- |
| 背景 | 原实现一律给出「或改补 N 打连打」，但有的谱面**根本没有黄条**，也有的谱面黄条容量不足以补上缺口；玩家需要知道还差几打、总共几打、对应秒速多少 |
| 数据 | 新增 `resource/rolls.v1.json.gz`（构建脚本 `scripts/build_rolls.py`）：从 ESE 的 TJA 谱面按 wiki「連打秒数表」公式算出每谱黄条条数、合計連打秒数、連打理論値与风船资料，再用 wiki 極スコア 表的「要求連打速度」交叉校验；覆盖 1326/1393 谱面 |
| 计算 | `score_rank.roll_plan()` / `judgment_plan()` / `improvement_plan()`：还差几打、总打数、秒速（黄条打数 ÷ 合计黄条秒数，风船不计入）、是否超理論値、是否必须全良、是否连全良＋打满都达不到 |
| 文案 | 新增 `improve_text.py`：判定路线 + 连打路线统一说法，`/rtlink improve` 文本/图片、`/rtlink score ... target_rank`、LLM 工具 `find_rank_improvements` 共用 |
| 验收 | `python -m pytest test -q`（`test/test_rolls.py` 27 条新用例）；`test_bundled_roll_resource_matches_wiki_for_known_songs` 对照 wiki 公布秒数；预览图见 `test/tmp/improve_roll_preview.txt` 与 `test/tmp/improve_10001_*.png` |

### 2026-09-19 · 曲名别名索引 + 段位查询优化

| 项 | 内容 |
| --- | --- |
| 问题 | 段位资料里 399 条课题曲只有 142 条与国服曲名同写法（247 条是日文写法），玩家用国服名或口语简称反问段位时大多查不到；查询结果也只有日文曲名，没法直接接着查成绩 |
| 数据 | 新增 `resource/aliases.v1.json.gz`（构建脚本 `scripts/build_aliases.py`）：合并国服曲名、日文曲名、ESE 谱面罗马字曲名、段位资料写法与人工别名表 `scripts/data/song_aliases.json`，含派生写法（去括号/主标题/去 2000 尾缀/紧凑写法），覆盖 1393 张谱面、5435 条写法 |
| 匹配 | 新增 `song_alias.py`：统一归一化（NFKC + 大小写 + 片假名折平假名 + 繁简折算 + 去符号）与 `exact > prefix > contains` 解析；段位查询、`/rtlink score`、`search_scores`、别名申请共用 |
| 段位查询 | `dan_query.query_dan_courses_text` 支持别名与「鬼 天竺2000」难度前缀；结果统一展示「《国服名》（日文名）· 鬼★10｜音符｜ID」；曲目不在段位里时说明「没有出现记录」并给出候选 ID；新增用户命令 `/rtlink dan [年份] [区域] [段位] [曲名]`（`/rtlink 段位` 同义） |
| 验收 | `python -m pytest test -q`（新增 `test/test_song_alias.py` 34 条 + `test_dan_query.py` 11 条）；预览见 `test/tmp/dan_alias_preview.txt`、`test/tmp/alias_e2e.txt`；规则与维护见 `docs/song-aliases.md` |
