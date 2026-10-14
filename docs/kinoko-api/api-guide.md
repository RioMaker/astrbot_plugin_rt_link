# API 接入指南

本文列出第三方脚本和 OAuth 应用可调用的资源 API。OAuth 授权、Token 与撤销端点见 [OAuth 协议 API](/docs/api/oauth)，完整接入步骤见 [OAuth 接入指南](/docs/oauth-guide)。

## 1. 基础信息

| 项目 | 值 |
| --- | --- |
| Base URL | `https://kinoko.zorua.cn/api/v1` |
| 认证头 | `Authorization: Bearer <credential>` |
| 请求和响应 | JSON |
| 缓存 | 成功和错误响应均为 `Cache-Control: no-store` |
| CORS 来源 | `*` |
| CORS 方法 | `GET, POST, OPTIONS` |
| CORS 请求头 | `Authorization, Content-Type` |

`player_id` 和 `userid` 必须按字符串处理。日服 12 位太鼓番可能以 `0` 开头，虚拟账号 ID 使用 `cm` 加 9 位数字；转换为数字会丢失身份信息。

## 2. 凭证与权限

| 凭证 | 前缀 | 获取方式 | 用途 |
| --- | --- | --- | --- |
| 个人 API Key | `tk_` | 账号信息 -> 第三方访问 | 读取当前账号的成绩、单曲历史和成绩汇总 |
| OAuth access token | `oa_` | OAuth Token 端点 | 按用户授权的 scope 读取或更新资源 |
| OAuth refresh token | `or_` | OAuth Token 端点 | 换取新 Token，不可调用资源 API |

站内登录 JWT 不可调用 `/api/v1`。第三方应用不得要求用户提供个人 API Key，应使用 OAuth。

## 3. 端点一览

| 方法和路径 | 功能 | 个人 API Key | OAuth scope |
| --- | --- | --- | --- |
| `GET /scores/hiroba` | 按谱面返回最新有效成绩 | 支持 | `read_player` |
| `GET /scores/kinoko` | 按谱面返回全部有效成绩历史 | 支持 | `read_player` |
| `GET /scores/hiroba/recent` | 返回最近一天游玩谱面的最新有效成绩 | 支持 | `read_player` |
| `GET /scores/kinoko/recent` | 返回最近一天游玩谱面的全部有效成绩历史 | 支持 | `read_player` |
| `GET /user/profile` | 返回授权用户资料 | 不支持 | `read_user_profile` |
| `GET /user/hiroba-binds` | 返回授权用户的有效绑定 | 不支持 | `read_user_profile` |
| `GET /players/{bind_id}/scores/{kinoko_id}/{level}/history` | 返回单个谱面的真实成绩快照 | 支持 | `read_player` |
| `GET /players/{bind_id}/score-summaries` | 分页返回每日成绩汇总 | 支持 | `read_player` |
| `POST /players/{bind_id}/sync` | 触发国服成绩同步 | 不支持 | `write_player`；虚拟账号返回 `CUSTOM_SYNC_UNSUPPORTED` |
| `GET /players/{bind_id}/sync-status` | 读取同步状态 | 不支持 | `write_player` |
| `POST /players/{bind_id}/scores/import` | 导入日服或虚拟账号 canonical 快照 | 不支持 | `write_player` |

## 4. 兼容成绩端点

四个兼容成绩端点共用以下查询字段。省略 `player_id` 时，服务端使用账号手动排序后的第一个已验证且启用绑定。

| 查询字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `player_id` | string | 否 | 当前账号拥有的玩家 ID |
| `server` | string | 否 | `cn`、`jp` 或 `custom`；传入 `player_id` 时建议同时传入 |

兼容成绩端点会应用用户设置的成绩覆盖。单曲历史端点只返回数据库中的真实成绩快照，不应用覆盖。`custom` 只接受格式为 `cm` 加 9 位数字的 ID，并且只能查询当前用户拥有的虚拟账号；省略 `server` 时服务端也会根据该格式识别虚拟账号。

