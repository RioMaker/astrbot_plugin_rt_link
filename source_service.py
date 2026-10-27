"""按用户选择路由到独立服务，数据库、凭据、缓存、历史及图片目录均不跨源。"""

import asyncio
from collections import defaultdict


SOURCE_NAMES = {"kinoko": "菌菌", "sakura": "Sakura"}


class MultiSourceService:
    # 只有明确声明的玩家操作可以被自动分发，公共谱面/别名走共享服务。
    PLAYER_METHODS = frozenset({
        "request_alias", "score_sync_reminder_text", "force_update", "generate_profile_image",
        "generate_report_image", "generate_configuration_image", "generate_weakness_image",
        "generate_rank_improve_image", "query_score_text", "query_scores_text",
        "get_accuracy_summary_text", "get_difficulty_stats_text", "get_genre_strength_text",
        "get_growth_trend_text", "get_improvement_candidates_text", "get_player_dan_capability_text",
        "get_profile_text", "get_rank_distribution_text", "get_rank_improvement_text",
        "get_rating_text", "get_recent_scores_text", "get_rhythm_weakness_text", "get_song_full_text",
        "get_ai_overview_text", "recommend_practice_text", "get_song_brief_text",
        "get_readonly_queries_text",
    })
    SHARED_METHODS = frozenset({
        "generate_help_image", "list_pending_aliases_text", "approve_aliases_text",
        "chart_library_status_text", "get_chart_analysis_text",
    })

    def __init__(self, services, selection_store):
        self.services = dict(services)
        self.selection_store = selection_store
        self._users = defaultdict(asyncio.Lock)
        self._bindings_lock = asyncio.Lock()

    async def current_source(self, qq):
        selected = (await self.selection_store.load()).get(qq, "kinoko")
        return selected if selected in self.services else "kinoko"

    async def _select(self, qq, source):
        selections = await self.selection_store.load()
        selections[qq] = source
        await self.selection_store.save(selections)

    async def source_text(self, qq, source=""):
        async with self._users[qq]:
            if source:
                source = source.lower()
                if source not in self.services:
                    return "未知数据源。可用：kinoko（菌菌）、sakura（Sakura）。"
                if not await self.services[source]._binding(qq):
                    return f"{SOURCE_NAMES[source]} 尚未绑定，请先在私聊中绑定该数据源。"
                async with self._bindings_lock:
                    await self._select(qq, source)
            selected = await self.current_source(qq)
            lines = [f"当前数据源：{SOURCE_NAMES[selected]}（{selected}）"]
            for key, service in self.services.items():
                binding = await service._binding(qq)
                status = f"玩家 {binding['player_id']} / {binding['server']}" if binding else "未绑定"
                lines.append(f"{key}：{status}")
            lines.append("切换：/rtlink source kinoko 或 /rtlink source sakura；各源成绩与历史独立保存。")
            return "\n".join(lines)

    async def bind(self, qq, apikey, player_id, server=""):
        async with self._users[qq], self._bindings_lock:
            result = await self.services["kinoko"].bind(qq, apikey, player_id, server)
            if result[0]:
                await self._select(qq, "kinoko")
            return result

    async def bind_sakura(self, qq, token):
        async with self._users[qq], self._bindings_lock:
            result = await self.services["sakura"].bind_sakura(qq, token)
            if result[0]:
                await self._select(qq, "sakura")
            return result

    async def unbind(self, qq):
        async with self._users[qq], self._bindings_lock:
            source = await self.current_source(qq)
            ok, text = await self.services[source].unbind(qq)
            return ok, f"[{SOURCE_NAMES[source]}] {text} 该来源的历史保留；其他来源绑定不变。"

    async def _all(self, method):
        sections = []
        for key, service in self.services.items():
            text = await getattr(service, method)()
            if text:
                sections.append(f"[{SOURCE_NAMES[key]}]\n{text}")
        return "\n\n".join(sections)

    async def list_bindings(self):
        return await self._all("list_bindings")

    async def storage_status_text(self):
        return await self._all("storage_status_text")

    async def low_space_warning_text(self):
        return await self._all("low_space_warning_text")

    async def cleanup(self):
        return await self._all("cleanup")

    def __getattr__(self, name):
        if name in self.SHARED_METHODS:
            return getattr(self.services["kinoko"], name)
        if name not in self.PLAYER_METHODS:
            raise AttributeError(name)

        async def routed(qq, *args, **kwargs):
            # 一次操作只使用开始时选定的服务；切换/解绑/同用户同步排队。
            # 等待中的并发查询会复用前一次同步写入的 TTL 缓存。
            async with self._users[qq]:
                source = await self.current_source(qq)
                return await getattr(self.services[source], name)(qq, *args, **kwargs)

        return routed
