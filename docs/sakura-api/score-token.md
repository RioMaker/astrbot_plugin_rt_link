<!-- 官方页面正文提取；来源：https://viewer.sakura-bot.cn/docs/score-token；快照日期：2026-10-14（Asia/Shanghai）。 -->

Sakura Taiko Viewer / scoretoken

# 网页成绩 token

它是一把只读密钥，让你授权的网页、工具或服务读取当前绑定太鼓 ID 的最新完整 userdata。

[返回多端同步](https://viewer.sakura-bot.cn/account/sync)

## 用户使用指南

1. 登录 Viewer，进入“个人账户 > 多端同步”。
2. 确认页面顶部显示的是你要授权的当前绑定 ID。
3. 点击“生成 token”，立即保存本次唯一展示的 48 位 token，并填写到需要接入的应用中。
4. 怀疑泄露时，在同一页面轮换或撤销 token；旧 token 会立即失效。

**安全须知**

token 等同于成绩读取密码。不要发到群聊、截图、前端源码或公开仓库。Viewer 和 bot 管理的是同一个 token，在任意一端重新生成都会让旧 token 失效。

## 开发者 API

| 项目 | 内容 |
| --- | --- |
| Method | `POST` |
| Endpoint | `https://sakura-bot.cn/api/public-score/by-token` |
| Content-Type | `application/json` |

### 请求

```bash
curl -X POST "https://sakura-bot.cn/api/public-score/by-token" \
  -H "Content-Type: application/json" \
  -d '{"token":"用户的48位token"}'
```

### 成功响应

```json
{
  "ok": true,
  "taikoId": "2258735",
  "fetchedAt": "2026-08-05T12:30:20Z",
  "data": {
    "profile": {
      "mydon_name": "SakuraDon",
      "userid": "2258735",
      "is_disp_dan_on": true,
      "province": "北京市",
      "gameCostume": {
        "title": "太鼓达人",
        "got_dan_max": 6,
        "dan_name": { "grade": "06", "level": 1 }
      }
    },
    "songs": [
      {
        "song_no": 187,
        "level": 4,
        "high_score": 1000000,
        "best_score_rank": 7,
        "good_cnt": 160,
        "ok_cnt": 0,
        "ng_cnt": 0,
        "combo_cnt": 160,
        "clear_cnt": 1,
        "full_combo_cnt": 1,
        "dondaful_combo_cnt": 1,
        "highscore_datetime": "2026-08-05 20:30:20"
      }
    ],
    "achievement": {
      "count_level": 5,
      "ary_crown_count": [250, 3, 0],
      "ary_score_rank_count": [19, 56, 136, 142, 29, 1, 0]
    }
  }
}
```

示例仅展示一条曲目记录；实际响应中的 songs 是该用户的完整成绩数组。

### 常见错误

| HTTP | 含义 |
| --- | --- |
| 400 | 请求体或 token 字段不合法 |
| 401 | token 无效、已轮换或已撤销 |
| 404 | 绑定 ID 或本地成绩不存在 |
| 502 | 上游成绩拉取失败 |

### 接入约束

- 接口支持 CORS，可由浏览器直接请求；有后端时建议服务端代调用，减少 token 暴露。
- 接口返回前会尝试拉取最新成绩。请避免高频轮询，并在业务侧设置短时间缓存。
- 不要把 token 写入日志、埋点、URL 查询参数或错误上报。