### 公共成绩字段

`scoreInfo` 中的成绩对象使用以下字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `song_no` | integer | 游戏侧歌曲 ID |
| `level` | integer | 难度，1 至 5 对应 Easy、Normal、Hard、Mania、Ura |
| `high_score` | integer | 最高分 |
| `best_score_rank` | integer | 最高分评价等级 |
| `good_cnt` | integer | 良数量 |
| `ok_cnt` | integer | 可数量 |
| `ng_cnt` | integer | 不可数量 |
| `pound_cnt` | integer | 连打数量 |
| `combo_cnt` | integer | 最大连击数 |
| `option_flg` | array | 演奏选项 |
| `tone_flg` | array | 音色数据 |
| `stage_cnt` | integer | 游玩次数 |
| `clear_cnt` | integer | 通关次数 |
| `full_combo_cnt` | integer | 全连次数 |
| `dondaful_combo_cnt` | integer | 全良次数 |
| `highscore_datetime` | string 或 null | 最高分时间，格式为 `YYYY-MM-DD HH:mm:ss` |
| `highscore_mode` | integer | 最高分模式标记 |
| `update_datetime` | string 或 null | 快照更新时间，格式为 `YYYY-MM-DD HH:mm:ss` |

### `GET /scores/hiroba`

返回每首歌每个难度的最新有效成绩。每个 `scoreInfo` 项在公共成绩字段外增加 `song_detail`。

`song_detail` 字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | integer | 游戏侧歌曲 ID；缺少曲库资料时为 `-1` |
| `type` | string | 分区名称 |
| `genreType` | integer | 分区 ID |
| `song_name_jp` | string | 日文标题 |
| `song_name` | string | 中文标题；缺失时回退到日文标题 |
| `subtitle` | string | 中文副标题 |
| `level_1` 至 `level_5` | integer 或 string | 五个难度的星级；缺失时为 `"-"` |
| `sort` | integer | 兼容字段 |
| `open_day` | string | 兼容字段 |
| `isPlayed` | boolean | 兼容字段，当前为 `true` |

<code-tabs id="hiroba"></code-tabs>

请求示例：

```bash
curl "https://kinoko.zorua.cn/api/v1/scores/hiroba" \
  -H "Authorization: Bearer tk_your_api_key"
```

响应示例：

```json
{
  "data": {
    "playedRecords": {
      "userid": "55327230",
      "server": "cn",
      "scoreInfo": [
        {
          "song_no": 938,
          "level": 4,
          "high_score": 1002500,
          "best_score_rank": 7,
          "good_cnt": 600,
          "ok_cnt": 12,
          "ng_cnt": 1,
          "pound_cnt": 88,
          "combo_cnt": 612,
          "option_flg": [1, 0, 0, "00"],
          "tone_flg": [],
          "stage_cnt": 5,
          "clear_cnt": 4,
          "full_combo_cnt": 1,
          "dondaful_combo_cnt": 0,
          "highscore_datetime": "2026-08-03 12:00:00",
          "highscore_mode": 0,
          "update_datetime": "2026-08-04 12:30:45",
          "song_detail": {
            "sort": 0,
            "id": 938,
            "open_day": "01/01/2765",
            "type": "流行音乐",
            "genreType": 1,
            "song_name_jp": "サンプル曲",
            "song_name": "示例曲",
            "subtitle": "",
            "level_1": 3,
            "level_2": 5,
            "level_3": 6,
            "level_4": 8,
            "level_5": "-",
            "isPlayed": true
          }
        }
      ]
    }
  }
}
```

### `GET /scores/kinoko`

按 `song_no + level` 分组返回全部有效成绩历史。外层使用 `player_id`，每个 `scoreInfo` 项代表一个谱面。

