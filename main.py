# -*- coding: utf-8 -*-
"""
rt_link 插件：将 QQ 号绑定到「菌菌控制台」apikey，查询太鼓达人指定曲目成绩。

- 持久化：使用 AstrBot 的 PluginKVStore（put_kv_data / get_kv_data）
- 成绩查询：菌菌公开 API（api_client.py + service.py）
- 交互：命令（/rt_link ...）+ LLM 工具（query_taiko_score，模型可自动调用）
"""

import re

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

from api_client import KinokoClient
from service import BindingsStore, ScoreService

PLUGIN_NAME = "rt_link"
PLUGIN_AUTHOR = "Rio"
PLUGIN_DESC = "将 QQ 绑定到菌菌控制台 apikey，查询太鼓达人指定曲目成绩"
PLUGIN_VERSION = "v0.2.0"

BINDINGS_KEY = "bindings"


class KvBindingsStore(BindingsStore):
    """基于 AstrBot PluginKVStore 的绑定存储。"""

    def __init__(self, star: "RTLinkPlugin"):
        self._star = star

    async def load(self) -> dict:
        data = await self._star.get_kv_data(BINDINGS_KEY, {})
        return data if isinstance(data, dict) else {}

    async def save(self, data: dict) -> None:
        await self._star.put_kv_data(BINDINGS_KEY, data)


@register(PLUGIN_NAME, PLUGIN_AUTHOR, PLUGIN_DESC, PLUGIN_VERSION)
class RTLinkPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.cfg = self.context.get_config() or {}
        self.service = ScoreService(
            store=KvBindingsStore(self),
            client_factory=self._make_client,
            default_server=self.cfg.get("default_server") or "cn",
        )

    def _make_client(self, apikey: str) -> KinokoClient:
        return KinokoClient(
            apikey,
            base_url=self.cfg.get("base_url") or None,
            timeout=int(self.cfg.get("request_timeout", 30) or 30),
        )

    # ------------------------------------------------------------------
    # 命令组：/rt_link <子命令>
    # ------------------------------------------------------------------
    @filter.command_group(PLUGIN_NAME)
    def rt_link(self):
        """rt_link 命令组入口。"""

    @rt_link.command("help")
    async def help(self, event: AstrMessageEvent):
        yield event.plain_result(
            "rt_link 命令：\n"
            "/rt_link bind <apikey> <player_id> [server]  绑定当前 QQ\n"
            "/rt_link unbind                             解绑当前 QQ\n"
            "/rt_link score <曲名>                       查询指定曲目成绩\n"
            "/rt_link list                               查看全部绑定（管理员）\n"
            "/rt_link about                              查看插件信息\n"
            "也可以直接用自然语言问我，例如「我的《夏祭り》成绩是多少」\n"
            "注意：apikey 仅用于服务端绑定与查询，不会发送给大模型；请在私聊中绑定。"
        )

    @rt_link.command("bind")
    async def bind(
        self, event: AstrMessageEvent, apikey: str, player_id: str, server: str = ""
    ):
        # 安全：apikey 属敏感凭据，仅允许在私聊中绑定，避免泄露到群聊。
        if not event.is_private_chat():
            yield event.plain_result("请在私聊中发送绑定命令，避免 apikey 泄露到群聊。")
            return
        ok, msg = await self.service.bind(
            event.get_sender_id(), apikey, player_id, server
        )
        yield event.plain_result(msg)

    @rt_link.command("unbind")
    async def unbind(self, event: AstrMessageEvent):
        ok, msg = await self.service.unbind(event.get_sender_id())
        yield event.plain_result(msg)

    @rt_link.command("list")
    async def list_bindings(self, event: AstrMessageEvent):
        if not event.is_admin():
            yield event.plain_result("无权限：仅管理员可查看全部绑定。")
            return
        yield event.plain_result(await self.service.list_bindings())

    @rt_link.command("score")
    async def score(self, event: AstrMessageEvent):
        song_name = self._parse_score_query(event.get_message_str())
        if not song_name:
            yield event.plain_result("用法：/rt_link score <曲名>")
            return
        yield event.plain_result(
            await self.service.query_score_text(event.get_sender_id(), song_name)
        )

    @rt_link.command("about")
    async def about(self, event: AstrMessageEvent):
        yield event.plain_result(f"{PLUGIN_NAME} v{PLUGIN_VERSION}\n{PLUGIN_DESC}")

    @staticmethod
    def _parse_score_query(msg: str) -> str:
        m = re.search(r"score\s+(.+)$", msg or "", re.IGNORECASE)
        return m.group(1).strip() if m else ""

    # ------------------------------------------------------------------
    # LLM 工具：允许模型在对话中直接调用
    # 安全约定：此工具只返回「成绩文本」，绝不返回 apikey；apikey 仅在服务端 KV 中读取。
    # ------------------------------------------------------------------
    @filter.llm_tool(name="query_taiko_score")
    async def query_taiko_score(self, event: AstrMessageEvent, song_name: str) -> str:
        """查询当前 QQ 用户绑定的太鼓达人账号中，指定歌曲的成绩。

        Args:
            song_name(string): 歌曲名称，支持中文/日文/英文的模糊匹配
        """
        return await self.service.query_score_text(event.get_sender_id(), song_name)
