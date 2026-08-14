# -*- coding: utf-8 -*-
"""测试 main.py 真实命令层（含私聊绑定校验）。

用 mock AstrBot 加载真实的 main.py，配合 apikey.key 打真实菌菌 API。
输出写入 test/cmd_output.txt（UTF-8），同时打印到控制台。
"""

import asyncio
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

import mock_astrbot as mock  # noqa: E402

mock.install()

import main  # noqa: E402

APIKEY = open(os.path.join(_PROJECT_ROOT, "apikey.key"), encoding="utf-8").read().strip()
PLAYER_ID = "30053354"  # apikey.key 对应账号的玩家 ID（国服）
OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cmd_output.txt")

CONFIG = {
    "base_url": "https://kinoko.zorua.cn/api/v1",
    "default_server": "cn",
    "request_timeout": 30,
}


def make_plugin() -> main.RTLinkPlugin:
    return main.RTLinkPlugin(mock.Context(CONFIG))


async def invoke(fn, plugin, event, *args):
    """运行异步生成器 handler，收集 yield 出的文本。"""
    results = []
    async for item in fn(plugin, event, *args):
        results.append(item)
    return results


async def run() -> list[str]:
    out = []
    plugin = make_plugin()
    group = main.RTLinkPlugin.rt_link  # 命令组 _Group
    bind_fn = group.commands["bind"]
    score_fn = group.commands["score"]
    unbind_fn = group.commands["unbind"]

    qq = "123456789"

    def add(title, text):
        out.append("=" * 60)
        out.append(f"[{title}]")
        out.append(text)

    # 1) 群聊绑定 → 应被拒绝
    grp = mock.AstrMessageEvent(qq, private=False, is_admin=False,
                                message_str=f"/rt_link bind {APIKEY} {PLAYER_ID} cn")
    add("群聊 /rt_link bind", (await invoke(bind_fn, plugin, grp, APIKEY, PLAYER_ID, "cn"))[0])

    # 2) 私聊绑定 → 成功
    priv = mock.AstrMessageEvent(qq, private=True, is_admin=False,
                                 message_str=f"/rt_link bind {APIKEY} {PLAYER_ID} cn")
    add("私聊 /rt_link bind", (await invoke(bind_fn, plugin, priv, APIKEY, PLAYER_ID, "cn"))[0])

    # 3) 私聊查分
    score_evt = mock.AstrMessageEvent(qq, private=True, is_admin=False,
                                      message_str="/rt_link score 夏祭り")
    add("私聊 /rt_link score 夏祭り", (await invoke(score_fn, plugin, score_evt))[0])

    # 4) 私聊解绑
    unbind_evt = mock.AstrMessageEvent(qq, private=True, is_admin=False,
                                       message_str="/rt_link unbind")
    add("私聊 /rt_link unbind", (await invoke(unbind_fn, plugin, unbind_evt))[0])

    return out


def main_entry():
    out = asyncio.run(run())
    text = "\n".join(out) + "\n"
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(text)
    print(text)
    print(f"\n[输出已写入 {OUTPUT_PATH}]")


if __name__ == "__main__":
    main_entry()
