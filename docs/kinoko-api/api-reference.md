# API 参考文档

## 1. 基础信息

- 网站 API Base URL：`/api`
- 公开 API Base URL：`/api/v1`
- 网站认证：`Authorization: Bearer <JWT>`
- 公开 API 认证：`Authorization: Bearer <tk_api_key>`
- 请求和响应格式：JSON

除健康检查、注册、登录和公开 API 外，其余网站接口默认需要 JWT。

## 2. 健康检查

### `GET /api/health`

响应：

```json
{ "status": "ok" }
```

## 3. 认证接口

### `POST /api/auth/register`

注册网站用户并返回 JWT。

请求体：

```json
{
  "username": "test_user",
  "email": "test@example.com",
  "password": "abc12345"
}
```

规则：

- 用户名 2-20 字符，可包含中文、英文、数字、下划线、短横线。
- 邮箱必填且格式合法。
- 密码至少 8 位，必须包含英文字母和数字。

响应：

```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "username": "test_user",
  "user_id": "6815f...",
  "email": "test@example.com"
}
```

### `POST /api/auth/login`

登录并返回 JWT。支持用户名或邮箱。

用户名登录：

```json
{
  "username": "test_user",
  "password": "abc12345"
}
```

邮箱登录：

```json
{
  "email": "test@example.com",
  "password": "abc12345"
}
```

响应同注册接口。

### `PATCH /api/auth/password`

修改密码。

请求体：

```json
{
  "old_password": "abc12345",
  "new_password": "newabc12345"
}
```

响应：

```json
{ "message": "密码已更新" }
```

### `PATCH /api/auth/email`

修改邮箱。

请求体：

```json
{ "email": "new@example.com" }
```

响应：

```json
{
  "message": "邮箱已更新",
  "email": "new@example.com"
}
```

## 4. 账号接口

### `GET /api/account/me`

获取当前用户。

响应：

```json
{
  "id": "6815f...",
  "username": "test_user",
  "email": "test@example.com",
  "created_at": "2026-05-04T12:00:00"
}
```

### `PATCH /api/account/username`

修改用户名。

请求体：

```json
{ "username": "new_name" }
```

响应：

```json
{ "username": "new_name" }
```

### `GET /api/app/cache-manifest`

返回前端主动刷新缓存所需的轻量版本清单，匿名和登录状态均可访问，响应头固定为 `Cache-Control: no-store`。曲库继续使用原 `/api/scores/catalog` 端点；前端把 `schema_version` 与 `version` 共同写入完整请求 URL，以绕开旧 Service Worker 正文。

```json
{
  "server_time": "2026-07-26T12:00:00",
  "public": {
    "music_catalog": {
      "schema_version": 3,
      "version": "sha256:...",
      "url": "/api/scores/catalog"
    }
  },
  "user": {
    "score_binds": [],
    "unread": null
  }
}
```

该清单不返回曲库正文、完整成绩、账号密钥或其它大体积/敏感数据。登录状态只会在 `user` 中增加当前用户的轻量活跃绑定版本和未读摘要。

## 5. 鼓众广场绑定接口

`/api/account/hiroba-binds` 系列接口支持国服和日服鼓众广场。后端按 `userid` 位数自动识别服务器：12 位太鼓番为日服，其余纯数字默认国服；也可以在请求体中显式传 `server: "cn" | "jp"`。

### `GET /api/account/hiroba-binds`

获取当前用户全部绑定，包括未验证或已停用绑定。每条绑定包含玩家资料和前端绘制用 `render_assets`。

响应结构：

```json
{
  "binds": [
    {
      "bind_id": "68160...",
      "created_at": "2026-05-04T12:00:00",
      "server": "cn",
      "player_id": "55327230",
      "authed": true,
      "enabled": true,
      "auth_str": "ド",
      "update_status": {
        "status": "idle",
        "message": "",
        "started_at": null,
        "finished_at": null
      },
      "verify_hint": null,
      "player": {
        "id": "68160...",
        "server": "cn",
        "userid": "55327230",
        "mydon_name": "菌菌",
        "title": "喜欢太鼓",
        "titleplate_id": 2,
        "is_disp_dan_on": true,
        "costume_1": 36,
        "costume_2": 144,
        "costume_3": 30,
        "costume_4": 0,
        "costume_5": 18,
        "color_limb": 3,
        "color_body": 3,
        "color_face": 3,
        "dan_grade": 4,
        "dan_level": 2,
        "got_dan_max": 12,
        "score_info": {
          "count_level": 4,
          "ary_crown_count": [10, 20, 30],
          "ary_score_rank_count": [1, 2, 3, 4, 5, 6, 7]
        },
        "last_update": "2026-05-04T12:00:00"
      },
      "render_assets": {
        "don": { "layers": ["/api/static/taiko/...png"] },
        "nameplate": {
          "background_url": "https://...",
          "dani_icon_url": "https://..."
        },
        "score_plate": {
          "background_url": "https://...",
          "count_level": 4
        }
      }
    }
  ]
}
```

