# 用户与可可子账号管理

v0.22.0 新增 AstrBot 插件管理页。更新插件后重载，在插件详情中打开「用户与可可子账号管理」。页面需要支持 Plugin Pages 与 `astrbot.api.web` 的 AstrBot；旧宿主仍可使用原有聊天命令。

## 绑定可可子的账号

1. 打开「可可子账号」。菌菌填写 `tk_` 开头的 API Key、玩家 ID，以及 `cn` / `jp` / `custom` 服务器；SakuraBot 填写 48 位字母或数字 Token，玩家身份由上游接口验证。
2. 点击「验证并保存」。成功后将该来源设为当前来源；验证失败保留原绑定。凭据输入框不回显已有 Token。
3. 点击「同步成绩」，拉取该来源的成绩并计算 Rating。仅绑定不会自动执行全量成绩同步；后续 AI 查询也会按原有缓存规则按需同步。
4. 两个来源可以同时绑定，通过「设为当前来源」选择 AI 使用的成绩表；切换本身不触发同步。

每个插件实例只有一份可可子身份，各聊天共用。内部所有者 ID 为 `__rtlink_ai__`，与普通发言者 ID 独立；即使绑定相同的游戏玩家，凭据、当前成绩、Rating 缓存及历史仍按所有者分别保存。两个来源继续沿用独立数据库。

## AI 如何使用

以下五个玩家工具支持可选参数 `target`：`query_rtlink`、`get_player_overview`、`recommend_practice`、`query_song_brief`、`evaluate_player_dan`。

| 参数 | 查询对象 | 例子 |
| --- | --- | --- |
| `caller`（默认） | 当前发言者 | 用户说「我的 Rating」「帮我查成绩」 |
| `bot` | 可可子自己 | 用户说「你的 Rating」「可可子这首歌打多少」 |

例如查询可可子的 Rating 和近期成绩：

```json
{
  "target": "bot",
  "queries": [
    {"tool": "get_player_rating"},
    {"tool": "get_recent_scores", "args": {"days": 7}}
  ]
}
```

组合查询结果的 `subject` 标明查询对象；快捷工具的可可子结果带对象前缀。未绑定当前来源时返回管理页设置提示，不借用发言者或其他来源的成绩。模型不能传入任意用户 ID，也不能调用绑定、换源、解绑等管理操作。公共 `query_dan_course` 无需选择玩家。

同一消息仍最多两次查询，`caller` 与 `bot` 的相同查询分别计数，允许用两次调用比较双方。升级后需刷新宿主的工具定义（重载插件；必要时开启新会话），使模型看到 `target` 参数。原有手动命令继续作用于发言者。

## 用户列表与管理

列表以用户 ID 为单位合并菌菌、SakuraBot 绑定，单个用户只占一行；可可子单独在账号页管理。支持用户 ID / 已知玩家 ID 搜索、当前绑定来源筛选、已绑定/已解绑状态筛选及分页。

- **最后同步**：各来源已落库成绩的最近同步时间，显示为北京时间；详情同时列出每个来源的时间。没有记录时显示「尚未同步」。
- **当前 Rating**：当前选择来源最近一次成功计算的综合 Rating，同时标注来源和评级时间；打开页面不会刷新上游。缓存必须属于相同游戏账号、服务器和当前评级版本，不能借用旧账号、其他来源或旧算法结果。没有有效缓存时显示「待同步评级」；当前来源已解绑时显示「当前来源未绑定」。
- **管理**：查看各源玩家 ID / 服务器，验证并替换凭据，同步指定来源，切换当前来源或解绑指定来源。同步非当前来源不会修改当前选择。

解绑只移除该来源的凭据，历史保留，其他来源不变；当前来源解绑后不会自动回退到另一个来源。重新绑定后需同步当前成绩。页面操作、聊天命令和 AI 查询共享用户锁，避免同步与换绑交错。

旧用户通过现有绑定、同步批次、评级记录与成绩记录自动发现。新增 `known_accounts` KV 仅保存非敏感身份，使今后「绑定后未同步就解绑」的用户仍可管理。升级前既已解绑、又未留下任何成绩或历史记录的用户无法还原；已有游戏昵称未接入，因此页面以平台用户 ID 展示。

## 存储与权限

沿用 `bindings`、`bindings_sakura`、`active_sources` 及原数据库，不迁移或删除已有数据。新增页面静态文件在 `pages/manage/`，通过新旧 Bridge 名称兼容宿主可视化视图。

管理 API 路由以插件元数据名称 `rt_link` 为前缀：`/rt_link/admin/users`、`/rt_link/admin/account`、`/rt_link/admin/action`。仅接受宿主提供的已登录 Dashboard 身份，拒绝无登录态及跨站请求；列表、详情、操作响应都不包含 Token，业务异常不回传上游异常原文。Token 仅在保存时通过 Bridge 发送，页面不使用 LocalStorage 保存凭据。

## 本地验证

```powershell
.\.venv\Scripts\python.exe -m pytest test --ignore=test/tmp -q
.\.venv\Scripts\python.exe -m ruff check --no-cache account_admin.py account_identity.py source_service.py test/test_account_admin.py
node --check pages/manage/app.js
node test/verify_account_page.cjs <playwright或playwright-core模块目录>
```

浏览器脚本使用合成数据与隔离 Bridge，覆盖列表、搜索、分页、详情、可可子绑定/同步/切换/解绑、失败提示、凭据清空、文本转义、窄屏与暗色主题；截图写入被忽略的 `test/tmp/account-admin-ui/`。这不代替真实 AstrBot 登录态、真实 Token 与聊天模型的部署联调。