| 谱面字段 | 类型 | 说明 |
| --- | --- | --- |
| `song_no` | integer | 游戏侧歌曲 ID |
| `level` | integer | 难度，1 至 5 |
| `title` | string | 日文标题 |
| `title_cn` | string | 中文标题 |
| `subTitle` | string | 日文副标题 |
| `subTitle_cn` | string | 中文副标题 |
| `genre` | string | 分区名称 |
| `genreType` | integer | 分区 ID |
| `scoreInfo` | array | 按 `update_datetime` 倒序排列的公共成绩对象 |

<code-tabs id="kinoko"></code-tabs>

请求示例：

```bash
curl "https://kinoko.zorua.cn/api/v1/scores/kinoko?player_id=001234567890&server=jp" \
  -H "Authorization: Bearer tk_your_api_key"
```

响应示例：

```json
{
  "data": {
    "playedRecords": {
      "player_id": "001234567890",
      "server": "jp",
      "scoreInfo": [
        {
          "song_no": 938,
          "level": 4,
          "title": "サンプル曲",
          "title_cn": "示例曲",
          "subTitle": "",
          "subTitle_cn": "",
          "genre": "流行音乐",
          "genreType": 1,
          "scoreInfo": [
            {
              "song_no": 938,
              "level": 4,
              "high_score": 1002500,
              "best_score_rank": 7,
              "good_cnt": 600,
              "ok_cnt": 12,
              "ng_cnt": 1,
              "pound_cnt": 88,
              "combo_cnt": 612,
              "option_flg": [1, 0, 0, "00"],
              "tone_flg": [],
              "stage_cnt": 5,
              "clear_cnt": 4,
              "full_combo_cnt": 1,
              "dondaful_combo_cnt": 0,
              "highscore_datetime": "2026-08-03 12:00:00",
              "highscore_mode": 0,
              "update_datetime": "2026-08-04 12:30:45"
            }
          ]
        }
      ]
    }
  }
}
```

### `GET /scores/hiroba/recent`

返回最新一份每日汇总中出现过的谱面，并为每个谱面保留最新有效成绩。查询字段和响应字段与 `GET /scores/hiroba` 相同。

<code-tabs id="hiroba-recent"></code-tabs>

请求示例：

```bash
curl "https://kinoko.zorua.cn/api/v1/scores/hiroba/recent" \
  -H "Authorization: Bearer tk_your_api_key"
```

响应示例：

```json
{
  "data": {
    "playedRecords": {
      "userid": "55327230",
      "server": "cn",
      "scoreInfo": []
    }
  }
}
```

### `GET /scores/kinoko/recent`

返回最新一份每日汇总中出现过的谱面及其全部有效成绩历史。查询字段和响应字段与 `GET /scores/kinoko` 相同。

<code-tabs id="kinoko-recent"></code-tabs>

请求示例：

```bash
curl "https://kinoko.zorua.cn/api/v1/scores/kinoko/recent?player_id=001234567890&server=jp" \
  -H "Authorization: Bearer tk_your_api_key"
```

响应示例：

```json
{
  "data": {
    "playedRecords": {
      "player_id": "001234567890",
      "server": "jp",
      "scoreInfo": []
    }
  }
}
```

## 5. 用户资料

### `GET /user/profile`

返回 OAuth access token 对应的站内用户资料。该端点只接受 `oa_`，需要 `read_user_profile`。

请求示例：

```bash
curl "https://kinoko.zorua.cn/api/v1/user/profile" \
  -H "Authorization: Bearer oa_your_access_token"
```

响应字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `schema_version` | integer | 当前为 `1` |
| `user.id` | string | 站内用户 ID |
| `user.username` | string | 用户名 |
| `user.email` | string 或 null | 用户邮箱 |

响应示例：

```json
{
  "schema_version": 1,
  "user": {
    "id": "6891f3a08c176c6f41234567",
    "username": "example_user",
    "email": "user@example.com"
  }
}
```

### `GET /user/hiroba-binds`

返回授权用户已验证、已启用且存在玩家资料的绑定。数组顺序与用户在账号页设置的手动顺序一致，结果可能包含国服、日服和虚拟账号。该端点只接受 `oa_`，需要 `read_user_profile`。

请求示例：