### `POST /api/account/hiroba-binds`

按鼓众广场 `userid` 创建未验证绑定。如果本地没有玩家数据，后端会从对应服务器拉取资料。

请求体：

```json
{ "userid": "55327230" }
```

日服示例：

```json
{ "userid": "001026182502" }
```

响应：

```json
{
  "message": "绑定请求已创建，请按提示修改称号后验证",
  "bind": {}
}
```

### `POST /api/account/hiroba-binds/{bind_id}/verify`

重新拉取玩家资料，检查称号是否包含 `auth_str`，成功后标记为已验证。

响应：

```json
{
  "message": "验证成功",
  "bind": {}
}
```

### `POST /api/account/hiroba-binds/{bind_id}/update`

从国服鼓众广场拉取最新玩家资料和成绩，在成绩与汇总写入成功后保存更新时间并返回。日服远端同步已停用，返回 `400 JP_IMPORT_REQUIRED`；请进入 `/import/hiroba` 使用现有书签脚本导入。

响应：

```json
{
  "message": "更新成功",
  "bind": {},
  "update_status": {
    "status": "completed",
    "message": "更新成功",
    "started_at": "2026-06-06T22:00:00",
    "finished_at": "2026-06-06T22:00:08"
  }
}
```

### `GET /api/account/hiroba-binds/{bind_id}/update-status`

读取现有同步或导入状态，不启动任务。保留旧任务状态查询，前端不再自动轮询日服爬取任务。

响应：

```json
{
  "bind": {},
  "update_status": {
    "status": "running",
    "message": "正在导入日服成绩",
    "started_at": "2026-06-06T22:00:00",
    "finished_at": null
  }
}
```

`status` 可能为 `idle`、`queued`、`running`、`completed`、`failed`。

### `PATCH /api/account/hiroba-binds/{bind_id}/enabled`

启用或停用绑定。停用后不参与成绩查询和公开 API。

请求体：

```json
{ "enabled": false }
```

响应：

```json
{
  "message": "已停用",
  "bind": {}
}
```

### `DELETE /api/account/hiroba-binds/{bind_id}`

删除绑定。

响应：

```json
{ "message": "解绑成功" }
```

### `GET /api/account/hiroba-binds/{bind_id}/heatmap`

获取绑定账号游玩热力图。绑定必须已验证且已启用。

响应：

```json
{
  "data": [
    { "date": "2026-05-01", "count": 4 },
    { "date": "2026-05-02", "count": 0 }
  ]
}
```

### `GET /api/account/inherit-code-a`

生成引继绑定暗号 A。

响应：

```json
{ "code_a": "<code-a>" }
```

### `POST /api/account/inherit-code-b`

验证暗号 B，并创建已验证绑定。

请求体：

```json
{ "code_b": "<code-b>" }
```

响应：

```json
{
  "message": "绑定成功",
  "bind": {}
}
```

## 6. API 密钥接口

### `GET /api/account/api-keys`

获取当前用户 API 密钥列表。不会返回完整密钥；`revealable` 表示该密钥是否可再次显示完整内容（功能上线前创建的旧密钥为 `false`）。

响应：

```json
{
  "keys": [
    {
      "id": "68170...",
      "name": "主设备密钥",
      "key_prefix": "tk_xxxxxx...",
      "created_at": "2026-05-04T12:00:00",
      "revealable": true
    }
  ]
}
```

### `POST /api/account/api-keys`

创建 API 密钥。创建响应返回完整 `key`，之后也可以通过 reveal 端点再次查看。

请求体：

```json
{ "name": "我的查分脚本" }
```

响应：

```json
{
  "id": "68170...",
  "name": "我的查分脚本",
  "key": "tk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "key_prefix": "tk_xxxxxx...",
  "created_at": "2026-05-04T12:00:00"
}
```

### `GET /api/account/api-keys/{key_id}/reveal`

本人再次查看完整 API 密钥。响应固定为 `Cache-Control: no-store`，完整密钥不会进入日志、缓存或前端持久化。

响应：

```json
{
  "id": "68170...",
  "key": "tk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
}
```

功能上线前创建的旧密钥只有哈希、没有可逆密文，返回 `409`；密钥不存在或不属于当前用户时返回 `404`。

### `DELETE /api/account/api-keys/{key_id}`

删除 API 密钥。

响应：

```json
{ "message": "已删除" }
```

## 7. 成绩接口

### `GET /api/scores`

获取成绩列表。只查询当前用户已验证且已启用的绑定账号。响应头固定为 `Cache-Control: no-store`，`schema_version` 当前为 `3`；每项拆成 `score + song + chart`，前端在网络边界转换为统一 `PlayerScore`。缺歌时仍保留用户成绩，`song` 为 `null`，`chart` 返回对应难度的空元数据槽。

查询参数：

