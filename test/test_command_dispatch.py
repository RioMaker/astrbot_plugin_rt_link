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
        self.unbind_calls = []
        self.profile_calls = []
        self.improve_calls = []
        self.sync_reminder = ""

    async def generate_report_image(self, qq):
        return True, f"report-{qq}.png"

    async def generate_help_image(self, qq):
        return True, f"help-{qq}.png"

    async def score_sync_reminder_text(self, qq):
        return self.sync_reminder

    async def generate_profile_image(self, qq, *, refresh=False):
        self.profile_calls.append((qq, refresh))
        return True, f"profile-{qq}.png"

    async def generate_configuration_image(self, qq):
        return True, f"progress-{qq}.png"

    async def generate_weakness_image(self, qq):
        return True, f"weakness-{qq}.png"

    async def generate_rank_improve_image(self, qq, target, level):
        self.improve_calls.append((qq, target, level))
        return True, f"improve-{qq}.png"

    async def force_update(self, qq):
        return True, f"更新完成：{qq}"

    async def bind(self, qq, apikey, player_id, server):
        self.bind_calls.append((qq, apikey, player_id, server))
        return True, "绑定成功"

    async def unbind(self, qq):
        self.unbind_calls.append(qq)
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

    async def chart_library_status_text(self):
        return "公共谱面分析库"


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

    plugin.service.sync_reminder = "请先同步新版成绩"
    assert await invoke(plugin, private_help, "help") == [
        "请先同步新版成绩", "help-10001.png"
    ]
    plugin.service.sync_reminder = ""

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
        "请在私聊中发送绑定指令，避免在群聊公开凭据。"
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

    progress = mock.AstrMessageEvent("10008", private=False, is_admin=False, message_str="rtlink progress")
    assert await invoke(plugin, progress, "progress") == ["progress-10008.png"]
    rating = mock.AstrMessageEvent("10008", private=False, is_admin=False, message_str="rtlink rating")
    assert await invoke(plugin, rating, "rating") == ["report-10008.png"]

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
    assert await invoke(plugin, bare) == ["profile-10007.png"]
    assert plugin.service.profile_calls == [("10008", False), ("10007", True)]

    unknown = mock.AstrMessageEvent(
        "10007", private=False, is_admin=False, message_str="rtlink something"
    )
    assert "未知子指令" in (await invoke(plugin, unknown, "something"))[0]


def test_dispatch_replies_for_user_admin_private_and_group():
    asyncio.run(run_dispatch_cases())


def test_dispatch_reads_the_argument_tail_once_and_keeps_song_text():
    plugin = make_plugin()

    async def replies(message, fallback=""):
        event = mock.AstrMessageEvent("qq", private=False, is_admin=False, message_str=message)
        return await invoke(plugin, event, fallback)

    assert asyncio.run(replies("/RTLINK\tＳＣＯＲＥ　Ｆｌｙ  Ａｗａｙ")) == [
        "查分成功：qq:Ｆｌｙ  Ａｗａｙ"
    ]
    assert asyncio.run(replies("/rtlink", "score score Fly Away")) == [
        "查分成功：qq:score Fly Away"
    ]
    assert asyncio.run(replies('/rtlink alias "Fly Away" 日本 版')) == ["别名申请：Fly Away:日本 版"]
    assert asyncio.run(replies("/rtlink alias 「Fly Away」 Ｆｌｙ")) == ["别名申请：Fly Away:Ｆｌｙ"]
    assert asyncio.run(replies("/rtlink alias 夏祭り 新 夏祭")) == ["别名申请：夏祭り:新 夏祭"]
    assert asyncio.run(replies('/rtlink alias "Fly Away 日本 版'))[0].startswith("用法：")
    assert asyncio.run(replies("/rtlink unbind sakura")) == ["用法：/rtlink unbind"]
    assert plugin.service.unbind_calls == []


def test_improve_accepts_known_aliases_and_stops_on_invalid_parameters():
    plugin = make_plugin()

    async def replies(args):
        event = mock.AstrMessageEvent("qq", private=False, is_admin=False, message_str=f"/rtlink {args}")
        return await invoke(plugin, event)

    for args in ("improve", "improve ４", "提升 ５　５", "紫雅 鬼", "improve 鬼 kiwami"):
        assert asyncio.run(replies(args)) == ["improve-qq.png"]
    assert plugin.service.improve_calls == [
        ("qq", None, None), ("qq", 4, None), ("qq", 5, 5), ("qq", 7, 4), ("qq", 8, 4),
    ]
    plugin.service.improve_calls.clear()
    for args in ("improve 紫雅 拼错", "improve 金雅 紫雅", "improve 金雅 松", "紫雅 鬼 鬼"):
        assert asyncio.run(replies(args))[0].startswith("用法：/rtlink improve")
    assert asyncio.run(replies("拼错 紫雅"))[0].startswith("未知子指令")
    assert plugin.service.improve_calls == []


def test_library_is_public_and_only_admin_can_retry():
    plugin = make_plugin()
    retries = []

    class Installer:
        def start(self, *, force):
            retries.append(force)

    plugin.chart_installer = Installer()

    async def replies(text, admin=False):
        event = mock.AstrMessageEvent("qq", private=True, is_admin=admin, message_str=text)
        return await invoke(plugin, event)

    assert asyncio.run(replies("/rtlink library")) == ["公共谱面分析库"]
    assert asyncio.run(replies("/rtlink library retry"))[0].startswith("无权限")
    assert retries == []
    assert asyncio.run(replies("/rtlink library ＲＥＴＲＹ", admin=True)) == ["公共谱面分析库"]
    assert retries == [True]


def test_only_root_command_is_registered():
    source = (Path(__file__).parents[1] / "main.py").read_text(encoding="utf-8")
    assert source.count("@filter.command(") == 1
    assert "@filter.command(COMMAND_NAME)" in source
