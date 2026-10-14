# 菌菌 API 本地参考

抓取日期：2026-10-14（Asia/Shanghai）。入口：[官方 API 接入指南](https://kinoko.zorua.cn/docs/api-guide)。本目录用于后续 RTLink 开发查阅；这是文档快照，接口行为未在本次任务中实测。

## 文件索引与来源

| 文件 | 内容 | 官方页面 |
| --- | --- | --- |
| [api-guide.md](api-guide.md) | 第三方资源 API：权限、完整字段表、请求与响应示例、错误码 | [API 接入指南](https://kinoko.zorua.cn/docs/api-guide) |
| [oauth-guide.md](oauth-guide.md) | 应用登记、授权、回调、换取和刷新 Token 的步骤 | [OAuth 接入指南](https://kinoko.zorua.cn/docs/oauth-guide) |
| [api-oauth.md](api-oauth.md) | OAuth 协议参数、认证方式、有效期、撤销和错误处理 | [OAuth 协议 API](https://kinoko.zorua.cn/docs/api/oauth) |
| [api-reference.md](api-reference.md) | 补充资料：网站内部 API、曲库、别名、难易度表等 | [API 参考文档](https://kinoko.zorua.cn/docs/api-reference) |
| [SOURCE_MANIFEST.json](SOURCE_MANIFEST.json) | 精确抓取时间、页面和资源 URL、文件大小、SHA-256 | 本地来源清单 |

上述四份 Markdown 从官网页面实际加载的公开 Vite 文档模块提取，未执行下载的 JavaScript。对应的四个 `.js` 文件保留原始字节，以供校验。下载过程使用 HTTPS 并校验证书，无需登录或 API Key。

原文中的 `/docs/...` 等站内链接保持原样，在线查阅时以 `https://kinoko.zorua.cn` 为根地址；本地请使用上表导航。`api-guide.md` 中四处 `<code-tabs>` 是网页动态生成的多语言示例占位符，Markdown 本身没有这些选项卡的正文，但保留了每个端点完整的 curl 和 JSON 示例。

以下内容为本地整理，接口约定以官方原文为准。未来更新时应重新解析文档页实际加载的资源路径，不应假定带哈希的 `.js` 文件名固定不变。

## 基础约定与权限

- 资源 API Base URL：`https://kinoko.zorua.cn/api/v1`。
- 鉴权头：`Authorization: Bearer <credential>`。
- `tk_` 是个人 API Key；`oa_` 是 OAuth access token；`or_` 仅用于刷新，不能调用资源 API。
- 网站登录 JWT 不可用于 `/api/v1`。官方要求第三方应用使用 OAuth，不得要求用户提供个人 API Key；个人 Key 仍支持文档列出的个人读取接口。
- `player_id`、`userid` 必须保存为字符串，保留日服 ID 的前导零。`server` 为 `cn`、`jp` 或 `custom`；虚拟账号 ID 为 `cm` 加 9 位数字。
- `bind_id` 是绑定 ID；`kinoko_id` 是菌菌曲目 ID；`song_no` / `game_id` 是游戏侧歌曲 ID。这些标识不能互换。
- 资源响应为 JSON，成功和失败均声明 `Cache-Control: no-store`。文档要求原始响应按该策略处理，仅缓存业务需要的非敏感派生结果。

## 资源端点速查

下表路径均相对于 `/api/v1`。个人 Key 一列的“是”指 `tk_` 可调用；OAuth 仍需对应 scope。

| 方法 / 路径 | 作用 | 个人 Key | OAuth scope |
| --- | --- | --- | --- |
| `GET /scores/hiroba` | 每个谱面的最新有效成绩，含 `song_detail` | 是 | `read_player` |
| `GET /scores/kinoko` | 按谱面分组的全部有效历史，组内时间倒序 | 是 | `read_player` |
| `GET /scores/hiroba/recent` | 最新每日汇总涉及谱面的最新有效成绩 | 是 | `read_player` |
| `GET /scores/kinoko/recent` | 最新每日汇总涉及谱面的全部有效历史 | 是 | `read_player` |
| `GET /user/profile` | 授权用户的站内资料 | 否 | `read_user_profile` |
| `GET /user/hiroba-binds` | 已验证、启用且有玩家资料的绑定，按手动顺序返回 | 否 | `read_user_profile` |
| `GET /players/{bind_id}/scores/{kinoko_id}/{level}/history` | 单谱面的真实聚合快照，不应用成绩覆盖 | 是 | `read_player` |
| `GET /players/{bind_id}/score-summaries` | 分页每日汇总和能力指标 | 是 | `read_player` |
| `POST /players/{bind_id}/sync` | 触发国服同步 | 否 | `write_player` |
| `GET /players/{bind_id}/sync-status` | 查看同步 / 导入状态 | 否 | `write_player` |
| `POST /players/{bind_id}/scores/import` | 导入日服 / 虚拟账号快照 | 否 | `write_player` |

## 成绩与历史的关键区别

四个 `/scores/*` 接口接受可选的 `player_id`、`server`。省略玩家 ID 时使用手动排序后第一个已验证且启用的绑定；需要稳定查询特定玩家时，应同时指定两者。这四个接口会应用用户设置的成绩覆盖。

- Hiroba 返回 `data.playedRecords.userid`，`scoreInfo[]` 是平铺成绩，每条附 `song_detail`。
- Kinoko 返回 `data.playedRecords.player_id`，外层 `scoreInfo[]` 是谱面，每个谱面内部还有 `scoreInfo[]` 历史数组。
- `recent` 根据最新一份每日汇总筛选谱面，不等同于滚动的过去 24 小时；Kinoko recent 仍可包含这些谱面更早的历史。
- 单谱面 `/history` 返回真实聚合快照，不能据此宣称是逐局游玩记录。当前 `schema_version=3`，包含 `song`、`selected_level`、固定五个难度槽的 `charts` 和快照 `items`。
- 曲库缺失时，历史接口的 `song` 可为 `null`；`charts[].stars`、图片和 Wiki 链接也可为 `null`。

常用成绩字段：`high_score` 最高分；`good_cnt` / `ok_cnt` / `ng_cnt` 良 / 可 / 不可；`pound_cnt` 连打；`combo_cnt` 最大连击；`stage_cnt` / `clear_cnt` / `full_combo_cnt` / `dondaful_combo_cnt` 分别是游玩 / 通关 / 全连 / 全良次数。`level=1..5` 对应 Easy、Normal、Hard、Mania、Ura。

时间需按接口分别解析：兼容成绩字段表写的是 `YYYY-MM-DD HH:mm:ss`，未注明时区；单曲历史示例使用带 `Z` 的 ISO 8601。不要未经核实给前者补上 UTC。汇总日期明确按 UTC，展示为北京时间时需另行转换。

每日汇总默认 `end_date=当前 UTC 日期`、`start_date=end_date 前 89 天`；日期范围最多 366 个自然日。`page` 默认 1，`page_size` 默认 30、范围 1–100。指标包含 `rating`、`daigouryoku`、`accuracy_power`、`stamina`、`speed`、`rhythm`、`complex_power`。文档没有在这里解释它们与本插件 Rating 模型版本的对应关系，接入前需要另行核对。

## 同步与导入

- 国服 `/sync` 在请求内完成并返回 `200`，同一玩家冷却 5 分钟，同一时间只能执行一个写入任务。
- 日服远端爬取已停用，`/sync` 返回 `400 JP_IMPORT_REQUIRED`，应通过采集脚本生成快照再导入。
- 虚拟账号 `/sync` 返回 `400 CUSTOM_SYNC_UNSUPPORTED`，只能使用导入。
- 导入请求体只能包含 `playerInfo`、`scoreInfo`，不超过 5 MiB；成绩最多处理前 5000 项，超出数量反映在 `skipped_extra`。
- `playerInfo.userid` 必须与绑定一致。虚拟账号导入不更新鼓手名、称号、段位或外观。
- 导入结果应分别检查 `inserted`、`updated`、`unchanged`、`skipped_stale`、`skipped_unmapped`、`skipped_invalid`、`skipped_extra`，不能仅根据 HTTP 成功认定每条成绩都已导入。
- `/sync-status` 也需要 `write_player`，但它不触发任务、不消耗玩家写入频率额度。

## OAuth 接入要点

1. 在开发者中心登记客户端类型、回调地址和 scope；公共客户端没有 secret，机密客户端只在可信服务端保存 secret。
2. 从 `GET /.well-known/oauth-authorization-server` 读取服务端点；每次授权生成独立的 `state` 和 PKCE verifier。
3. 打开 `GET /oauth/authorize`，使用 Authorization Code + PKCE `S256`；回调地址必须与登记值逐字符一致。
4. 回调先校验 `state`，再向 `POST /api/oauth/token` 提交授权码和 verifier。
5. 交换 / 刷新 / 撤销使用 `application/x-www-form-urlencoded`，不是 JSON；不支持 HTTP Basic。机密客户端使用 `client_secret_post`。
6. 授权码 5 分钟且仅可成功交换一次；access token 15 分钟；refresh token 30 天并在刷新成功后轮换。
7. 先持久化新 refresh token 再废弃旧值；重用旧值会导致整个 token family 被撤销。实现时应串行处理同一授权的刷新操作。
8. 解除授权使用 `POST /api/oauth/revoke`；撤销 refresh token 会撤销其整个 family。

Scope 分别为：`read_user_profile`（用户与绑定）、`read_player`（成绩与历史）、`write_player`（同步、状态、导入）。新增 scope 需要先修改应用登记，再让用户重新授权。

## 错误处理

| 接口类型 | 错误体 |
| --- | --- |
| 四个 `/api/v1/scores/*` 兼容端点 | `{"detail": "..."}` |
| `/api/v1/user/*`、`/api/v1/players/*` | `{"code": "...", "detail": "..."}` |
| OAuth Token / Revoke | `{"error": "...", "error_description": "..."}` |

OAuth 资源请求遇到 `401` 最多自动刷新一次，失败后重新授权；不得自动回退到个人 API Key。`403` 检查 scope，`404 BIND_NOT_FOUND` 重新获取绑定，`409 SYNC_IN_PROGRESS` 等待写入完成，`429` 遵守 `Retry-After` / 冷却提示并限制重试。Token 端点的 `invalid_grant` 应重新授权，不能循环刷新。

## 后续 RTLink 开发查阅提示

以下是依据文档提出的接入检查项，本次没有修改插件实现：

- 先确认个人脚本与第三方应用的授权场景，再选择个人 Key 或 OAuth；不能因现有代码使用 Key 就假定所有新增端点也支持它。
- Profile、推荐卡、历史曲线分别明确使用兼容成绩、真实快照还是每日汇总；保留数据来源语义。
- 歌曲编号与绑定编号使用各自字段；不要把 `song_no` 直接代入 `kinoko_id` 路径。
- 保留零值、缺失值与不同星级缺失标记的区别：兼容接口可能为 `"-"`，历史接口可能为 `null`。
- [既有字段笔记](../data-fields.md) 包含以前的接口观察；本次没有重测那些观察，若与官方描述冲突应在接入时验证。
- 补充的 `api-reference.md` 描述网站 JWT 接口，其公开 API 概述仍主要写个人 Key。第三方接入以专门的 `api-guide.md` 和 OAuth 文档为主；网站内部端点不能自动视为 OAuth 公开资源端点。

本次验证范围：四份官方文档下载、解码、来源和哈希核对，以及本地摘要的相对链接检查；未调用玩家资源接口、未触发同步或导入、未进行 AstrBot / QQ 集成验证。