- `page`：页码，默认 1。
- `page_size`：每页数量。传 0 返回全部。
- `bind_id`：指定绑定。
- `sort_by`：`title`、`genre`、`high_score`、`good_cnt`、`ok_cnt`、`ng_cnt`、`update_datetime` 等。
- `sort_order`：`asc` 或 `desc`。

响应：

```json
{
  "schema_version": 3,
  "scores": [
    {
      "score": {
        "kinoko_id": 12345,
        "level": 2,
        "high_score": 1017060,
        "good_cnt": 236,
        "ok_cnt": 0,
        "ng_cnt": 0,
        "best_score_rank": 8,
        "clear_cnt": 5,
        "full_combo_cnt": 1,
        "dondaful_combo_cnt": 0,
        "highscore_datetime": "2025-07-26T19:40:00",
        "update_datetime": "2025-07-26T19:51:32"
      },
      "song": {
        "kinoko_id": 12345,
        "game_id": 72,
        "title": { "jp": "The Carnivorous Carnival", "zh": null },
        "subtitle": { "jp": "", "zh": null },
        "genre_type": 5,
        "genre_name": "ナムコオリジナル"
      },
      "chart": {
        "level": 2,
        "difficulty": "Normal",
        "stars": 7,
        "pic_link": null,
        "wiki_link": null
      }
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20,
  "binds": [
    {
      "bind_id": "68160...",
      "player_id": "55327230",
      "mydon_name": "菌菌",
      "last_update": "2026-05-04T12:00:00"
    }
  ],
  "selected_bind_id": "68160..."
}
```

### `GET /api/scores/catalog?schema_version=3&catalog_version={version}`

返回公共曲库 schema 3 正文。`songs` 使用数据库全部 `gameId != null` 的歌曲，按 `kinoko_id` 去重并带固定五槽 `charts`；歌曲文本使用 `title/subtitle.{jp,zh}`，分类使用 `genre_type/genre_name`。`placements` 仍完整保留 `order.json` 的国服游戏歌单分区位置，因此允许歌曲没有 placement，同一歌曲也可以出现多条 placement。`song_total` 与 `placement_total` 分别校验两组数据的数量。缺少或传错 `schema_version=3` 时返回 `409` 与 `Cache-Control: no-store`；合法响应允许公共长期缓存，`catalog_version` 只参与完整 URL 的缓存轮换，不改变查询结果。以下示例仅缩略展示一个 chart 槽，实际响应始终返回五槽。

```json
{
  "schema_version": 3,
  "songs": [
    {
      "kinoko_id": 12345,
      "game_id": 72,
      "title": { "jp": "Test Song", "zh": "测试曲" },
      "subtitle": { "jp": "", "zh": null },
      "genre_type": 5,
      "genre_name": "ナムコオリジナル",
      "charts": [
        { "level": 1, "difficulty": "Easy", "stars": 2, "pic_link": null, "wiki_link": null }
      ]
    }
  ],
  "placements": [
    { "catalog_id": "namco", "kinoko_id": 12345, "genre_id": 5, "order": 10, "position": 8, "total": 120 }
  ],
  "song_total": 1,
  "placement_total": 1
}
```

### `GET /api/scores/{kinoko_id}/{level}/history`

获取某歌曲某难度的历史成绩，同时返回规范歌曲摘要与固定五难度谱面摘要。

路径参数：`kinoko_id >= 1`，`level` 取 1-5，超出范围返回 `422`。

响应头固定为 `Cache-Control: no-store`。响应 `schema_version` 当前为 `3`；未知主分类、缺失 gameId 与缺失星数一律为 `null`，不回退成 `0` 或 `-1`。缺歌时 `song` 为 `null`，`charts` 仍返回五个空槽。

```json
{
  "schema_version": 3,
  "song": {
    "kinoko_id": 12345,
    "game_id": 72,
    "title": { "jp": "Test Song", "zh": "测试曲" },
    "subtitle": { "jp": "", "zh": null },
    "genre_type": 5,
    "genre_name": "ナムコオリジナル"
  },
  "selected_level": 5,
  "charts": [
    { "level": 1, "difficulty": "Easy", "stars": 2, "pic_link": null, "wiki_link": null },
    { "level": 2, "difficulty": "Normal", "stars": null, "pic_link": null, "wiki_link": null },
    { "level": 3, "difficulty": "Hard", "stars": 7, "pic_link": null, "wiki_link": null },
    { "level": 4, "difficulty": "Mania", "stars": null, "pic_link": null, "wiki_link": null },
    { "level": 5, "difficulty": "Ura", "stars": 10, "pic_link": null, "wiki_link": null }
  ],
  "items": [
    {
      "high_score": 1017060,
      "good_cnt": 236,
      "ok_cnt": 0,
      "ng_cnt": 0,
      "pound_cnt": 10,
      "combo_cnt": 500,
      "best_score_rank": 8,
      "full_combo_cnt": 1,
      "dondaful_combo_cnt": 0,
      "stage_cnt": 5,
      "clear_cnt": 5,
      "option_flg": [1, 0, 0, "00"],
      "update_datetime": "2025-07-26T19:51:32"
    }
  ]
}
```