```bash
curl "https://kinoko.zorua.cn/api/v1/user/hiroba-binds" \
  -H "Authorization: Bearer oa_your_access_token"
```

绑定字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `bind_id` | string | 后续玩家端点使用的绑定 ID |
| `server` | string | `cn`、`jp` 或 `custom` |
| `player_id` | string | 玩家 ID |
| `player` | object | 玩家资料白名单 |

`player` 字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `server` | string | `cn`、`jp` 或 `custom` |
| `userid` | string | 玩家 ID |
| `mydon_name` | string | 鼓手名 |
| `title` | string | 称号 |
| `is_disp_dan_on` | boolean | 是否显示段位 |
| `is_disp_tojiru_on` | boolean | 是否启用资料显示选项 |
| `titleplate_id` | integer | 称号牌 ID |
| `costume_1` 至 `costume_5` | integer | 外观部件 ID |
| `color_limb`、`color_body`、`color_face` | integer | 外观颜色 ID |
| `got_dan_max`、`dan_grade`、`dan_level` | integer | 段位资料 |
| `last_update` | string 或 null | 最近更新时间，UTC ISO 8601 |
| `update_history` | array | 历次更新时间，UTC ISO 8601 |
| `score_info` | object 或 null | 成绩面板统计 |

`score_info` 字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `count_level` | integer | 成绩面板等级统计 |
| `ary_crown_count` | array | 三个皇冠数量，长度固定为 3 |
| `ary_score_rank_count` | array | 七个评价等级数量，长度固定为 7 |

虚拟账号的 `player_id` 和 `player.userid` 都是 `cm` 加 9 位数字。虚拟账号资料由账号页维护，资源 API 只返回资料和成绩统计，不提供远端广场状态。

响应示例：

```json
{
  "schema_version": 1,
  "binds": [
    {
      "bind_id": "68920af78c176c6f47654321",
      "server": "jp",
      "player_id": "001234567890",
      "player": {
        "server": "jp",
        "userid": "001234567890",
        "mydon_name": "DONCHAN",
        "is_disp_dan_on": true,
        "is_disp_tojiru_on": false,
        "title": "全良挑戦中",
        "titleplate_id": 12,
        "costume_1": 1,
        "costume_2": 2,
        "costume_3": 3,
        "costume_4": 4,
        "costume_5": 5,
        "color_limb": 3,
        "color_body": 1,
        "color_face": 0,
        "got_dan_max": 10,
        "dan_grade": 3,
        "dan_level": 10,
        "last_update": "2026-08-04T12:30:45Z",
        "update_history": ["2026-08-03T12:20:00Z", "2026-08-04T12:30:45Z"],
        "score_info": {
          "count_level": 5,
          "ary_crown_count": [120, 35, 8],
          "ary_score_rank_count": [0, 0, 1, 8, 32, 79, 43]
        }
      }
    }
  ]
}
```

## 6. 单曲历史

### `GET /players/{bind_id}/scores/{kinoko_id}/{level}/history`

返回一个绑定在指定谱面的真实聚合快照，按 `update_datetime` 倒序排列。该端点接受 `tk_`，或带 `read_player` 的 `oa_`。

路径字段：

| 字段 | 类型 | 规则 |
| --- | --- | --- |
| `bind_id` | string | 来自 `GET /user/hiroba-binds` 或账号页绑定列表 |
| `kinoko_id` | integer | 大于等于 1 的菌菌曲目 ID |
| `level` | integer | 1 至 5 |

请求示例：

```bash
curl "https://kinoko.zorua.cn/api/v1/players/68920af78c176c6f47654321/scores/42/4/history" \
  -H "Authorization: Bearer tk_your_api_key"
```

响应字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `schema_version` | integer | 当前为 `3` |
| `song` | object 或 null | 歌曲摘要；曲库缺少记录时为 `null` |
| `selected_level` | integer | 请求的难度 |
| `charts` | array | 固定五个难度槽，按 1 至 5 排列 |
| `items` | array | 真实成绩快照 |

