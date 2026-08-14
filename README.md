# astrbot_plugin_rt_link

将 NapCat 对话中的 QQ 号绑定到「菌菌控制台」的 apikey，据此查询太鼓达人指定曲目的成绩。

## 功能

- 绑定管理：`bind` / `unbind` / `list`（管理员）
- 成绩查询：按曲名模糊匹配（中文/日文/英文）
- LLM 工具：注册 `query_taiko_score`，模型可在自然对话中自动调用
- 持久化：绑定关系存入 AstrBot PluginKVStore

## 命令

```
/rt_link bind <apikey> <player_id> [server]  绑定当前 QQ（server 默认 cn）
/rt_link unbind                              解绑当前 QQ
/rt_link score <曲名>                        查询指定曲目成绩
/rt_link list                                查看全部绑定（管理员）
/rt_link help                                查看帮助
/rt_link about                               查看插件信息
```

也可以直接自然语言询问，例如：「我的《夏祭り》成绩是多少」。

## 目录结构

```
astrbot_plugin_rt_link/
├── main.py             # 插件入口（Star 类 + 命令 + LLM 工具）
├── api_client.py       # 菌菌公开 API 客户端（标准库实现）
├── test_api.py         # API 连通性测试（读取 apikey.key）
├── metadata.yaml       # 插件元数据
├── requirements.txt    # 依赖声明（当前无第三方依赖）
├── _conf_schema.json   # WebUI 配置项
└── docs/
    └── agent-tasks.md  # 开发任务清单
```

## 菌菌公开 API（已实测）

| 项 | 值 |
| --- | --- |
| Base URL | `https://kinoko.zorua.cn/api/v1` |
| 鉴权 | `Authorization: Bearer <tk_... API Key>` |
| 成绩端点 | `GET /scores/hiroba`、`/scores/kinoko`、`/scores/hiroba/recent`、`/scores/kinoko/recent` |

## 安全说明

- apikey 仅保存在插件服务端的 KV 存储中，**不会**发送给大模型。
- LLM 只能通过 `query_taiko_score` 工具查询成绩，返回内容为成绩文本，不含 apikey。
- `bind` / `unbind` / `list` 是聊天命令而非 LLM 工具，大模型无法调用；且命令一旦返回结果，AstrBot 不会再调用大模型处理该条消息。
- `bind` 命令仅允许在私聊中使用，避免 apikey 泄露到群聊。
- 请勿在普通对话中直接粘贴 apikey。

## 开发

1. 将本目录软链/复制到 AstrBot 的插件目录（`data/plugins/`）。
2. 在 AstrBot 的插件管理界面中加载插件。
3. 绑定后即可用命令或自然语言查询成绩。

### 本地测试 API

```bash
python test_api.py hiroba   # 或 kinoko
```

## 参考

- 插件开发指南：https://docs.astrbot.app/dev/star/plugin-new.html
- AI / LLM 工具：https://docs.astrbot.app/dev/star/guides/ai.html
