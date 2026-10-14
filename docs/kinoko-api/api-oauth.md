# OAuth 协议 API

本文列出第三方应用使用的 OAuth 2.0 Authorization Code + PKCE 端点、字段和响应。资源端点见 [API 接入指南](/docs/api-guide)。

## 1. 基础信息

| 项目 | 值 |
| --- | --- |
| Issuer | `https://kinoko.zorua.cn` |
| 授权页 | `GET /oauth/authorize` |
| Token | `POST /api/oauth/token` |
| Revoke | `POST /api/oauth/revoke` |
| 元数据 | `GET /.well-known/oauth-authorization-server` |
| PKCE | 公共和机密客户端都必须使用 `S256` |
| 授权码有效期 | 5 分钟，只能成功交换一次 |
| Access token 有效期 | 15 分钟 |
| Refresh token 有效期 | 30 天，成功刷新后轮换 |

Token 和 Revoke 请求必须使用 `application/x-www-form-urlencoded`。不支持 HTTP Basic 客户端认证。

## 2. 客户端认证

| 客户端类型 | Token 和 Revoke 认证 | `client_secret` |
| --- | --- | --- |
| `public` | `none` | 不得提交 |
| `confidential` | `client_secret_post` | 在表单中提交 |

机密客户端的 secret 只能保存在可信服务端。SPA、桌面应用和移动应用应注册为公共客户端。

## 3. 端点一览

| 方法和路径 | 功能 | 用户登录 | 客户端认证 |
| --- | --- | --- | --- |
| `GET /.well-known/oauth-authorization-server` | 返回当前 OAuth 服务配置 | 不需要 | 不需要 |
| `GET /oauth/authorize` | 让用户确认授权并返回授权码 | 需要站内登录 | `client_id` + PKCE |
| `POST /api/oauth/token` | 用授权码换取 Token 或刷新 Token | 不需要 | 按客户端类型 |
| `POST /api/oauth/revoke` | 撤销 access token 或 refresh token family | 不需要 | 按客户端类型 |

## 4. 授权服务器元数据

### `GET /.well-known/oauth-authorization-server`

返回客户端接入所需的端点、grant、scope、PKCE 方法和认证方式。客户端应从该端点读取地址，不要根据当前页面 Host 拼接 OAuth URL。

请求示例：

```bash
curl "https://kinoko.zorua.cn/.well-known/oauth-authorization-server"
```

响应字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `issuer` | string | OAuth issuer |
| `authorization_endpoint` | string | 用户授权页地址 |
| `token_endpoint` | string | Token 端点地址 |
| `revocation_endpoint` | string | Revoke 端点地址 |
| `response_types_supported` | array | 当前为 `["code"]` |
| `grant_types_supported` | array | `authorization_code` 和 `refresh_token` |
| `code_challenge_methods_supported` | array | 当前为 `["S256"]` |
| `scopes_supported` | array | 当前支持的 scope |
| `token_endpoint_auth_methods_supported` | array | `none` 和 `client_secret_post` |

响应示例：

```json
{
  "issuer": "https://kinoko.zorua.cn",
  "authorization_endpoint": "https://kinoko.zorua.cn/oauth/authorize",
  "token_endpoint": "https://kinoko.zorua.cn/api/oauth/token",
  "revocation_endpoint": "https://kinoko.zorua.cn/api/oauth/revoke",
  "response_types_supported": ["code"],
  "grant_types_supported": ["authorization_code", "refresh_token"],
  "code_challenge_methods_supported": ["S256"],
  "scopes_supported": ["read_user_profile", "read_player", "write_player"],
  "token_endpoint_auth_methods_supported": ["none", "client_secret_post"]
}
```

## 5. 发起用户授权

### `GET /oauth/authorize`

在浏览器中打开授权页。用户未登录时会先进入站内登录页，之后返回授权流程。

查询字段：

| 字段 | 类型 | 必填 | 规则 |
| --- | --- | --- | --- |
| `response_type` | string | 是 | 固定为 `code` |
| `client_id` | string | 是 | 开发者中心显示的客户端 ID |
| `redirect_uri` | string | 是 | 必须与应用登记地址逐字符相同 |
| `scope` | string | 是 | 单个空格分隔，必须是应用登记 scope 的子集 |
| `state` | string | 是 | 16 至 512 字符，每次请求随机生成 |
| `code_challenge` | string | 是 | `BASE64URL(SHA256(code_verifier))`，无 `=` padding，固定 43 字符 |
| `code_challenge_method` | string | 是 | 固定为 `S256` |