`song` 字段（曲库缺少记录时为 `null`）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `kinoko_id` | integer | 菌菌曲目 ID |
| `game_id` | integer 或 null | 游戏侧歌曲 ID |
| `title` | object | `{jp, zh}` 标题 |
| `subtitle` | object | `{jp, zh}` 副标题 |
| `genre_type` | integer 或 null | 主分类 ID |
| `genre_name` | string | 主分类名称 |

每个 `charts` 项字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `level` | integer | 难度，1 至 5 |
| `difficulty` | string | Easy、Normal、Hard、Mania 或 Ura |
| `stars` | integer 或 null | 星级，缺失时为 `null` |
| `pic_link` | string 或 null | 谱面图片链接 |
| `wiki_link` | string 或 null | 维基链接 |

`items` 使用公共成绩字段中的判定、次数和时间字段，但不包含 `song_no`、`level`、`tone_flg` 和 `highscore_mode`。

响应示例：

```json
{
  "schema_version": 3,
  "song": {
    "kinoko_id": 42,
    "game_id": 938,
    "title": {"jp": "サンプル曲", "zh": "示例曲"},
    "subtitle": {"jp": "", "zh": ""},
    "genre_type": 1,
    "genre_name": "流行音乐"
  },
  "selected_level": 4,
  "charts": [
    {"level": 1, "difficulty": "Easy", "stars": 3, "pic_link": null, "wiki_link": null},
    {"level": 2, "difficulty": "Normal", "stars": 5, "pic_link": null, "wiki_link": null},
    {"level": 3, "difficulty": "Hard", "stars": 6, "pic_link": null, "wiki_link": null},
    {"level": 4, "difficulty": "Mania", "stars": 8, "pic_link": "/taiko_assets/fumen_img/42_4.png", "wiki_link": null},
    {"level": 5, "difficulty": "Ura", "stars": null, "pic_link": null, "wiki_link": null}
  ],
  "items": [
    {
      "high_score": 1002500,
      "good_cnt": 600,
      "ok_cnt": 12,
      "ng_cnt": 1,
      "pound_cnt": 88,
      "combo_cnt": 612,
      "best_score_rank": 7,
      "full_combo_cnt": 1,
      "dondaful_combo_cnt": 0,
      "stage_cnt": 5,
      "clear_cnt": 4,
      "option_flg": [1, 0, 0, "00"],
      "highscore_datetime": "2026-08-03T12:00:00Z",
      "update_datetime": "2026-08-04T12:30:45Z"
    }
  ]
}
```

## 7. 成绩汇总

### `GET /players/{bind_id}/score-summaries`

按 UTC 日期倒序返回同步后持久化的每日汇总。该端点接受 `tk_`，或带 `read_player` 的 `oa_`。

路径字段：

| 字段 | 类型 | 规则 |
| --- | --- | --- |
| `bind_id` | string | 当前账号的有效绑定 ID |

查询字段：

| 字段 | 类型 | 默认值 | 规则 |
| --- | --- | --- | --- |
| `start_date` | string | `end_date` 前 89 天 | `YYYY-MM-DD` |
| `end_date` | string | 当前 UTC 日期 | `YYYY-MM-DD` |
| `page` | integer | `1` | 大于等于 1 |
| `page_size` | integer | `30` | 1 至 100 |

日期范围最多包含 366 个自然日。

请求示例：

```bash
curl "https://kinoko.zorua.cn/api/v1/players/68920af78c176c6f47654321/score-summaries?start_date=2026-08-01&end_date=2026-08-05&page=1&page_size=30" \
  -H "Authorization: Bearer oa_your_access_token"
```

每个 `items` 项包含：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `date` | string | 汇总日期，UTC ISO 8601 |
| `total_played_count` | integer | 累计游玩次数 |
| `increased_songs` | integer | 当日有进展的谱面数 |
| `played_songs` | array | 当日游玩谱面及次数 |
| `rating` | number | Rating |
| `daigouryoku` | number | 大综合力 |
| `accuracy_power` | number | 准度能力 |
| `stamina` | number | 体力能力 |
| `speed` | number | 速度能力 |
| `rhythm` | number | 节奏能力 |
| `complex_power` | number | 复合能力 |