### `GET /api/scores/songs/search`

搜索歌曲。

查询参数：

- `q`：关键词。
- `search_type`：`title`、`alias`、`combined`，默认 `title`。

响应：

响应头固定为 `Cache-Control: no-store`。响应 `schema_version` 当前为 `3`；三条搜索路径共用同一个 `SongSummaryDTO`。只有别名命中才带 `matched_level` 与 `matched_chart`，标题与模糊命中保持 `null`，不猜测谱面。`match.source` 取值为 `id`、`title`、`fuzzy`、`alias`。

```json
{
  "schema_version": 3,
  "search_type": "combined",
  "items": [
    {
      "song": {
        "kinoko_id": 12345,
        "game_id": 72,
        "title": { "jp": "The Carnivorous Carnival", "zh": null },
        "subtitle": { "jp": "", "zh": null },
        "genre_type": 5,
        "genre_name": "ナムコオリジナル"
      },
      "matched_level": 5,
      "matched_chart": {
        "level": 5,
        "difficulty": "Ura",
        "stars": 10,
        "pic_link": null,
        "wiki_link": null
      },
      "match": { "source": "alias", "alias": "食人狂欢" }
    }
  ]
}
```

### `GET /api/scores/songs/{kinoko_id}/sheet-chart`

获取表格选歌与覆盖弹窗所需的歌曲与谱面数据。响应头固定为 `Cache-Control: no-store`，`schema_version` 当前为 `3`；`charts` 固定按 Easy/Normal/Hard/Mania/Ura 输出五个槽位，缺失难度的 `stars` 为 `null`（不是 `0`）。歌曲不存在时返回 404。

```json
{
  "schema_version": 3,
  "song": {
    "kinoko_id": 12345,
    "game_id": 72,
    "title": { "jp": "The Carnivorous Carnival", "zh": null },
    "subtitle": { "jp": "", "zh": null },
    "genre_type": 5,
    "genre_name": "ナムコオリジナル"
  },
  "charts": [
    { "level": 1, "difficulty": "Easy", "stars": 3, "pic_link": null, "wiki_link": null },
    { "level": 2, "difficulty": "Normal", "stars": null, "pic_link": null, "wiki_link": null },
    { "level": 3, "difficulty": "Hard", "stars": 7, "pic_link": null, "wiki_link": null },
    { "level": 4, "difficulty": "Mania", "stars": 9, "pic_link": null, "wiki_link": null },
    { "level": 5, "difficulty": "Ura", "stars": 10, "pic_link": null, "wiki_link": null }
  ]
}
```

### `GET /api/scores/active-binds`

获取当前用户已验证且已启用的绑定。

响应：

```json
{
  "binds": [
    {
      "bind_id": "68160...",
      "player_id": 55327230,
      "mydon_name": "菌菌",
      "last_update": "2026-05-04T12:00:00"
    }
  ]
}
```

## 8. 分数覆盖接口

### `GET /api/scores/overrides`

获取当前用户所有活跃绑定玩家的覆盖成绩。响应头固定为 `Cache-Control: no-store`，`schema_version` 当前为 `3`。

列表项拆成 `override + song + chart`：`override` 只含身份与成绩数字，`song` 是共享的 `SongSummaryDTO`，`chart` 只返回该覆盖所在难度的谱面摘要（不是五槽数组）。歌曲已从曲库移除时 `song` 与 `chart` 都是 `null`，前端据此显示身份而不是伪造标题。

```json
{
  "schema_version": 3,
  "items": [
    {
      "override": {
        "id": "68200...",
        "server": "cn",
        "player_id": "55327230",
        "kinoko_id": 12345,
        "song_no": 72,
        "level": 4,
        "high_score": 1000000,
        "best_score_rank": 8,
        "good_cnt": 500,
        "ok_cnt": 0,
        "ng_cnt": 0,
        "pound_cnt": 0,
        "combo_cnt": 500,
        "option_flg": [1, 0, 0, "00"],
        "tone_flg": [0],
        "stage_cnt": 1,
        "clear_cnt": 1,
        "full_combo_cnt": 1,
        "dondaful_combo_cnt": 0,
        "highscore_datetime": "2765-01-01T00:00:00",
        "highscore_mode": 0,
        "update_datetime": "2765-01-01T00:00:00"
      },
      "song": {
        "kinoko_id": 12345,
        "game_id": 72,
        "title": { "jp": "The Carnivorous Carnival", "zh": null },
        "subtitle": { "jp": "", "zh": null },
        "genre_type": 5,
        "genre_name": "ナムコオリジナル"
      },
      "chart": { "level": 4, "difficulty": "Mania", "stars": 9, "pic_link": null, "wiki_link": null }
    }
  ]
}
```

### `POST /api/scores/overrides`

创建或更新覆盖成绩。按 `server + player_id + kinoko_id + level` upsert。要求当前用户对该服务器下的 `player_id` 有活跃绑定。