`code_verifier` 使用 RFC 7636 允许的字符，长度为 43 至 128。它只保存在客户端，不能放入授权 URL、`state` 或日志。

授权 URL 示例：

```text
https://kinoko.zorua.cn/oauth/authorize?response_type=code&client_id=oc_example&redirect_uri=https%3A%2F%2Fapp.example.com%2Foauth%2Fcallback&scope=read_user_profile%20read_player&state=O0jM7Xh0JRf8JFOBYqhdss7oF17DJ1pW&code_challenge=0YLnE7D_VDGswFQFyNjG4335zjc98hXQXew1ZM51RiU&code_challenge_method=S256
```

用户同意后，服务端向已登记回调地址添加：

| 回调字段 | 说明 |
| --- | --- |
| `code` | 一次性授权码 |
| `state` | 请求中的原始 state |

成功回调示例：

```text
https://app.example.com/oauth/callback?code=ac_example_authorization_code&state=O0jM7Xh0JRf8JFOBYqhdss7oF17DJ1pW
```

用户拒绝时，可信回调地址收到：

```text
https://app.example.com/oauth/callback?error=access_denied&error_description=The%20user%20denied%20the%20request&state=O0jM7Xh0JRf8JFOBYqhdss7oF17DJ1pW
```

回调处理器必须先用恒定时间比较校验 `state`，再交换授权码。无效客户端或无效回调地址不会触发第三方跳转。

## 6. 用授权码换取 Token

### `POST /api/oauth/token`

表单字段：

| 字段 | 类型 | 公共客户端 | 机密客户端 | 规则 |
| --- | --- | --- | --- | --- |
| `grant_type` | string | 必填 | 必填 | 固定为 `authorization_code` |
| `client_id` | string | 必填 | 必填 | 必须与授权请求一致 |
| `client_secret` | string | 禁止 | 必填 | 机密客户端当前 secret |
| `code` | string | 必填 | 必填 | 回调收到的一次性授权码 |
| `redirect_uri` | string | 必填 | 必填 | 必须与授权请求及登记地址逐字符相同 |
| `code_verifier` | string | 必填 | 必填 | 生成 `code_challenge` 的原始 verifier |

公共客户端请求示例：

```bash
curl -X POST "https://kinoko.zorua.cn/api/oauth/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "grant_type=authorization_code" \
  --data-urlencode "client_id=oc_example" \
  --data-urlencode "code=ac_example_authorization_code" \
  --data-urlencode "redirect_uri=https://app.example.com/oauth/callback" \
  --data-urlencode "code_verifier=6hbZc9J5mL7uX2QpR8sT4wY1aD0fG3kN5vB7eH9jK2mP4qS6xC8zA1dF"
```

机密客户端在同一表单中增加：

```text
client_secret=ocs_example_client_secret
```

响应字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `access_token` | string | `oa_` 开头的资源访问凭证 |
| `token_type` | string | 固定为 `Bearer` |
| `expires_in` | integer | Access token 剩余有效秒数，默认 `900` |
| `refresh_token` | string | `or_` 开头的刷新凭证 |
| `refresh_token_expires_in` | integer | Refresh token 剩余有效秒数，默认 `2592000` |
| `scope` | string | 实际签发的空格分隔 scope |

成功响应示例：

```json
{
  "access_token": "oa_example_access_token",
  "token_type": "Bearer",
  "expires_in": 900,
  "refresh_token": "or_example_refresh_token",
  "refresh_token_expires_in": 2592000,
  "scope": "read_user_profile read_player"
}
```

成功和错误响应都包含 `Cache-Control: no-store` 与 `Pragma: no-cache`。

## 7. 刷新 Token

### `POST /api/oauth/token`

使用当前 refresh token 换取新的 access token 和 refresh token。

表单字段：

| 字段 | 类型 | 公共客户端 | 机密客户端 | 规则 |
| --- | --- | --- | --- | --- |
| `grant_type` | string | 必填 | 必填 | 固定为 `refresh_token` |
| `client_id` | string | 必填 | 必填 | 签发 refresh token 的客户端 |
| `client_secret` | string | 禁止 | 必填 | 机密客户端当前 secret |
| `refresh_token` | string | 必填 | 必填 | 当前有效的 `or_` token |
| `scope` | string | 可选 | 可选 | 省略时保持原 scope；传入时只能保持或缩小 |

请求示例：

