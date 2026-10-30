# 多来源成绩与独立存储

从 v0.16.0 起，RTLink 支持菌菌（`kinoko`）和 Sakura（`sakura`）。同一 QQ 可同时绑定两者，每个来源保留一份绑定；查询、画像、手动更新和 LLM 玩家查询使用该 QQ 当前选择的来源。

## 使用方式

聊天绑定只能在私聊进行，不要把真实凭据发到群里。成功绑定后自动切换到刚绑定的来源；绑定失败保留原绑定和当前来源。v0.22.0 起，管理员也可通过 [账号管理页](account-management.md) 管理现有用户与可可子的独立绑定。

```text
/rtlink bind <菌菌apikey> <player_id> [server]
/rtlink bind sakura <Sakura的48位token>
/rtlink source
/rtlink source kinoko
/rtlink source sakura
/rtlink update
/rtlink unbind
```

原有菌菌命令保持兼容，`server` 仍支持 `cn`、`jp`、`custom`。Sakura 不要求手填玩家 ID，由接口核实；当前实测的 `wahlap` 数据标记为 `cn`，未知上游标记为 `unknown`，不会推定为日服。不同来源与游戏服务器是两个概念。

`source` 不带参数显示绑定概况；切换到尚未绑定的来源会提示先绑定。切换不会同步、清除或搬移成绩。`unbind` 仅解除当前来源的凭据，保留该来源的成绩历史，其他来源的绑定不变；之后该来源查询会要求重新绑定，不自动回退到另一来源。

## 存储位置与兼容

以 AstrBot 的 `data/plugin_data/astrbot_plugin_rt_link/` 为根：

| 内容 | 菌菌 | Sakura |
| --- | --- | --- |
| SQLite 数据库 | `rt_link.db`（原路径） | `sources/sakura/rt_link.db` |
| 图片与配置资源归档 | 原数据目录 | `sources/sakura/` |
| AstrBot PluginKVStore 绑定键 | `bindings`（原键） | `bindings_sakura` |
| 当前来源 | 共同使用 `active_sources`，按 QQ 存来源名称 | 同左 |

旧用户没有 `active_sources` 时默认使用菌菌，原绑定、数据库和历史无需搬迁。两个数据库的成绩、同步批次、Rating 缓存、变化历史、配置快照和同步状态完全分开；即便 QQ、玩家 ID 和曲目 ID 都相同也不会互相替换。

公共谱面资源、TJA 分析库和歌曲别名仍共享。它们不包含玩家成绩；Sakura 玩家可以使用、申请同一份公共别名。

`storage_quota_mb` 和告警比例按每个来源独立计算；`/rtlink storage`、`list` 和 `cleanup` 分别列出或处理两个来源。与之前一样，配额用于用量告警，不是硬性写入阻断。`cleanup` 仅回收 SQLite 空页，不删除历史。

## Sakura 数据处理

[官方文档快照](sakura-api/README.md)记录鉴权与字段约定。客户端仅向固定 HTTPS 成绩端点发送 JSON token，不跟随重定向；错误消息不回显响应正文、token 或底层网络异常内容。

适配层把 `data.songs` 转为既有评级输入，保留所有难度的原始成绩字段；`0` 与缺失字段保持区别。评级继续使用原算法，仅鬼/里参与评级，不为缺少谱面模型的歌曲捏造定数。

完整的 `profile`、`songs`、`achievement`、`dojo`、`_meta` 等 userdata 保存在 Sakura 库的 `kv` 表 `source_payload:<QQ>` 下，保留最近一次成功解析并落库的响应。每条成绩的原始字段进入 `raw_json`，变化状态进入去重历史。凭据仅保存在绑定存储中，不进入成绩快照、图片或源码。

Sakura 返回当前完整成绩；本地历史从接入后每次同步积累，不代表接口提供逐局游玩历史。`fetchedAt` 与成绩时间保留原始字符串，未给不带时区的成绩时间新增时区假定。响应玩家 ID 与已绑定 ID 不一致时拒绝同步并提示重新绑定。

每个 QQ 的操作串行执行：同步期间的切换、解绑会排队，避免写入与来源选择交错。普通查询遵守各自的 `sync_ttl` 缓存；`update` 是显式强制刷新，应避免频繁调用。API 失败不会回退使用另一来源的成绩。

## 扩展其他来源

新增客户端及响应适配器，再注册独立 `ScoreService`、持久化绑定键、数据库和输出目录；同时将服务加入 `MultiSourceService`。路由只分发显式声明的玩家方法，公共资源方法独立列出。不要把一个新 bot 直接当作旧数据库里的 `source` 字段值：该字段原先区分菌菌的 `kinoko` 全历史与 `hiroba` 最新成绩格式，并不能单独隔离以 QQ 为主键的缓存。