每个 `played_songs` 项字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `kinoko_id` | integer | 菌菌曲目 ID |
| `song_no` | integer | 游戏侧歌曲 ID |
| `level` | integer | 难度，1 至 5 |
| `played_count` | integer | 当日游玩次数 |

`pagination` 字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `page` | integer | 当前页码 |
| `page_size` | integer | 每页数量 |
| `total` | integer | 匹配总数 |

响应示例：

```json
{
  "schema_version": 1,
  "bind": {
    "bind_id": "68920af78c176c6f47654321",
    "server": "jp",
    "player_id": "001234567890"
  },
  "items": [
    {
      "date": "2026-08-04T00:00:00Z",
      "total_played_count": 1200,
      "increased_songs": 5,
      "played_songs": [
        {"kinoko_id": 42, "song_no": 938, "level": 4, "played_count": 2}
      ],
      "rating": 8.125,
      "daigouryoku": 7.81,
      "accuracy_power": 8.45,
      "stamina": 7.92,
      "speed": 8.01,
      "rhythm": 8.22,
      "complex_power": 7.76
    }
  ],
  "pagination": {"page": 1, "page_size": 30, "total": 1}
}
```

## 8. 玩家同步

以下三个端点只接受带 `write_player` 的 `oa_`。个人 API Key 不可使用。

### 同步状态字段

同步与导入响应共用以下结构：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `schema_version` | integer | 当前为 `1` |
| `bind.bind_id` | string | 绑定 ID |
| `bind.server` | string | `cn`、`jp` 或 `custom` |
| `bind.player_id` | string | 玩家 ID |
| `update_status.status` | string | `idle`、`queued`、`running`、`completed` 或 `failed` |
| `update_status.message` | string | 可向用户显示的脱敏状态信息 |
| `update_status.started_at` | string 或 null | 开始时间，UTC ISO 8601 |
| `update_status.finished_at` | string 或 null | 完成时间，UTC ISO 8601 |

### `POST /players/{bind_id}/sync`

触发国服绑定同步，在请求内完成并返回 `200`。日服远端爬取已停用，返回 `400 JP_IMPORT_REQUIRED`，请使用脚本采集后调用 `/players/{bind_id}/scores/import`。虚拟账号没有远端数据源，调用时返回 `400 CUSTOM_SYNC_UNSUPPORTED`。同一玩家有 5 分钟冷却，且同一时间只能执行一个写入任务。

请求示例：

```bash
curl -X POST "https://kinoko.zorua.cn/api/v1/players/68920af78c176c6f47654321/sync" \
  -H "Authorization: Bearer oa_your_access_token"
```

响应示例：

```json
{
  "schema_version": 1,
  "bind": {
    "bind_id": "68920af78c176c6f47654321",
    "server": "cn",
    "player_id": "55327230"
  },
  "update_status": {
    "status": "completed",
    "message": "更新成功",
    "started_at": "2026-08-05T10:00:00Z",
    "finished_at": "2026-08-05T10:00:08Z"
  }
}
```

### `GET /players/{bind_id}/sync-status`

读取持久化同步或导入状态，不触发新任务，也不消耗玩家写入频率额度。日服仍可查询已有状态，前端不再轮询旧爬取任务。

请求示例：

```bash
curl "https://kinoko.zorua.cn/api/v1/players/68920af78c176c6f47654321/sync-status" \
  -H "Authorization: Bearer oa_your_access_token"
```

响应使用“同步状态字段”中的结构。例如任务完成后：

```json
{
  "schema_version": 1,
  "bind": {
    "bind_id": "68920af78c176c6f47654321",
    "server": "jp",
    "player_id": "001234567890"
  },
  "update_status": {
    "status": "completed",
    "message": "日服成绩导入完成",
    "started_at": "2026-08-05T10:00:00Z",
    "finished_at": "2026-08-05T10:03:12Z"
  }
}
```

