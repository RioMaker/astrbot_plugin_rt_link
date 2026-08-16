# -*- coding: utf-8 -*-
"""极简 AstrBot mock：把假模块注入 sys.modules，使 `import main` 可在无 AstrBot 环境下运行。

仅覆盖 main.py 用到的接口：register / filter.command_group / filter.llm_tool、
Star 基类（含 KV 存储）、Context、AstrMessageEvent、logger。
"""

import sys
import types
import os


class AstrMessageEvent:
    """模拟消息事件。"""

    def __init__(self, sender_id: str, private: bool, is_admin: bool, message_str: str):
        self._sender_id = sender_id
        self._private = private
        self._is_admin = is_admin
        self._message_str = message_str

    def get_sender_id(self) -> str:
        return self._sender_id

    def is_private_chat(self) -> bool:
        return self._private

    def is_admin(self) -> bool:
        return self._is_admin

    def get_message_str(self) -> str:
        return self._message_str

    def plain_result(self, text: str):
        return text


class Context:
    def __init__(self, config: dict | None = None):
        self._config = config or {}

    def get_config(self) -> dict:
        return self._config


class StarTools:
    """模拟 StarTools.get_data_dir，返回项目下 test/tmp/data/<name>。"""

    @staticmethod
    def get_data_dir(name: str) -> str:
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "test", "tmp", "data")
        os.makedirs(base, exist_ok=True)
        target = os.path.join(base, name)
        os.makedirs(target, exist_ok=True)
        return target


class Star:
    def __init__(self, context: Context, config: dict | None = None):
        self.context = context
        self._kv = {}

    async def get_kv_data(self, key, default=None):
        return self._kv.get(key, default)

    async def put_kv_data(self, key, value):
        self._kv[key] = value

    async def delete_kv_data(self, key):
        self._kv.pop(key, None)


class _Group:
    """模拟 @filter.command_group 返回的 RegisteringCommandable。"""

    def __init__(self, name: str):
        self.name = name
        self.commands: dict = {}

    def command(self, sub: str):
        def deco(fn):
            self.commands[sub] = fn
            return fn

        return deco


class _Filter:
    def command_group(self, name: str):
        def deco(fn):
            return _Group(name)

        return deco

    def command(self, name: str):
        def deco(fn):
            return fn

        return deco

    def llm_tool(self, name: str | None = None):
        def deco(fn):
            fn._llm_tool_name = name or fn.__name__
            return fn

        return deco


filter = _Filter()


def register(*args, **kwargs):
    def deco(cls):
        return cls

    return deco


logger = types.SimpleNamespace(
    info=lambda *a, **k: None,
    warning=lambda *a, **k: None,
    debug=lambda *a, **k: None,
    error=lambda *a, **k: None,
)


def install() -> None:
    m_astrbot = types.ModuleType("astrbot")
    m_api = types.ModuleType("astrbot.api")
    m_event = types.ModuleType("astrbot.api.event")
    m_star = types.ModuleType("astrbot.api.star")

    m_api.logger = logger
    m_event.filter = filter
    m_event.AstrMessageEvent = AstrMessageEvent
    m_star.Context = Context
    m_star.Star = Star
    m_star.StarTools = StarTools
    m_star.register = register

    sys.modules["astrbot"] = m_astrbot
    sys.modules["astrbot.api"] = m_api
    sys.modules["astrbot.api.event"] = m_event
    sys.modules["astrbot.api.star"] = m_star
