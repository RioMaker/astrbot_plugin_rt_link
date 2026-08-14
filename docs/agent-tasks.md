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
| P1 | 明确菌菌控制台 API 与绑定/查询交互设计 | 🟦 进行中 |
| P2 | 实现核心功能（绑定管理 / 成绩查询 / API 客户端 / LLM 工具） | ✅ 已完成（实机验证见 T4-4） |
| P3 | 配置化、持久化与健壮性 | ⬜ 未开始 |
| P4 | 测试、文档与发布 | ⬜ 未开始 |

---

## 2. 任务清单

### P0 · 基础框架（✅ 已完成）

| ID | 任务 | 目标 / 验收标准 | 状态 |
| --- | --- | --- | --- |
| T0-1 | 目录与元数据 | `metadata.yaml` 信息完整，`name/desc/version/author` 可用 | ✅ |
| T0-2 | 插件入口 | `main.py` 使用 `@register` + `Star`，可被 AstrBot 加载 | ✅ |
| T0-3 | 命令组骨架 | `/rt_link help\|ping\|about` 可正常响应 | ✅ |
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
- 被阻塞的任务在「开放问题」中记录阻塞原因，不臆造需求。
- 优先完成 P1 的需求确认（尤其 Q1 API 细节），再进入 P2 实现，避免返工。