```bash
curl -X POST "https://kinoko.zorua.cn/api/oauth/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "grant_type=refresh_token" \
  --data-urlencode "client_id=oc_example" \
  --data-urlencode "refresh_token=or_example_refresh_token" \
  --data-urlencode "scope=read_player"
```

响应字段与授权码交换相同。客户端必须先持久化新 refresh token，再废弃旧值。旧 refresh token 再次使用会被判定为重放，并撤销同一 `client_id` 下的整个 token family。

刷新成功示例：

```json
{
  "access_token": "oa_new_access_token",
  "token_type": "Bearer",
  "expires_in": 900,
  "refresh_token": "or_new_refresh_token",
  "refresh_token_expires_in": 2592000,
  "scope": "read_player"
}
```

## 8. 撤销 Token

### `POST /api/oauth/revoke`

撤销 access token 时只撤销该 token。撤销 refresh token 时撤销其整个 family。格式正确但服务端不存在的 token 也返回 `200`。

表单字段：

| 字段 | 类型 | 公共客户端 | 机密客户端 | 规则 |
| --- | --- | --- | --- | --- |
| `client_id` | string | 必填 | 必填 | Token 所属客户端 |
| `client_secret` | string | 禁止 | 必填 | 机密客户端当前 secret |
| `token` | string | 必填 | 必填 | `oa_` 或 `or_` token |
| `token_type_hint` | string | 可选 | 可选 | `access_token` 或 `refresh_token` |

请求示例：

```bash
curl -X POST "https://kinoko.zorua.cn/api/oauth/revoke" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "client_id=oc_example" \
  --data-urlencode "token=or_example_refresh_token" \
  --data-urlencode "token_type_hint=refresh_token"
```

成功响应状态为 `200 OK`，响应体为空。OAuth 服务总开关关闭时仍可调用该端点撤销 Token。

## 9. Scope

| Scope | 允许的操作 | 资源端点 |
| --- | --- | --- |
| `read_user_profile` | 读取站内用户资料和有效绑定 | `/api/v1/user/profile`、`/api/v1/user/hiroba-binds` |
| `read_player` | 读取成绩、单曲历史和成绩汇总 | `/api/v1/scores/*`、`/api/v1/players/*/history`、`/score-summaries` |
| `write_player` | 触发同步、读取同步状态、向日服或虚拟账号导入成绩 | `/api/v1/players/*/sync`、`/sync-status`、`/scores/import` |

请求的 scope 必须是应用登记 scope 的子集。需要新增权限时，开发者先修改应用配置，再让用户重新授权。

## 10. 协议错误

Token 和 Revoke 端点使用扁平 OAuth 错误：

```json
{
  "error": "invalid_grant",
  "error_description": "authorization grant is invalid, expired, or already used"
}
```

| HTTP | 错误码 | 常见原因 | 处理方式 |
| --- | --- | --- | --- |
| `400` | `invalid_request` | 缺少字段、重复字段、错误 Content-Type 或混入当前 grant 不允许的字段 | 修正请求，不原样重试 |
| `401` | `invalid_client` | 客户端类型、`client_id` 或 secret 错误 | 检查凭证；不要重复提交同一错误 secret |
| `400` | `invalid_grant` | 授权码或 refresh token 无效、过期、已使用或状态已变化 | 重新授权 |
| `400` | `invalid_scope` | scope 未登记、格式错误或刷新时扩大权限 | 请求已登记且已授权的子集 |
| `400` | `unsupported_grant_type` | grant 不受支持 | 使用 `authorization_code` 或 `refresh_token` |
| `429` | `temporarily_unavailable` | IP 或 `client_id` 达到频率限制 | 按 `Retry-After` 退避 |
| `500` | `server_error` | 服务端内部错误 | 稍后重试，不记录完整请求表单 |
| `503` | `temporarily_unavailable` | OAuth 服务暂不可用 | 稍后重试；已有 Token 可调用 Revoke |

授权页还可能通过可信回调返回 `access_denied`、`unsupported_response_type`、`invalid_scope`、`invalid_request` 或 `temporarily_unavailable`。客户端必须校验回调 `state`，并只处理自己发起的授权请求。

## 11. 安全要求

- 不记录授权码、`code_verifier`、client secret、access token 或 refresh token。
- 不把 Token 放入 URL 查询字段、浏览器历史、分析事件或错误上报。
- Refresh token 只发送到 Token 或 Revoke 端点，不发送到资源 API。
- 对 `invalid_grant` 不自动循环刷新；清除本地 Token 后重新授权。
- 对 `429` 使用有上限的退避，并遵循 `Retry-After`。