### `POST /players/{bind_id}/scores/import`

导入日服书签脚本或虚拟账号生成的 canonical 快照。绑定必须属于日服或虚拟账号；请求体只能包含 `playerInfo` 和 `scoreInfo`，总字节数最多 5 MiB，`scoreInfo` 业务上限为 5000 项。

顶层字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `playerInfo` | object | 是 | 玩家资料；`userid` 必须与绑定一致。虚拟账号只校验该 ID，不更新资料字段 |
| `scoreInfo` | array | 是 | 成绩快照，最多处理前 5000 项 |

`playerInfo` 字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `userid` | string | 是 | 必须与目标绑定一致 |
| `mydon_name` | string | 否 | 鼓手名；日服按白名单更新，虚拟账号忽略 |
| `title` | string | 否 | 称号 |
| `is_disp_dan_on` | boolean | 否 | 是否显示段位 |
| `is_disp_tojiru_on` | boolean | 否 | 是否启用资料显示选项 |
| `titleplate_id` | integer | 否 | 称号牌 ID |
| `got_dan_max`、`dan_grade`、`dan_level` | integer | 否 | 段位资料 |
| `costume_1` 至 `costume_5` | integer | 否 | 外观部件 ID |
| `color_limb`、`color_body`、`color_face` | integer | 否 | 外观颜色 ID |
| `score_info` | object | 否 | 成绩面板统计（见下） |

`score_info` 字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `count_level` | integer | 成绩面板等级统计 |
| `ary_crown_count` | array | 三个皇冠数量，长度固定为 3 |
| `ary_score_rank_count` | array | 七个评价等级数量，长度固定为 7 |

日服导入按既有字段白名单更新资料；虚拟账号只保留 `userid`、成绩和导入时间，不更新玩家名、称号、段位或外观。

`scoreInfo` 每项字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `song_no` | integer | 是 | 游戏侧歌曲 ID，用于定位谱面 |
| `level` | integer | 是 | 难度，1 至 5 |
| `source_url` | string | 否 | 书签脚本来源地址 |
| 公共成绩字段 | - | 否 | 见第 4 节“公共成绩字段” |

`song_no` 和 `level` 缺失或小于等于 0 的项会计入 `skipped_invalid`。服务端会过滤未列入白名单的字段、重复谱面和旧快照。

请求示例：

```bash
curl -X POST "https://kinoko.zorua.cn/api/v1/players/68920af78c176c6f47654321/scores/import" \
  -H "Authorization: Bearer oa_your_access_token" \
  -H "Content-Type: application/json" \
  --data-binary @hiroba-jp-snapshot.json
```

`hiroba-jp-snapshot.json` 示例：

```json
{
  "playerInfo": {
    "userid": "001234567890",
    "mydon_name": "DONCHAN",
    "title": "全良挑戦中",
    "score_info": {
      "count_level": 5,
      "ary_crown_count": [120, 35, 8],
      "ary_score_rank_count": [0, 0, 1, 8, 32, 79, 43]
    }
  },
  "scoreInfo": [
    {
      "song_no": 938,
      "level": 4,
      "high_score": 1002500,
      "best_score_rank": 7,
      "good_cnt": 600,
      "ok_cnt": 12,
      "ng_cnt": 1,
      "pound_cnt": 88,
      "combo_cnt": 612,
      "option_flg": [1, 0, 0, "00"],
      "tone_flg": [],
      "stage_cnt": 5,
      "clear_cnt": 4,
      "full_combo_cnt": 1,
      "dondaful_combo_cnt": 0,
      "highscore_datetime": "2026-08-03T12:00:00Z",
      "highscore_mode": 0,
      "update_datetime": "2026-08-04T12:30:45Z"
    }
  ]
}
```

虚拟账号导入使用相同路径和结构，只需把 `playerInfo.userid` 改为目标绑定的 `cm` ID。例如目标为 `cm234567890` 时，载荷至少包含：

