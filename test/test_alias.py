# -*- coding: utf-8 -*-
"""临时验证：难度别名解析 + 组合名 + 别名两步审批流程（不依赖真实 API）。"""
import asyncio
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

from service import parse_difficulty, parse_song_query, ScoreService, MemoryBindingsStore  # noqa: E402
from storage import ScoreDatabase  # noqa: E402

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tmp", "alias_test.db")


def test_pure():
    cases = [
        ("鬼", 4), ("魔王", 4), ("oni", 4), ("4", 4),
        ("里", 5), ("里鬼", 5), ("里魔王", 5), ("5", 5),
        ("松", 3), ("困难", 3), ("3", 3),
        ("竹", 2), ("一般", 2), ("2", 2),
        ("梅", 1), ("简单", 1), ("1", 1),
        ("0", None), ("", None), (None, None), ("全部", None),
    ]
    for text, expect in cases:
        got = parse_difficulty(text)
        assert got == expect, f"parse_difficulty({text!r}) = {got}, expect {expect}"
    assert parse_song_query("鬼夏祭") == (4, "夏祭")
    assert parse_song_query("里夏祭") == (5, "夏祭")
    assert parse_song_query("夏祭") == (None, "夏祭")
    assert parse_song_query("魔王Song") == (4, "Song")
    assert parse_song_query("") == (None, "")
    print("[OK] 难度解析 + 组合名解析")


async def test_alias_flow():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    db = ScoreDatabase(DB_PATH)

    rid = db.add_alias_request(303, "夏祭", "Natsumatsuri", "夏祭り", "123456789")
    assert rid is not None
    # 大小写不敏感重复
    assert db.add_alias_request(999, "夏祭", "x", None, "x") is None
    assert len(db.list_pending_aliases()) == 1
    assert db.approve_aliases([rid]) == [rid]
    assert db.get_approved_aliases().get("夏祭") == 303
    print("[OK] storage 别名审批")

    charts = {
        (303, 4): {"title": "Natsumatsuri", "titleJa": "夏祭り", "genre": "J-POP"},
        (1027, 4): {"title": "Natsumatsuri / Jitterin' Jinn", "titleJa": "夏祭り / ジッタリン・ジン", "genre": "J-POP"},
    }
    store = MemoryBindingsStore({"123456789": {"apikey": "tk_x", "player_id": "30053354", "server": "cn"}})
    svc = ScoreService(store=store, client_factory=lambda k: None, charts=charts, score_db=db)

    # 精准 ID 解析
    song, hint = svc._resolve_song("303")
    assert song and song["id"] == 303 and hint is None
    # 名称唯一匹配
    song, hint = svc._resolve_song("Jitterin")
    assert song and song["id"] == 1027 and hint is None
    # 名称歧义
    song, hint = svc._resolve_song("夏祭り")
    assert song is None and hint and "多首" in hint
    # 名称不存在
    song, hint = svc._resolve_song("不存在的歌")
    assert song is None and hint and "未找到" in hint
    print("[OK] _resolve_song 解析")

    # 别名请求（未绑定会拒绝）
    msg = await svc.request_alias("123456789", "Natsumatsuri / Jitterin' Jinn", "夏祭2")
    assert "已收到" in msg, msg
    pending = await svc.list_pending_aliases_text()
    assert "待审批" in pending
    # 通过
    ids = [a["id"] for a in db.list_pending_aliases()]
    msg = await svc.approve_aliases_text(" ".join(str(i) for i in ids))
    assert "已通过" in msg, msg
    print("[OK] service 别名请求/审批")

    # 别名解析 + 组合名（用假 records 直接验证 _resolve_query_to_records）
    records = [
        {"id": 303, "level": 4, "title": "Natsumatsuri", "titleJa": "夏祭り", "rating": 5.0, "accuracy": 0.99, "constant": 7.8, "bestScoreRank": 8, "highScore": 1000000, "fullComboCount": 1, "dondafulComboCount": 0},
        {"id": 1027, "level": 5, "title": "Natsumatsuri / Jitterin' Jinn", "titleJa": "夏祭り / ジッタリン・ジン", "rating": 8.0, "accuracy": 0.95, "constant": 10.0, "bestScoreRank": 6, "highScore": 950000, "fullComboCount": 0, "dondafulComboCount": 0},
    ]
    matched = await svc._resolve_query_to_records(records, "夏祭2")
    assert len(matched) == 1 and matched[0]["id"] == 1027, matched
    matched = await svc._resolve_query_to_records(records, "Jitterin")
    assert len(matched) == 1 and matched[0]["id"] == 1027
    print("[OK] 别名查询解析")


async def main():
    test_pure()
    await test_alias_flow()
    print("ALL OK")


if __name__ == "__main__":
    asyncio.run(main())
