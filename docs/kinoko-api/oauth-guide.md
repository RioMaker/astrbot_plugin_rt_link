# OAuth 接入指南

菌菌控制台使用 Authorization Code + PKCE。公共客户端和机密客户端都必须使用 `S256`。

## 1. 创建应用

在[开发者中心](/developer)登记客户端类型、回调地址和 scope。

- `public`：SPA、桌面、移动应用或 CLI，不签发 secret。
- `confidential`：有可信服务端的应用，使用 `client_secret_post`。

生产回调使用 HTTPS。本地开发可以使用 `http://localhost` 或 `http://127.0.0.1`。回调地址必须与登记值逐字符相同。

## 2. 生成 state 和 PKCE

每次授权都生成新的 `state` 和 `code_verifier`。下面的浏览器示例生成无 padding 的 Base64url 值：

```js
const randomBase64Url = (bytes) => {
  const value = crypto.getRandomValues(new Uint8Array(bytes))
  return btoa(String.fromCharCode(...value))
    .replaceAll('+', '-').replaceAll('/', '_').replaceAll('=', '')
}

const state = randomBase64Url(32)
const verifier = randomBase64Url(64)
const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))
const challenge = btoa(String.fromCharCode(...new Uint8Array(digest)))
  .replaceAll('+', '-').replaceAll('/', '_').replaceAll('=', '')
```

把 `state` 和 `verifier` 保存在当前授权会话中。不要把 verifier 放入授权 URL、state、日志或分析事件。

## 3. 发起授权

在系统浏览器打开授权页：

```js
const query = new URLSearchParams({
  response_type: 'code',
  client_id: CLIENT_ID,
  redirect_uri: CALLBACK_URL,
  scope: 'read_user_profile read_player',
  state,
  code_challenge: challenge,
  code_challenge_method: 'S256',
})

location.assign(`https://kinoko.zorua.cn/oauth/authorize?${query}`)
```

授权页会要求用户明确同意或拒绝。参数规则见 [OAuth 协议 API](/docs/api/oauth#授权页)。

## 4. 校验回调

用户同意后，回调地址会收到 `code` 和原始 `state`：

```text
https://client.example.com/oauth/callback?code=ONE_TIME_CODE&state=RANDOM_STATE
```

先以常量时间比较回调 state 与会话中的 state。校验通过后立即删除 state，并使用同一会话保存的 verifier 交换 Token。

用户拒绝时，回调会收到 `error=access_denied`。当客户端或回调地址不可信时，授权页会留在站内错误页。

## 5. 交换 Token

Token 请求必须使用 `application/x-www-form-urlencoded`。公共客户端示例：

```bash
curl -X POST "https://kinoko.zorua.cn/api/oauth/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "grant_type=authorization_code" \
  --data-urlencode "client_id=PUBLIC_CLIENT_ID" \
  --data-urlencode "code=ONE_TIME_CODE" \
  --data-urlencode "redirect_uri=https://client.example.com/oauth/callback" \
  --data-urlencode "code_verifier=SESSION_VERIFIER"
```

机密客户端在服务端额外提交 `client_secret`。授权码有效 5 分钟且只能使用一次。

## 6. 调用资源 API

使用返回的 access token：

```bash
curl "https://kinoko.zorua.cn/api/v1/user/profile" \
  -H "Authorization: Bearer oa_your_access_token"
```

Access token 默认有效 15 分钟。资源端点、字段和示例见 [API 接入指南](/docs/api-guide)。

## 7. 刷新和撤销

Access token 到期前，使用当前 refresh token 调用 Token 端点。成功响应会返回新的 access token 和 refresh token；保存新 refresh token 后立即废弃旧值。

重复使用旧 refresh token 会被视为重放，并撤销同一 token family。需要退出登录或解除绑定时，调用 Revoke 端点撤销 refresh token。用户也可以在“账号信息 → 第三方访问”撤销应用授权。

请求字段和错误处理见 [OAuth 协议 API](/docs/api/oauth#刷新-token)。
