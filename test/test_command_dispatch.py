# -*- coding: utf-8 -*-
"""验证 /rtlink 根指令对不同会话和权限用户都能正确分发。"""

import asyncio
import os
import sys
from pathlib import Path

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

import mock_astrbot as mock  # noqa: E402

mock.install()

import main  # noqa: E402


class FakeService:
    def __init__(self):
        self.bind_calls = []

    async def generate_report_image(self, qq):
        return True, f"report-{qq}.png"

    async def generate_help_image(self, qq):
        return True, f"help-{qq}.png"

    async def generate_profile_image(self, qq):
        return True, f"profile-{qq}.png"

    async def generate_weakness_image(self, qq):
        return True, f"weakness-{qq}.png"

    async def force_update(self, qq):
        return True, f"更新完成：{qq}"

    async def bind(self, qq, apikey, player_id, server):
        self.bind_calls.append((qq, apikey, player_id, server))
        return True, "绑定成功"

    async def unbind(self, qq):
        return True, "已解绑"

    async def list_bindings(self):
        return "当前绑定"

    async def low_space_warning_text(self):
        return ""

    async def query_score_text(self, qq, song_name):
        return f"查分成功：{qq}:{song_name}"

    async def get_profile_text(self, qq):
        return f"画像：{qq}"

    async def get_rhythm_weakness_text(self, qq):
        return f"弱项：{qq}"

    async def storage_status_text(self):
        return "存储状态"

    async def cleanup(self):
        return "清理完成"

    async def request_alias(self, qq, target, alias):
        return f"别名申请：{target}:{alias}"

    async def list_pending_aliases_text(self):
        return "待审批别名"

    async def approve_aliases_text(self, args):
        return f"已审批：{args}"


def make_plugin():
    plugin = object.__new__(main.RTLinkPlugin)
    plugin.service = FakeService()
    return plugin


async def invoke(plugin, event, subcommand=""):
    return [item async for item in plugin.rtlink(event, subcommand)]


async def run_dispatch_cases():
    plugin = make_plugin()

    private_help = mock.AstrMessageEvent(
        "10001", private=True, is_admin=False, message_str="rtlink help"
    )
    assert await invoke(plugin, private_help, "help") == ["help-10001.png"]

    chinese_help = mock.AstrMessageEvent(
        "10001", private=True, is_admin=False, message_str="rtlink 帮助"
    )
    assert await invoke(plugin, chinese_help, "帮助") == ["help-10001.png"]

    group_score = mock.AstrMessageEvent(
        "10002", private=False, is_admin=False, message_str="rtlink score 夏祭り"
    )
    assert await invoke(plugin, group_score, "score") == ["查分成功：10002:夏祭り"]

    group_bind = mock.AstrMessageEvent(
        "10003",
        private=False,
        is_admin=False,
        message_str="rtlink bind tk_test 30053354 cn",
    )
    assert await invoke(plugin, group_bind, "bind") == [
        "请在私聊中发送绑定命令，避免 apikey 泄露到群聊。"
    ]
    assert plugin.service.bind_calls == []

    private_bind = mock.AstrMessageEvent(
        "10004",
        private=True,
        is_admin=False,
        message_str="rtlink bind tk_test 30053354 cn",
    )
    assert await invoke(plugin, private_bind, "bind") == ["绑定成功"]
    assert plugin.service.bind_calls == [("10004", "tk_test", "30053354", "cn")]

    user_storage = mock.AstrMessageEvent(
        "10005", private=True, is_admin=False, message_str="rtlink storage"
    )
    assert await invoke(plugin, user_storage, "storage") == [
        "无权限：仅管理员可查看存储用量。"
    ]

    admin_storage = mock.AstrMessageEvent(
        "10006", private=False, is_admin=True, message_str="rtlink storage"
    )
    assert await invoke(plugin, admin_storage, "storage") == ["存储状态"]

    profile = mock.AstrMessageEvent(
        "10008", private=True, is_admin=False, message_str="rtlink profile"
    )
    assert await invoke(plugin, profile, "profile") == ["profile-10008.png"]

    weakness = mock.AstrMessageEvent(
        "10009", private=False, is_admin=False, message_str="rtlink weakness"
    )
    assert await invoke(plugin, weakness, "weakness") == ["weakness-10009.png"]

    update = mock.AstrMessageEvent(
        "10010", private=True, is_admin=False, message_str="rtlink update"
    )
    assert await invoke(plugin, update, "update") == ["更新完成：10010"]

    bare = mock.AstrMessageEvent(
        "10007", private=False, is_admin=False, message_str="/rtlink"
    )
    assert await invoke(plugin, bare) == ["report-10007.png"]

    unknown = mock.AstrMessageEvent(
        "10007", private=False, is_admin=False, message_str="rtlink something"
    )
    assert "未知子指令" in (await invoke(plugin, unknown, "something"))[0]


def test_dispatch_replies_for_user_admin_private_and_group():
    asyncio.run(run_dispatch_cases())


def test_only_root_command_is_registered():
    source = (Path(__file__).parents[1] / "main.py").read_text(encoding="utf-8")
    assert source.count("@filter.command(") == 1
    assert "@filter.command(COMMAND_NAME)" in source