```json
{
  "playerInfo": {"userid": "cm234567890"},
  "scoreInfo": []
}
```

服务端会把每条成绩写入 `server="custom" + player_id="cm234567890"`，不会因为成绩文件中的玩家名、称号或外观字段改变账号资料。

成功响应在同步状态字段外增加 `import_result`：

| 字段 | 说明 |
| --- | --- |
| `valid` | 通过基本字段解析的成绩数 |
| `mapped` | 成功映射到菌菌曲库的成绩数 |
| `skipped_unmapped` | 未映射到曲库的成绩数 |
| `inserted` | 新增快照数 |
| `updated` | 更新现有快照数 |
| `unchanged` | 内容未变化的成绩数 |
| `skipped_stale` | 因早于现有数据而跳过的成绩数 |
| `received` | 请求中收到的成绩总数 |
| `skipped_extra` | 超过 5000 项限制而跳过的数量 |
| `skipped_invalid` | 格式无效的成绩数 |

```json
{
  "schema_version": 1,
  "bind": {
    "bind_id": "68920af78c176c6f47654321",
    "server": "jp",
    "player_id": "001234567890"
  },
  "update_status": {
    "status": "completed",
    "message": "书签脚本成绩导入完成",
    "started_at": "2026-08-05T11:00:00Z",
    "finished_at": "2026-08-05T11:00:08Z"
  },
  "import_result": {
    "valid": 1,
    "mapped": 1,
    "skipped_unmapped": 0,
    "inserted": 1,
    "updated": 0,
    "unchanged": 0,
    "skipped_stale": 0,
    "received": 1,
    "skipped_extra": 0,
    "skipped_invalid": 0
  }
}
```

玩家写入端点的 POST 请求同时按来源 IP、OAuth access token 和 OAuth `client_id` 限流。账户页的 JWT 导入按来源 IP、用户和 token 限流；收到 `429` 时应等待 `Retry-After`，不要并发重试。

## 9. 错误与重试

`/user/*` 和 `/players/*` 使用稳定错误结构：

```json
{
  "code": "INSUFFICIENT_SCOPE",
  "detail": "当前令牌缺少 read_player 权限"
}
```

| HTTP | 常见错误码 | 处理方式 |
| --- | --- | --- |
| `400` | `INVALID_REQUEST`、`INVALID_IMPORT_PAYLOAD`、`IMPORT_CN_NOT_ALLOWED`、`CUSTOM_SYNC_UNSUPPORTED` | 修正参数、改用导入或请求体 |
| `401` | `INVALID_TOKEN` | OAuth 尝试刷新一次；个人 API Key 需要重新创建或配置 |
| `403` | `INSUFFICIENT_SCOPE` | 重新授权所需 scope |
| `404` | `BIND_NOT_FOUND` | 重新读取有效绑定列表 |
| `409` | `SYNC_IN_PROGRESS` | 等待当前写入完成 |
| `429` | `RATE_LIMITED`、`SYNC_COOLDOWN` | 按 `Retry-After` 或冷却提示退避，不并发重试 |
| `413` | `IMPORT_PAYLOAD_TOO_LARGE` | 将 JSON 请求体缩小到 5 MiB 以内 |
| `500` | `INTERNAL_ERROR` | 保留端点和请求关联信息后稍后重试，不记录凭证或响应正文 |

四个 `/scores/*` 兼容端点保留 FastAPI 的 `{"detail": "..."}` 错误结构。

OAuth 客户端收到 `401` 后最多自动刷新一次。刷新失败时重新发起用户授权，不要在 OAuth token 和个人 API Key 之间自动回退。

## 10. 安全要求

- 不在 URL、日志、错误上报或分析事件中写入 `tk_`、`oa_` 或 `or_`。
- 不把个人 API Key、refresh token 或机密客户端 secret 放入浏览器公开代码。
- 使用 HTTPS 并校验证书；跨域跳转时不要转发 `Authorization`。
- 原始响应按 `no-store` 处理，只缓存业务所需的非敏感派生结果。