请求体：

```json
{
  "server": "cn",
  "player_id": "55327230",
  "song_no": 72,
  "kinoko_id": 12345,
  "level": 4,
  "high_score": 1000000,
  "best_score_rank": 8,
  "good_cnt": 500,
  "ok_cnt": 0,
  "ng_cnt": 0,
  "pound_cnt": 0,
  "combo_cnt": 500,
  "option_flg": [1, 0, 0, "00"],
  "tone_flg": [0],
  "stage_cnt": 1,
  "clear_cnt": 1,
  "full_combo_cnt": 1,
  "dondaful_combo_cnt": 0,
  "highscore_datetime": "2026-05-01T12:00:00",
  "highscore_mode": 0,
  "update_datetime": "2026-05-01T12:00:00"
}
```

响应为 `{ schema_version, override, message }`，其中 `override` 只回执身份与成绩数字；分类文字与颜色既不持久化也不回传，页面保存后重新拉取列表即可。

### `DELETE /api/scores/overrides/{override_id}`

删除覆盖成绩。

响应：

```json
{ "message": "已删除" }
```

### `GET /api/scores/player/{player_id}/{kinoko_id}/{level}?server=cn`

获取指定玩家某歌曲某难度的最佳成绩，用于覆盖弹窗默认值。

响应：

```json
{
  "score": null
}
```

或：

```json
{
  "score": {
    "high_score": 1000000,
    "best_score_rank": 8,
    "good_cnt": 500,
    "ok_cnt": 0,
    "ng_cnt": 0,
    "pound_cnt": 0,
    "combo_cnt": 500,
    "option_flg": [1, 0, 0, "00"],
    "stage_cnt": 1,
    "clear_cnt": 1,
    "full_combo_cnt": 1,
    "dondaful_combo_cnt": 0,
    "highscore_datetime": "2026-05-01T12:00:00",
    "update_datetime": "2026-05-01T12:00:00"
  }
}
```

## 9. 歌曲别名接口

### `GET /api/scores/aliases/song/{kinoko_id}`

获取一首歌的别名数据。

### `POST /api/scores/aliases/update`

从在线文档更新别名数据，并返回变更日志。

## 10. 难易度表接口

### `GET /api/sheets/overview`

获取预设分组、自建表格、收藏表格。

响应：

```json
{
  "preset_groups": [],
  "my_tables": [],
  "favorites": []
}
```

### `GET /api/sheets/search`

搜索预设和公开表格。

查询参数：

- `q`
- `page`
- `page_size`

