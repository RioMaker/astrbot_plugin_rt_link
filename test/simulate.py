# -*- coding: utf-8 -*-
"""本地模拟 rt_link 插件，验证「发送 → 返回」信息（不依赖 AstrBot）。

用法（在项目根目录执行）：
    python test/simulate.py demo                       # 跑一组完整场景
    python test/simulate.py bind <player_id> [server]  # 用 apikey.key 绑定
    python test/simulate.py score <曲名>               # 查询指定曲目
    python test/simulate.py unbind                     # 解绑
    python test/simulate.py list                       # 查看绑定

绑定状态持久化在 test/bindings.json；完整输出同时写入 test/sim_output.txt。
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

from api_client import KinokoClient  # noqa: E402
from service import JsonFileBindingsStore, ScoreService  # noqa: E402
from storage import ScoreDatabase, load_charts  # noqa: E402

APIKEY_PATH = os.path.join(_PROJECT_ROOT, "apikey.key")
BINDINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bindings.json")
OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sim_output.txt")
CHARTS_PATH = os.path.join(_PROJECT_ROOT, "resource", "charts.v1.json.gz")
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tmp", "sim.db")

FAKE_QQ = "123456789"  # 模拟的 QQ 号
DEMO_PLAYER_ID = "30053354"  # apikey.key 对应账号的玩家 ID（国服）


def load_apikey() -> str:
    with open(APIKEY_PATH, encoding="utf-8") as f:
        return f.read().strip()


def make_service() -> ScoreService:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    charts = load_charts(CHARTS_PATH)
    db = ScoreDatabase(DB_PATH)
    return ScoreService(
        store=JsonFileBindingsStore(BINDINGS_PATH),
        client_factory=lambda apikey: KinokoClient(apikey),
        charts=charts,
        score_db=db,
        default_server="cn",
    )


async def run_demo():
    apikey = load_apikey()
    svc = make_service()
    transcript = []

    def show(label: str, text: str):
        transcript.append("\n" + "=" * 60)
        transcript.append(f"[{label}]")
        transcript.append(text)

    # 1. 未绑定时查询
    show(
        "模拟发送：LLM 工具 query_taiko_score(song_name='夏祭り')",
        await svc.query_score_text(FAKE_QQ, "夏祭り"),
    )

    # 2. 绑定
    ok, msg = await svc.bind(FAKE_QQ, apikey, DEMO_PLAYER_ID, "cn")
    show("模拟发送：/rtlink bind <apikey> 30053354 cn", msg)

    # 3. 查询
    show("模拟发送：/rtlink score 夏祭り", await svc.query_score_text(FAKE_QQ, "夏祭り"))
    show(
        "模拟发送：LLM 工具 query_taiko_score(song_name='Tokyo')",
        await svc.query_score_text(FAKE_QQ, "Tokyo"),
    )
    show("模拟发送：/rtlink rating", await svc.get_rating_text(FAKE_QQ))
    show("模拟发送：/rtlink profile", await svc.get_profile_text(FAKE_QQ))
    show("模拟发送：/rtlink weakness", await svc.get_rhythm_weakness_text(FAKE_QQ))

    # 4. 未命中
    show(
        "模拟发送：/rtlink score 不存在的曲子xyz",
        await svc.query_score_text(FAKE_QQ, "不存在的曲子xyz"),
    )

    # 6. 列表 + 存储用量
    show("模拟发送：/rtlink list（管理员）", await svc.list_bindings())
    show("模拟发送：/rtlink storage", await svc.storage_status_text())

    # 7. 解绑
    ok, msg = await svc.unbind(FAKE_QQ)
    show("模拟发送：/rtlink unbind", msg)

    out = "\n".join(transcript) + "\n"
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(out)
    print(out)
    print(f"\n[输出已写入 {OUTPUT_PATH}]")


async def run_cli(args):
    svc = make_service()
    cmd = args[0]
    if cmd == "bind":
        if len(args) < 2:
            print("用法：python test/simulate.py bind <player_id> [server]")
            return
        player_id = args[1]
        server = args[2] if len(args) > 2 else "cn"
        ok, msg = await svc.bind(FAKE_QQ, load_apikey(), player_id, server)
        print(msg)
    elif cmd == "score":
        if len(args) < 2:
            print("用法：python test/simulate.py score <曲名>")
            return
        print(await svc.query_score_text(FAKE_QQ, " ".join(args[1:])))
    elif cmd == "unbind":
        ok, msg = await svc.unbind(FAKE_QQ)
        print(msg)
    elif cmd == "list":
        print(await svc.list_bindings())
    else:
        print("未知命令。可用：demo / bind / score / unbind / list")


def main():
    args = sys.argv[1:]
    if not args or args[0] == "demo":
        asyncio.run(run_demo())
    else:
        asyncio.run(run_cli(args))


if __name__ == "__main__":
    main()
