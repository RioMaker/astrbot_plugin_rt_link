# -*- coding: utf-8 -*-
"""スコアランク 门槛计算、提升候选分析与渲染器的单元测试。"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

PLUGIN_DIR = Path(__file__).resolve().parent.parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

import score_rank as sr  # noqa: E402

RESOURCE = PLUGIN_DIR / "resource" / "score_rank.v1.json.gz"


# ---------------------------------------------------------------------------
# 解析与门槛
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("金雅", 4), ("4", 4), ("白粹", 2), ("白粋", 2), ("銀粋", 3), ("银粹", 3),
    ("粉雅", 5), ("紫雅", 6), ("极", 7), ("極", 7), ("极+连打满", 8), ("全良", 8),
    ("gInSuI", 3), ("  Kiwami  ", 7), (8, 8), (1, 1),
])
def test_parse_score_rank_accepts_names_and_numbers(text, expected):
    assert sr.parse_score_rank(text) == expected


@pytest.mark.parametrize("text", ["", None, "鬼", "里", "9", "0", "不存在"])
def test_parse_score_rank_rejects_unknown(text):
    assert sr.parse_score_rank(text) is None


def test_song_unit_prefers_wiki_ceiling():
    song = {"ceiling": 996000, "top": 1002000, "rolls": 24}
    ceiling, unit, exact = sr.song_unit(song, 400)
    assert exact is True
    assert ceiling == 996000
    assert unit == 2490          # round(996000 / 400 / 10) * 10


def test_song_unit_falls_back_when_wiki_entry_mismatches_chart():
    # 天井 50 万对 100 音符的谱面不成立（应为 100 万量级），必须退回估算。
    song = {"ceiling": 500000, "top": 500000, "rolls": 0}
    ceiling, unit, exact = sr.song_unit(song, 100)
    assert exact is False
    assert unit == 10000
    assert ceiling == 1_000_000


def test_song_unit_without_song_estimates():
    ceiling, unit, exact = sr.song_unit(None, 500)
    assert exact is False
    assert unit == 2000
    assert ceiling == 1_000_000


def test_song_unit_zero_notes_is_unavailable():
    assert sr.song_unit(None, 0) == (0, 0, False)


@pytest.mark.parametrize("rank,ratio", [(2, .5), (3, .6), (4, .7), (5, .8), (6, .9), (7, .95)])
def test_rank_threshold_uses_ratio_of_ceiling(rank, ratio):
    song = {"ceiling": 1_000_000, "top": 1_005_000, "rolls": 50}
    threshold = sr.rank_threshold(song, 500, rank)
    assert threshold["score"] == int(1_000_000 * ratio)
    assert threshold["rolls"] == 0
    assert threshold["requiresAllGood"] is False


def test_rank_threshold_top_rank_uses_kiwami_score_and_rolls():
    song = {"ceiling": 1_000_000, "top": 1_005_000, "rolls": 50}
    threshold = sr.rank_threshold(song, 500, 8)
    assert threshold["score"] == 1_005_000
    assert threshold["rolls"] == 50
    assert threshold["requiresAllGood"] is True


def test_rank_of_score_maps_borders():
    song = {"ceiling": 1_000_000, "top": 1_004_000, "rolls": 40}
    assert sr.rank_of_score(song, 500, 499_999) == 1
    assert sr.rank_of_score(song, 500, 500_000) == 2
    assert sr.rank_of_score(song, 500, 600_000) == 3
    assert sr.rank_of_score(song, 500, 700_000) == 4
    assert sr.rank_of_score(song, 500, 800_000) == 5
    assert sr.rank_of_score(song, 500, 900_000) == 6
    assert sr.rank_of_score(song, 500, 950_000) == 7
    assert sr.rank_of_score(song, 500, 1_004_000) == 8


# ---------------------------------------------------------------------------
# 提升候选分析
# ---------------------------------------------------------------------------

def _charts() -> dict:
    return {
        (1, 4): {"id": 1, "level": 4, "title": "甲", "titleJa": "甲", "genre": "J-POP", "totalNotes": 400},
        (2, 4): {"id": 2, "level": 4, "title": "乙", "titleJa": "乙", "genre": "アニメ", "totalNotes": 500},
        (3, 5): {"id": 3, "level": 5, "title": "丙", "titleJa": "丙", "genre": "J-POP", "totalNotes": 600},
    }


def _rank_data() -> dict:
    return {
        "songs": {
            "1|4": {"ceiling": 996000, "top": 1002000, "rolls": 24, "kind": ""},
            "2|4": {"ceiling": 1000000, "top": 1000000, "rolls": 0, "kind": "完全精度曲"},
            "3|5": {"ceiling": 1000000, "top": 1010000, "rolls": 100, "kind": ""},
        }
    }


def _record(song_no, level, score, rank, ok=0, ng=0, good=0):
    return {
        "id": song_no, "level": level, "highScore": score, "bestScoreRank": rank,
        "okCount": ok, "ngCount": ng, "goodCount": good, "poundCount": 0,
        "rating": 0.0, "constant": None,
    }


def test_analyze_converts_gap_into_ok_and_roll_requirements():
    records = [_record(1, 4, 750_000, 3, ok=40)]
    result = sr.analyze_rank_improvements(records, _charts(), _rank_data(), 5)
    assert result["scanned"] == 1
    assert result["candidateCount"] == 1
    item = result["items"][0]
    # 天井 996000，粉雅门槛 80% = 796800，缺口 46800，基本点 2490。
    assert item["targetScore"] == 796_800
    assert item["gap"] == 46_800
    assert item["okToGood"] == 38            # ceil(2 × 46800 / 2490)
    assert item["ngToGood"] == 0             # 当前 40 个「可」够用
    assert item["rollsNeeded"] == 468        # ceil(46800 / 100)
    assert item["pathRequiresAllGood"] is False


def test_analyze_asks_for_miss_conversion_when_ok_count_is_not_enough():
    records = [_record(1, 4, 750_000, 3, ok=2, ng=10)]
    item = sr.analyze_rank_improvements(records, _charts(), _rank_data(), 5)["items"][0]
    assert item["okToGood"] == 38
    # 把 2 个「可」全部打成「良」只补回 1 个基本点，剩余缺口仍需 18 个「不可」转「良」。
    assert item["ngToGood"] == 18


def test_analyze_top_rank_requires_all_good_plus_rolls():
    records = [_record(1, 4, 1_001_000, 7, ok=3, ng=1)]
    item = sr.analyze_rank_improvements(records, _charts(), _rank_data(), 8)["items"][0]
    assert item["pathRequiresAllGood"] is True
    assert item["targetScore"] == 1_002_000
    assert item["okToGood"] == 3             # 必须把残留的「可」全部打成「良」
    assert item["ngToGood"] == 1
    assert item["rollsNeeded"] == 24         # 且补足该谱规定连打打数


def test_analyze_respects_level_filter_and_counts_already_at_target():
    records = [
        _record(1, 4, 900_000, 5),           # 已达粉雅
        _record(2, 4, 500_000, 3),           # 未达标
        _record(3, 5, 700_000, 3),           # 难度 5，被 levels 过滤掉
    ]
    result = sr.analyze_rank_improvements(records, _charts(), _rank_data(), 5, levels=(4,))
    assert result["scanned"] == 2
    assert result["alreadyAtTarget"] == 1
    assert result["candidateCount"] == 1
    assert result["items"][0]["id"] == 2


def test_analyze_groups_by_genre_and_sorts_by_median_gap():
    records = [
        _record(1, 4, 700_000, 4, ok=50),
        _record(3, 5, 850_000, 5, ok=80),
        _record(2, 4, 880_000, 5, ok=5),
    ]
    result = sr.analyze_rank_improvements(records, _charts(), _rank_data(), 6, per_genre=2)
    genres = {row["genre"]: row for row in result["genres"]}
    assert genres["J-POP"]["count"] == 2
    assert genres["アニメ"]["count"] == 1
    assert all(len(row["closest"]) <= 2 for row in result["genres"])
    # 每个分区内按缺口升序
    for row in result["genres"]:
        gaps = [item["gap"] for item in row["closest"]]
        assert gaps == sorted(gaps)


def test_analyze_marks_estimated_thresholds():
    charts = {(9, 4): {"id": 9, "level": 4, "title": "丁", "titleJa": "丁", "genre": "X", "totalNotes": 500}}
    result = sr.analyze_rank_improvements([_record(9, 4, 400_000, 3)], charts, {"songs": {}}, 4)
    item = result["items"][0]
    assert item["exact"] is False
    assert item["targetScore"] == 700_000    # 估算天井 100 万 × 70%


def test_analyze_gap_limit_filters_far_candidates():
    records = [_record(1, 4, 200_000, 1, ok=50), _record(2, 4, 690_000, 3, ok=5)]
    result = sr.analyze_rank_improvements(
        records, _charts(), _rank_data(), 4, per_genre=5, gap_limit_ratio=0.1
    )
    assert [item["id"] for item in result["items"]] == [2]


# ---------------------------------------------------------------------------
# 资源加载
# ---------------------------------------------------------------------------

def _write_resource(tmp_path, payload) -> Path:
    path = tmp_path / "score_rank.v1.json.gz"
    path.write_bytes(gzip.compress(json.dumps(payload, ensure_ascii=False).encode("utf-8")))
    return path


def test_load_score_rank_normalises_and_indexes_by_genre(tmp_path):
    charts = {(1, 4): {"id": 1, "level": 4, "genre": "J-POP", "totalNotes": 400},
              (2, 5): {"id": 2, "level": 5, "genre": "アニメ", "totalNotes": 500}}
    path = _write_resource(tmp_path, {
        "schema_version": 1, "data_version": "test",
        "songs": {"1|4": {"ceiling": 996000, "top": 1000000, "rolls": 0},
                  "2|5": {"ceiling": 990000, "top": 990000, "rolls": 5, "kind": "精度曲"}},
    })
    data = sr.load_score_rank(path, charts)
    assert data["data_version"] == "test"
    assert set(data["songs"]) == {"1|4", "2|5"}
    assert data["songs"]["2|5"]["kind"] == "精度曲"
    assert data["by_genre"]["J-POP"] == [1]


def test_load_score_rank_rejects_wrong_schema(tmp_path):
    path = _write_resource(tmp_path, {"schema_version": 99, "songs": {}})
    with pytest.raises(sr.ScoreRankDataError):
        sr.load_score_rank(path)


def test_load_score_rank_rejects_invalid_entry(tmp_path):
    path = _write_resource(tmp_path, {
        "schema_version": 1, "songs": {"1|4": {"ceiling": 0}},
    })
    with pytest.raises(sr.ScoreRankDataError):
        sr.load_score_rank(path)


def test_load_score_rank_clamps_top_below_ceiling(tmp_path):
    path = _write_resource(tmp_path, {
        "schema_version": 1,
        "songs": {"1|4": {"ceiling": 1_000_000, "top": 900_000, "rolls": 5}},
    })
    data = sr.load_score_rank(path)
    assert data["songs"]["1|4"]["top"] == 1_000_000


def test_bundled_resource_is_loadable_and_covers_most_charts():
    charts = {}
    with gzip.open(PLUGIN_DIR / "resource" / "charts.v1.json.gz", "rb") as handle:
        for chart in json.loads(handle.read().decode("utf-8")):
            charts[(chart["id"], chart["level"])] = chart
    data = sr.load_score_rank(RESOURCE, charts)
    assert data["songs"]
    # wiki 极スコア 表与谱面库的交集应覆盖绝大部分谱面。
    assert len(data["songs"]) / len(charts) > 0.9
    # 每个条目都必须给出不低于天井的極スコア。
    assert all(entry["top"] >= entry["ceiling"] for entry in data["songs"].values())


# ---------------------------------------------------------------------------
# 渲染器
# ---------------------------------------------------------------------------

def test_improve_image_renders_fixed_size_png(tmp_path):
    import improve_image

    records = [
        _record(1, 4, 700_000, 4, ok=50),
        _record(3, 5, 850_000, 5, ok=80),
        _record(2, 4, 880_000, 5, ok=5),
    ]
    result = sr.analyze_rank_improvements(records, _charts(), _rank_data(), 6, per_genre=3)
    result["meta"] = {"playerId": "30053354", "server": "cn"}
    out = tmp_path / "improve.png"
    improve_image.render_improve_image(result, str(out))
    assert out.exists()
    with Image.open(out) as image:
        assert image.size == (improve_image.WIDTH, improve_image.HEIGHT)


def test_improve_image_layout_invariants():
    """固定像素版式的几何约束，防止后续调整坐标时把文字压到别的底色上。"""
    import improve_image as ii

    # `_text` 使用左上锚点：分区小标题的 y 必须整体落在深色主卡下沿之外。
    assert ii.HERO_TOP + ii.HERO_H < 580
    # 卡片网格不得与页脚分隔线重叠。
    grid_bottom = ii.GRID_TOP + 3 * ii.CARD_H + 2 * ii.CARD_GAP_Y
    assert grid_bottom < ii.FOOTER_LINE_Y
    # 页脚最后一行（页脚线 + 42 + 行高）必须留在画布内。
    assert ii.FOOTER_LINE_Y + 42 + 20 <= ii.HEIGHT
    # 两列卡片必须正好落在左右页边距之内。
    assert ii.GRID_LEFT + 2 * ii.CARD_W + ii.CARD_GAP_X == ii.WIDTH - ii.GRID_LEFT


def test_build_improve_data_caps_genres_and_items():
    import improve_image

    result = {
        "targetRank": 8,
        "scanned": 10,
        "alreadyAtTarget": 2,
        "candidateCount": 8,
        "exactCount": 7,
        "meta": {"playerId": "1", "server": "jp"},
        "note": "（默认）",
        "genres": [
            {"genre": f"G{i}", "count": 1, "gapMedian": i,
             "closest": [{"title": "t", "id": 1, "level": 4, "targetScore": 1, "currentScore": 1, "gap": 1}] * 9}
            for i in range(9)
        ],
    }
    data = improve_image.build_improve_data(result)
    assert len(data["genres"]) == improve_image.GENRE_CARDS
    assert all(len(row["closest"]) <= improve_image.ITEMS_PER_CARD for row in data["genres"])
    assert data["targetName"] == "极+连打满"
    assert data["targetRatio"] is None       # 最高档没有固定比例


# ---------------------------------------------------------------------------
# 服务层串联（命令与 LLM 工具最终都会走到这里）
# ---------------------------------------------------------------------------

def test_service_get_rank_improvement_uses_cached_analysis(tmp_path):
    import asyncio
    import time as _time

    import improve_image
    from service import (
        RATING_CACHE_SCHEMA, SCORE_STORAGE_SCHEMA, MemoryBindingsStore, ScoreService,
    )
    from storage import ScoreDatabase

    qq, player = "10001", "30053354"
    db = ScoreDatabase(tmp_path / "rt_link.db")
    service = ScoreService(
        store=MemoryBindingsStore(),
        client_factory=lambda key: None,
        charts=_charts(),
        score_db=db,
        score_rank=_rank_data(),
        report_dir=str(tmp_path),
    )

    async def scenario():
        await service.store.save({qq: {"apikey": "tk_x", "player_id": player, "server": "cn"}})
        db.put_rating_cache(qq, {
            "_cacheSchema": RATING_CACHE_SCHEMA,
            "_ts": _time.time(),
            "meta": {"playerId": player, "server": "cn"},
            "records": [{
                "id": 1, "level": 4, "title": "甲", "titleJa": "甲", "genre": "J-POP",
                "highScore": 700_000, "bestScoreRank": 4, "okCount": 50, "ngCount": 0,
                "goodCount": 350, "poundCount": 0, "rating": 10.0,
            }],
        })
        db.kv_set(f"score_storage_schema:{qq}", {
            "schema": SCORE_STORAGE_SCHEMA, "playerId": player, "server": "cn",
        })
        text = await service.get_rank_improvement_text(qq, 6)
        image = await service.generate_rank_improve_image(qq, 6)
        default_text = await service.get_rank_improvement_text(qq)   # 默认 = 最常见评价的上一档
        return text, image, default_text

    text, (ok, path), default_text = asyncio.run(scenario())
    db.close()

    assert "紫雅" in text and "896400" in text
    assert "/rtlink improve" in text
    assert ok is True and Path(path).exists()
    with Image.open(path) as image:
        assert image.size == (improve_image.WIDTH, improve_image.HEIGHT)

    # 只有 1 张成绩，最常见评价是金雅，默认目标应为其上一档粉雅。
    assert "粉雅" in default_text
