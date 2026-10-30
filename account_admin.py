"""Credential-free account projections and authenticated Dashboard management."""

import asyncio
import json
import math
import re
from functools import wraps

if __package__:
    from .account_identity import BOT_NAME, BOT_OWNER_ID
    from .service import RATING_ALGORITHM_VERSION, RATING_CACHE_SCHEMA
    from .source_service import SOURCE_NAMES
else:
    from account_identity import BOT_NAME, BOT_OWNER_ID
    from service import RATING_ALGORITHM_VERSION, RATING_CACHE_SCHEMA
    from source_service import SOURCE_NAMES


class AdminError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class AccountAdmin:
    def __init__(self, router):
        self.router = router

    async def identities(self):
        async with self.router._bindings_lock:
            bindings = {
                source: dict(await service.store.load())
                for source, service in self.router.services.items()
            }
            known = (
                dict(await self.router.known_store.load())
                if self.router.known_store is not None
                else {}
            )
        history = {}
        for source, service in self.router.services.items():
            history[source] = set(
                await asyncio.to_thread(service.db.list_known_owners)
                if service.db is not None
                else []
            )
        owners = set(known)
        for source, values in bindings.items():
            owners.update(values)
            owners.update(history[source])
        return bindings, known, history, owners

    async def account(self, owner, identities=None):
        identities = identities or await self.identities()
        _, known, history, owners = identities
        if owner != BOT_OWNER_ID and owner not in owners:
            raise AdminError("用户不存在。", 404)
        async with self.router._users[owner]:
            selected = await self.router.current_source(owner)
            sources = []
            for source, service in self.router.services.items():
                binding = await service._binding(owner)
                saved = known.get(owner, {}).get(source) or {}
                identity = binding or saved
                latest, cache = None, None
                if service.db is not None:
                    latest = await asyncio.to_thread(
                        service.db.get_latest_score_sync,
                        owner,
                        identity.get("player_id") if identity else None,
                        identity.get("server") if identity else None,
                    )
                    if binding:
                        cache = await asyncio.to_thread(
                            service.db.get_rating_cache, owner
                        )
                if not identity and latest:
                    identity = {
                        "player_id": latest.get("game_player_id"),
                        "server": latest.get("server"),
                    }
                meta = (cache or {}).get("meta") or {}
                matches = bool(binding and cache) and (
                    str(meta.get("playerId") or "")
                    == str(binding.get("player_id") or "")
                    and str(meta.get("server") or "")
                    == str(binding.get("server") or service.default_server)
                )
                current = matches and (
                    cache.get("ratingAlgorithmVersion") == RATING_ALGORITHM_VERSION
                    and cache.get("_cacheSchema") == RATING_CACHE_SCHEMA
                )
                rating = (cache.get("summary") or {}).get("rating") if current else None
                if (
                    isinstance(rating, bool)
                    or not isinstance(rating, (float, int))
                    or not math.isfinite(rating)
                ):
                    rating = None
                synced_at = latest.get("fetched_at") if latest else None
                rating_at = cache.get("profileSyncedAt") if matches else None
                sources.append(
                    {
                        "source": source,
                        "label": SOURCE_NAMES[source],
                        "bound": bool(binding),
                        "ever_bound": bool(
                            binding or saved or owner in history[source]
                        ),
                        "player_id": str(identity.get("player_id") or ""),
                        "server": str(identity.get("server") or ""),
                        "last_sync_at": synced_at or rating_at,
                        "rating_at": rating_at if rating is not None else None,
                        "rating": round(rating, 2) if rating is not None else None,
                        "rating_state": "unbound"
                        if not binding
                        else ("available" if rating is not None else "needs_sync"),
                        "score_count": latest.get("current_count") if latest else None,
                    }
                )
            active = next(row for row in sources if row["source"] == selected)
            dates = [row["last_sync_at"] for row in sources if row["last_sync_at"]]
            return {
                "owner_id": owner,
                "name": BOT_NAME if owner == BOT_OWNER_ID else owner,
                "is_bot": owner == BOT_OWNER_ID,
                "current_source": selected,
                "bound_sources": [row["source"] for row in sources if row["bound"]],
                "last_sync_at": max(dates, default=None),
                "rating": active["rating"],
                "rating_at": active["rating_at"],
                "rating_state": active["rating_state"],
                "sources": sources,
            }

    async def users(self, query):
        search = str(query.get("q", "")).strip().lower()
        source, status = query.get("source", ""), query.get("status", "all")
        try:
            page, size = int(query.get("page", 1)), int(query.get("page_size", 20))
        except (TypeError, ValueError) as error:
            raise AdminError("分页参数必须为整数。") from error
        if not 1 <= page <= 100000 or not 1 <= size <= 100 or len(search) > 100:
            raise AdminError("分页或搜索范围无效。")
        if source not in ("", *self.router.services) or status not in {
            "all",
            "bound",
            "unbound",
        }:
            raise AdminError("筛选条件无效。")
        identities = await self.identities()
        bindings, known, _, owners = identities
        owners.discard(BOT_OWNER_ID)
        active = {
            owner
            for owner in owners
            if any(owner in values for values in bindings.values())
        }
        filtered = []
        for owner in sorted(owners):
            if source and owner not in bindings[source]:
                continue
            if (status == "bound" and owner not in active) or (
                status == "unbound" and owner in active
            ):
                continue
            public_ids = [owner]
            for key, values in bindings.items():
                identity = values.get(owner) or known.get(owner, {}).get(key) or {}
                public_ids.append(str(identity.get("player_id") or ""))
            if search and not any(search in value.lower() for value in public_ids):
                continue
            filtered.append(owner)
        page = min(page, max(1, math.ceil(len(filtered) / size)))
        rows = [
            await self.account(owner, identities)
            for owner in filtered[(page - 1) * size : page * size]
        ]
        return {
            "items": rows,
            "total": len(filtered),
            "page": page,
            "page_size": size,
            "stats": {
                "total": len(owners),
                "bound": len(active),
                "unbound": len(owners - active),
            },
        }

    async def perform(self, data):
        owner, source, action = (
            data.get("owner_id"),
            data.get("source"),
            data.get("action"),
        )
        if not isinstance(owner, str) or not 1 <= len(owner) <= 200:
            raise AdminError("用户 ID 无效。")
        if not isinstance(source, str) or source not in self.router.services:
            raise AdminError("来源仅支持 kinoko 或 sakura。")
        if not isinstance(action, str) or action not in {
            "bind",
            "select",
            "sync",
            "unbind",
        }:
            raise AdminError("操作无效。")
        await self.account(owner)  # Only the bot or a known user can be managed.
        if action == "bind":
            token = data.get("token")
            if not isinstance(token, str) or not 1 <= len(token.strip()) <= 512:
                raise AdminError("请输入有效 Token。")
            token = token.strip()
            if source == "sakura":
                if not re.fullmatch(r"[A-Za-z0-9]{48}", token):
                    raise AdminError("Sakura Token 应为 48 位字母或数字。")
                ok, _ = await self.router.bind_sakura(owner, token)
            else:
                player, server = data.get("player_id"), data.get("server", "cn")
                if not token.startswith("tk_"):
                    raise AdminError("菌菌 API Key 应以 tk_ 开头。")
                if not isinstance(player, str) or not re.fullmatch(
                    r"[A-Za-z0-9_-]{1,64}", player
                ):
                    raise AdminError("请输入有效的菌菌玩家 ID。")
                if not isinstance(server, str) or server not in {"cn", "jp", "custom"}:
                    raise AdminError("菌菌服务器仅支持 cn、jp、custom。")
                ok, _ = await self.router.bind(owner, token, player, server)
            if not ok:
                # Provider failures can contain request URLs/credentials; never echo them.
                raise AdminError(
                    "绑定验证失败，请检查 Token、玩家信息及来源服务状态；原绑定未变更。",
                    422,
                )
            message = (
                "绑定已保存并设为当前来源。点击「同步成绩」获取最新成绩与 Rating。"
            )
        else:
            ok, _ = await self.router.manage_source(owner, source, action)
            if not ok:
                raise AdminError(
                    "操作未完成，请检查该来源是否已绑定、凭据是否有效或暂时无可评级成绩。",
                    422,
                )
            message = {
                "sync": "同步完成，成绩与 Rating 已更新。",
                "select": "当前来源已切换。",
                "unbind": "该来源已解绑，历史成绩保留。",
            }[action]
        return {"message": message, "account": await self.account(owner)}


