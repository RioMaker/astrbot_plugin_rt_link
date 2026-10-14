# Sakura bot 成绩 API 本地参考

抓取日期：2026-10-14（Asia/Shanghai）。[官方文档](https://viewer.sakura-bot.cn/docs/score-token)介绍通过只读成绩 token 获取当前绑定太鼓 ID 的最新完整 userdata。本目录保存该页的历史快照和接入摘要，供后续 RTLink 开发查阅。

## 文件索引

| 文件 | 内容 |
| --- | --- |
| [score-token.md](score-token.md) | 官方正文的 Markdown 副本，保留请求、完整示例响应及错误说明 |
| [score-token.source.html](score-token.source.html) | 官网 HTTP 响应的原始 HTML，适合核对源码；未打包外部样式和脚本 |
| [SOURCE_MANIFEST.json](SOURCE_MANIFEST.json) | 来源 URL、抓取时间、下载状态、文件大小和 SHA-256 |

以下为本地摘要，接口约定以官方文档为准。范围仅限所给页面公开的成绩 token API，未据此推断 Sakura bot 的其他内部接口。

## 接口与鉴权

| 项目 | 约定 |
| --- | --- |
| 请求 | `POST https://sakura-bot.cn/api/public-score/by-token` |
| Content-Type | `application/json` |
| 鉴权位置 | JSON 请求体的 `token` 字段 |
| 请求体 | `{"token":"用户的48位token"}` |
| 授权范围 | 当前绑定太鼓 ID 的成绩只读访问 |
| 返回内容 | `ok`、`taikoId`、`fetchedAt`、`data`；`data` 下包含 `profile`、`songs`、`achievement` |

文档展示的是 JSON 内传递 token，没有要求 `Authorization: Bearer` 请求头。文档域名为 `viewer.sakura-bot.cn`，API 请求域名为 `sakura-bot.cn`。

用户登录 Viewer 后，在“个人账户 > 多端同步”确认当前绑定 ID，再生成 token。48 位 token 仅在生成时展示一次。Viewer 和 bot 管理同一个 token；任意一端重新生成、轮换或撤销后，旧 token 立即失效。

## 响应结构

| 路径 | 文档示例展示的字段 |
| --- | --- |
| 顶层 | `ok: true`、字符串 `taikoId`、`fetchedAt` |
| `data.profile` | `mydon_name`、`userid`、`is_disp_dan_on`、`province`、`gameCostume` |
| `data.profile.gameCostume` | `title`、`got_dan_max`、`dan_name.grade`、`dan_name.level` |
| `data.songs[]` | `song_no`、`level`、`high_score`、`best_score_rank`、`good_cnt`、`ok_cnt`、`ng_cnt`、`combo_cnt`、`clear_cnt`、`full_combo_cnt`、`dondaful_combo_cnt`、`highscore_datetime` |
| `data.achievement` | `count_level`、`ary_crown_count`、`ary_score_rank_count` |

`songs` 实际返回该用户的完整成绩数组；原文示例只展示一条。以上是示例字段清单，不是完整、强制或非空的 schema。原文没有定义难度与段位枚举、冠和分数等级数组的下标含义，也未保证示例涵盖所有成绩字段。

`fetchedAt` 示例为带 `Z` 的 ISO 8601：`2026-08-05T12:30:20Z`；`highscore_datetime` 示例为 `2026-08-05 20:30:20`，未注明时区。不能仅因示例相差八小时就把后者的时区作为已确认契约。

## 错误和调用约束

| HTTP 状态 | 官方说明 |
| --- | --- |
| 400 | 请求体或 token 字段不合法 |
| 401 | token 无效、已轮换或已撤销 |
| 404 | 绑定 ID 或本地成绩不存在 |
| 502 | 上游成绩拉取失败 |

接口在返回前会尝试拉取最新成绩。官方要求避免高频轮询，并在业务侧设置短时间缓存，但未给出具体频率额度、缓存秒数、超时或自动重试规则。错误响应的 JSON 结构也未在本页定义。

支持 CORS，浏览器可直接请求；有后端时官方建议由服务端代调用。不要把 token 写入群聊、截图、前端源码、公开仓库、日志、埋点、URL 查询参数或错误上报。

## 后续 RTLink 接入检查项

以下为实现建议，尚未修改插件：

- 为 Sakura 独立处理 token 和响应结构，再转换为插件内部数据模型；不能直接套用其他数据源的鉴权或响应路径。
- 将 `taikoId` 和 `profile.userid` 按字符串处理；成绩中保留 `0` 与缺失值的区别。
- 在真实授权响应中核实歌曲 ID 对应关系、难度枚举、可空字段和时间语义，再建立字段映射。
- 核实 `best_score_rank`、段位字段及 achievement 数组的枚举含义，避免凭字段名或示例值推定。
- 对同一授权的并发拉取做合并并设置短期缓存；具体时间应在接入阶段确定。
- 401 应提示用户重新配置有效 token；404 应提示检查绑定及成绩；502 应作为上游拉取失败处理，避免无限重试。

本次仅下载和核对公开文档，未使用真实 token、未调用玩家成绩接口、未进行 AstrBot / QQ 集成验证。更新资料时重新下载官方页面、提取正文并刷新来源清单；本地快照不代表未来在线版本。
