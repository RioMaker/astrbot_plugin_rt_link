# -*- coding: utf-8 -*-
"""rt_link 菌菌 API 连通性测试。

用法：
    python test_api.py          # 读取 apikey.key，调用 /scores/hiroba/recent
    python test_api.py kinoko   # 改用 kinoko 风格
"""

import json
import sys

from api_client import KinokoAPIError, KinokoClient


def load_apikey(path: str = "apikey.key") -> str:
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def summarize(style: str, data: dict) -> str:
    played = data["data"]["playedRecords"]
    uid = played.get("userid") or played.get("player_id")
    server = played.get("server")
    records = played.get("scoreInfo", [])
    lines = [
        f"style={style} userid={uid} server={server} records={len(records)}"
    ]
    if records:
        r = records[0]
        sd = r.get("song_detail") or {}
        name = sd.get("song_name") or r.get("title") or f"song_no={r.get('song_no')}"
        lines.append(
            "  example: song=%s level=%s high_score=%s rank=%s "
            "good=%s ok=%s ng=%s fc=%s dondaful=%s"
            % (
                name, r.get("level"), r.get("high_score"), r.get("best_score_rank"),
                r.get("good_cnt"), r.get("ok_cnt"), r.get("ng_cnt"),
                r.get("full_combo_cnt"), r.get("dondaful_combo_cnt"),
            )
        )
    return "\n".join(lines)


def main() -> int:
    style = sys.argv[1] if len(sys.argv) > 1 else "hiroba"
    client = KinokoClient(load_apikey())

    try:
        data = client.scores(style=style, recent=True)
    except KinokoAPIError as e:
        print(f"[FAIL] {e}")
        return 1

    print("[OK] " + summarize(style, data))

    # 把完整响应落盘，便于人工核对（UTF-8）
    with open("_api_dump.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("[OK] full dump -> _api_dump.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