class AdminAPI:
    def __init__(self, plugin, web):
        self.plugin, self.web = plugin, web
        self.accounts = AccountAdmin(plugin.service)
        self.handlers = []
        self.closed = False

    def register(self):
        for endpoint, handler, method in (
            ("users", self.users, "GET"),
            ("account", self.account, "GET"),
            ("action", self.action, "POST"),
        ):
            wrapped = self.guard(handler)
            # Metadata/register name is rt_link, not the repository directory name.
            self.plugin.context.register_web_api(
                f"/rt_link/admin/{endpoint}", wrapped, [method], "RTLink 账号管理"
            )
            self.handlers.append(wrapped)

    def close(self):
        self.closed = True
        routes = getattr(self.plugin.context, "registered_web_apis", None)
        if isinstance(routes, list):
            routes[:] = [route for route in routes if route[1] not in self.handlers]

    def guard(self, handler):
        @wraps(handler)
        async def guarded():
            if self.closed:
                return self.web.error_response(
                    "插件已停用，请刷新页面。", status_code=503
                )
            request = self.web.request
            if not request.username:
                return self.web.error_response(
                    "请先登录 AstrBot 管理面板。", status_code=401
                )
            if request.headers.get("Sec-Fetch-Site", "").lower() == "cross-site":
                return self.web.error_response(
                    "请通过 AstrBot 管理面板访问。", status_code=403
                )
            try:
                data = await handler()
                return self.web.json_response(
                    data, headers={"Cache-Control": "no-store"}
                )
            except AdminError as error:
                return self.web.error_response(str(error), status_code=error.status)
            except Exception:  # noqa: BLE001 -- HTTP boundary must not echo credentials
                from astrbot.api import logger

                logger.error("rt_link 账号管理操作失败：%s", handler.__name__)
                return self.web.error_response(
                    "操作失败，请检查服务状态后重试。", status_code=500
                )

        return guarded

    async def users(self):
        return await self.accounts.users(self.web.request.query)

    async def account(self):
        return await self.accounts.account(
            self.web.request.query.get("owner_id", BOT_OWNER_ID)
        )

    async def action(self):
        request = self.web.request
        if (request.content_type or "").split(";", 1)[0].strip() != "application/json":
            raise AdminError("请使用 JSON 请求。", 415)
        raw = await request.body()
        if len(raw) > 4096:
            raise AdminError("请求内容过大。", 413)
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as error:
            raise AdminError("请求须为有效 JSON。") from error
        if not isinstance(data, dict):
            raise AdminError("请求须为 JSON 对象。")
        return await self.accounts.perform(data)


def register_admin_api(plugin):
    if not callable(getattr(plugin.context, "register_web_api", None)):
        return None
    try:
        from astrbot.api import web
    except ImportError:
        from astrbot.api import logger

        logger.warning(
            "rt_link 账号管理页需要支持 Plugin Pages 和 astrbot.api.web 的新版 AstrBot。"
        )
        return None
    api = AdminAPI(plugin, web)
    api.register()
    return api