响应：

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 20
}
```

### `GET /api/sheets/{sheet_id}`

获取完整表格。私有表格仅所有者可见。响应顶层固定包含 `schema_version: 3`，每个谱面以 `kinoko_id + level` 标识，并附带使用 `jp/zh`、`genre_type/genre_name` 的规范 `song` 和固定五槽 `charts`。尚未离线迁移的 schema 1/2 表格返回 `503`，应用不会双读旧结构；部署步骤见 `docs/sheet-schema-v3-migration.md`。

### `POST /api/sheets/{sheet_id}/copy`

复制预设或公开表格为自己的私有表格。

### `POST /api/sheets`

创建自建表格。

请求体：

```json
{
  "name": "我的表格",
  "description": "",
  "short_name": "my-sheet"
}
```

### `PUT /api/sheets/{sheet_id}`

更新表格元数据。

请求体：

```json
{
  "name": "新名称",
  "description": "说明",
  "short_name": "new-short",
  "type": 2
}
```

`type` 仅允许 `1` 私有或 `2` 公开。

### `DELETE /api/sheets/{sheet_id}`

删除自建表格。

### `POST /api/sheets/{sheet_id}/favorite`

收藏表格。

### `DELETE /api/sheets/{sheet_id}/favorite`

取消收藏。

### 分类接口

- `POST /api/sheets/{sheet_id}/categories`
- `PUT /api/sheets/{sheet_id}/categories`
- `PUT /api/sheets/{sheet_id}/categories/reorder`
- `DELETE /api/sheets/{sheet_id}/categories/{name}`

新增分类请求：

```json
{ "name": "十段" }
```

重命名分类请求：

```json
{
  "old_name": "十段",
  "new_name": "玄人"
}
```

排序请求：

```json
{ "order": ["玄人", "名人", "超人"] }
```

### 谱面接口

- `POST /api/sheets/{sheet_id}/categories/{name}/charts`
- `PUT /api/sheets/{sheet_id}/categories/{name}/charts/reorder`
- `PUT /api/sheets/{sheet_id}/categories/{name}/charts/{index}`
- `DELETE /api/sheets/{sheet_id}/categories/{name}/charts/{index}`

谱面请求体：

```json
{
  "kinoko_id": 12345,
  "level": 4,
  "song": {
    "kinoko_id": 12345,
    "game_id": 72,
    "title": { "jp": "The Carnivorous Carnival", "zh": null },
    "subtitle": { "jp": "", "zh": null },
    "genre_type": 5,
    "genre_name": "南梦宫原创音乐"
  },
  "charts": [
    { "level": 1, "difficulty": "Easy", "stars": 3, "pic_link": null, "wiki_link": null },
    { "level": 2, "difficulty": "Normal", "stars": 5, "pic_link": null, "wiki_link": null },
    { "level": 3, "difficulty": "Hard", "stars": 7, "pic_link": null, "wiki_link": null },
    { "level": 4, "difficulty": "Mania", "stars": 9, "pic_link": null, "wiki_link": null },
    { "level": 5, "difficulty": "Ura", "stars": null, "pic_link": null, "wiki_link": null }
  ]
}
```

`charts` 必须严格按 Easy、Normal、Hard、Mania、Ura 返回五个槽位；缺失谱面的 `stars` 使用 `null`，不能使用 `0`。`song` 可为 `null`，用于保留曲库中已缺失歌曲的迁移快照。

分类名含特殊字符时，前端应对 `{name}` 使用 `encodeURIComponent`。

### `POST /api/sheets/{sheet_id}/batch-import`

批量导入谱面。支持 `merge` 和 `overwrite`。

请求体：

```json
{
  "imports": [
    {
      "target_category": "十段",
      "mode": "merge",
      "charts": [
        {
          "kinoko_id": 12345,
          "level": 4,
          "song": null,
          "charts": [
            { "level": 1, "difficulty": "Easy", "stars": 3, "pic_link": null, "wiki_link": null },
            { "level": 2, "difficulty": "Normal", "stars": 5, "pic_link": null, "wiki_link": null },
            { "level": 3, "difficulty": "Hard", "stars": 7, "pic_link": null, "wiki_link": null },
            { "level": 4, "difficulty": "Mania", "stars": 9, "pic_link": null, "wiki_link": null },
            { "level": 5, "difficulty": "Ura", "stars": null, "pic_link": null, "wiki_link": null }
          ]
        }
      ]
    }
  ]
}
```

## 11. 进步推荐接口

三个接口都需要网站 JWT，并固定返回 `Cache-Control: no-store`。`bind_id` 必须指向当前用户已验证且启用的绑定；不存在、越权或停用统一返回 `404`。Web projection 不改动机器人共用的 `step_up_tasks`、`step_up_cooldowns`、`step_up_group_stats` 与 `step_up_refresh_locks` 持久化模型。

### `GET /api/step-up/tasks/current?bind_id={bind_id}`

无副作用地读取指定绑定的最新课题；没有课题时 `task` 为 `null`。每首课题以 `kinoko_id + level` 标识，`song` 为可空规范歌曲元数据，`chart` 为对应难度谱面，`recommendation_placement` 为可空的推荐分区位置。

```json
{
  "bind_id": "507f1f77bcf86cd799439011",
  "task": {
    "id": "507f191e810c19729de860ea",
    "created_at": "2026-07-27T10:00:00",
    "groups": [
      {
        "code": "A",
        "recommend_type": 3,
        "songs": [
          {
            "kinoko_id": 12345,
            "level": 4,
            "song": null,
            "chart": { "level": 4, "difficulty": "Mania", "stars": 9, "pic_link": null, "wiki_link": null },
            "recommendation_placement": { "genre_id": 5, "position": 12, "total": 240 },
            "target_score": 950000,
            "initial_score": 900000,
            "initial_play_count": 3,
            "is_cleared": false,
            "is_locked": false,
            "recommend_type": 3,
            "crown_target_type": "",
            "initial_ok_count": null,
            "initial_ng_count": null,
            "target_ok_count": null,
            "target_ng_count": null
          }
        ]
      }
    ]
  }
}
```

### `PATCH /api/step-up/tasks/current/songs/lock`

设置当前任务中一首谱面的锁定状态，并返回完整当前课题。`expected_task_id` 必须与服务器当前任务一致；任务已变化或刷新租约繁忙时返回 `409`。

```json
{
  "bind_id": "507f1f77bcf86cd799439011",
  "expected_task_id": "507f191e810c19729de860ea",
  "kinoko_id": 12345,
  "song_level": 4,
  "locked": true
}
```

### `POST /api/step-up/tasks/refresh`

首次生成时 `expected_task_id` 可为 `null`；已有任务时必须传当前任务 ID。成功响应同时返回 `settled_task`、`settlement`、新 `task` 和 `generation.warnings`。刷新保留锁定课题，并通过 Web/机器人共享玩家租约与条件写避免并发覆盖。

```json
{
  "bind_id": "507f1f77bcf86cd799439011",
  "expected_task_id": "507f191e810c19729de860ea"
}
```

## 12. 公开 API

公开 API 使用 API 密钥，不使用 JWT。密钥由 `/api/account/api-keys` 创建。

可选查询参数：

- `player_id`：指定活跃绑定玩家。不传时使用第一个活跃绑定。日服 ID 需要按字符串保留前导 0。
- `server`：可选，`cn` 或 `jp`。不传时按 `player_id` 位数识别；`player_id` 也不传时使用第一个活跃绑定的服务器。

### `GET /api/v1/scores/hiroba`

返回鼓众广场风格全量成绩。每首歌取最新一条成绩，并附带 `song_detail`。

### `GET /api/v1/scores/kinoko`

返回菌菌风格全量成绩。按歌曲和难度组织，附带歌曲标题信息。

### `GET /api/v1/scores/hiroba/recent`

返回最近一天游玩的鼓众广场风格成绩。

### `GET /api/v1/scores/kinoko/recent`

返回最近一天游玩的菌菌风格成绩。

公开 API 会应用用户设置的分数覆盖。

## 13. 占位或历史接口

以下成绩接口仍为占位：

- `GET /api/scores/{score_id}`
- `PATCH /api/scores/{score_id}`
- `PATCH /api/scores/{score_id}/lock`
- `GET /api/scores/summary/heatmap`

旧的 `/api/taiko-data/*` 路由不再由主应用注册。渲染素材请使用 `/api/account/hiroba-binds` 返回的 `render_assets`。

## 14. 全国对战接口

前缀为 `/api/battles`，全部接口需要 JWT，成功和所有错误都返回 `Cache-Control: no-store`。当前 JSON 协议为 `schema_version=4`：bootstrap、列表和操作摘要在顶层携带版本，直接返回的 room/match 对象自身携带版本。schema 3 客户端必须刷新，不能把 schema 4 的阶段或卡组字段降级处理。错误正文固定为 `{ "detail": string, "code": string }`；校验错误使用 `INVALID_REQUEST`，未处理异常使用不包含内部细节的 `INTERNAL_ERROR`，前端应按 `code` 分支，不解析中文文案。

schema 4 的模式定义除人数、每人选曲数、选曲/传分秒数和房间选项外，还可携带选曲策略、阶段时限、最终歌曲槽与严格 `mode_config`。offer、room card、room、match card 与 match 均携带创建时冻结的 `rules` 摘要，match 另返回 `phase + phase_deadline_at`；客户端不得用当前 bootstrap 模式反推旧资源。旧 `duel/trio` 自动匹配禁止演奏选项并只填写总分，自建房间两项默认关闭且可独立设置。四个卡组模式固定允许卡牌声明的演奏选项，自动匹配只填写总分，自建房间只能切换详细判定。

- `GET /bootstrap?bind_id=`：首次进入页面所需的合格国服/日服身份、模式、当前活动、匹配池、进行中对局和历史预览。
- `GET /lobby?bind_id=`：3 秒轮询使用的轻量大厅状态。
- `POST /presence/heartbeat`：延长当前队列或房间活动心跳。
- `POST /matchmaking/queue`：按冻结 Rating 的对称 `±1` 窗口加入 1v1/1v1v1 FIFO 队列。请求固定包含 `bind_id/mode_id/action_id`；四个卡组模式还必须提交当前用户可参战的 `deck_id`，服务端按当前国服 catalog 复核后把完整卡组快照冻结到 queue engagement。相同 action 并发重试只在模式、绑定和条件卡组 ID 一致时返回先写入的权威 ticket。旧 `duel/trio` 不要求 `deck_id`。
- `POST /matchmaking/queue/{ticket_id}/cancel`：取消排队。
- `POST /matchmaking/offers/{offer_id}/respond`：接受或拒绝 60 秒邀请。卡组模式的邀请只返回参与者和响应状态，内部卡组及卡牌不会下发；全员接受后服务端按当前国服 catalog 复核冻结快照，失效时返回 `409 BATTLE_DECK_STALE`、关闭邀请并释放全部邀请占用，客户端可重新选择卡组入队。普通拒绝、超时或实时资格失效先持久化邀请终态，再幂等回队或释放占用；相同 action 重试返回同一终态，不能改成相反响应。已经创建的唯一 origin match 优先恢复，不受后续 catalog 变化影响。
- `GET/POST /rooms`：读取公开房间或创建公开/私密房间。创建请求除 `bind_id/mode_id/name/visibility/action_id` 外还包含 `rule_options: { allow_play_options, require_detailed_judgements }`；只能提交模式声明为可配置的选项。
- `POST /rooms/join-by-code`：通过六位数字暗号加入房间。
- `GET /rooms/{room_id}`：读取公开房间，私密房间仅成员可读。
- `POST /rooms/{room_id}/join|ready|leave|start`：加入、准备、离开和房主开局。
- `DELETE /rooms/{room_id}`：房主关闭房间。
- `GET /matches?scope=active|history&player_key=`：读取当前用户的对局列表。
- `GET /matches/{battle_id}`：参与者读取进行中对局；`battle:moderate` 维护者可读取进行中对局，任意登录用户可读取已结算或作废分享页。非参与者访问进行中对局时统一返回 404，包括对局恢复发现内部状态错误的情况。`deck_pick` 的禁选阶段返回 `deck_view.decks` 与 `deck_view.ban`；公开卡牌含 card ID、位置、歌曲、谱面、placement、演奏选项和稀有度。全员确认前 `revealed_bans=null`，参与者只能从 `my_targets` 读取自己的提交，维护者没有 `my_targets`。进入 pick 后，`pick_view` 返回各卡组被禁 card ID、本人选择和确认状态，完成前 `revealed_picks=null`，顶层 `selections=[]`。`shuffle_pick` 阶段不返回整套卡组，`shuffle_view.my_offer` 只向对应参与者返回三张候选；维护者看不到任何候选，完成前 `revealed_offers/revealed_picks=null`。进入 `scoring/settled/void` 后才返回完整冻结卡组、禁选、候选、最终选择和歌曲槽。对局响应不含卡牌编辑 `source`、`sheet_id/category`、owner、receipt、signature 或 action ID；历史不回查当前卡组。旧 `duel/trio` 的 selections 和 songs 保持原形状。
- `POST /matches/{battle_id}/deck-ban`：严格提交 `bans[{target_participant_id, card_ids[]}] + action_id`。`deck_duel` 必须包含对方一个目标且恰好两张卡；`deck_trio` 必须完整包含另外两个目标且每个恰好一张卡。目标、数量和卡牌归属由 match 冻结快照校验，同 action 只能重放相同规范结果。最后一名确认时服务端通过 revision CAS 原子进入 `pick` 并重置 180 秒期限。
- `POST /matches/{battle_id}/deck-pick`：严格提交 `card_id + action_id`，只能选择本人冻结卡组中未被任何对手禁选的一张卡。
- `POST /matches/{battle_id}/shuffle-pick`：严格提交 `card_id + action_id`，只能选择服务端为当前参与者冻结的三张候选之一；候选可以来自任一参赛卡组。
- 两种选卡接口都把 action 与完整卡牌快照写入 match。同 action 只能重放同一 `card_id`；最后一名确认时服务端按参与者席位生成 2 或 3 个独立歌曲槽，以及所有参与者乘歌曲槽的 pending 提交槽。不同玩家选择相同卡牌或谱面时仍保留独立歌曲槽，scoring 和 engagement 截止时间按冻结规则重置为 1800 秒。
- `POST /matches/{battle_id}/selection`：仅旧 `duel/trio` 使用，以 `kinoko_id + level` 确认国服曲库谱面；卡组阶段调用返回 `BATTLE_PHASE_INVALID`。
- `POST /matches/{battle_id}/submissions/{song_slot}`：multipart 始终提交 `action_id + score + photo`，`song_slot` 必须存在于 match 冻结歌曲槽；即使多个槽使用同一卡牌或谱面，也要分别提交。本场 `require_detailed_judgements=false` 时必须省略 `good/ok/bad/drumroll`；开启时四项必须全部提交。默认路径由前端缩放转码后提交 WebP，并附带 `client_processed=true`、`source_sha256`（原图 SHA-256，去重锚点）、`source_format` 和 `exif`（原图 EXIF TIFF 原始字节，≤64 KB）；无 `exif` 时可改用带时区偏移的 `capture_at + capture_timezone_source`。后端只做字节级校验后原样落盘，照片带 `EXIF` 或 `XMP ` 块返回 `IMAGE_METADATA_PRESENT`，浏览器正常写入的 `ICCP` 色彩配置必须放行。省略 `client_processed` 时按原始 JPEG/HEIC/HEIF 处理，由后端解码转换，作为 HEIC 与老浏览器的兜底。
- `GET /matches/{battle_id}/evidence/{evidence_id}`：经后端 ACL 读取私有 WebP 凭证。

参战写操作需要默认权限 `battle:play`。管理员移除该权限即禁赛；国服和日服已验证、已启用绑定均可参战，自动匹配必须有最新 `ScoreSummary.rating`。

新 v2 规则的选曲期限为 180 秒，传分期限从真正进入 scoring 时起算 1800 秒。只计总分时按整场总分排名；详细判定模式在总分相同时再比较整场良率。卡牌稀有度、来源和演奏选项只用于展示及人工核验，不进入分数、排名、平局或战绩计算。1v1 最终仍相等返回双方 `rank=1/tied=true/outcome=draw`，双方各增加 1 胜、不增加负场。旧 v1 资源继续要求详细判定并沿用原 1200 秒和旧并列战绩语义。

### `GET /api/account/unread-status`

需要登录，响应为 `no-store`。默认保持原四字段：`updates_unread`、`feedback_unread_count`、`feedback_unread_issue_numbers`、`score_guides_unread_count`。

传入 `include_score_binds=true` 时附加 `score_binds`，复用已验证、已启用绑定的六字段摘要：`bind_id`、`server`、`player_id`、`mydon_name`、`display_name`、`last_update`。`last_update` 为本系统保存的成功更新时间，浏览器用它比较成绩版本，不请求官网探测。
