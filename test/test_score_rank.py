# -*- coding: utf-8 -*-
"""スコアランク 门槛计算、提升候选分析与渲染器的单元测试。"""

from __future__ import annotations

import gzip
import json
import math
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
    ("无", 1), ("1", 1),
    ("白粹", 2), ("白粋", 2), ("shirosui", 2),
    ("铜粹", 3), ("銅粋", 3), ("dousui", 3),
    ("银粹", 4), ("銀粋", 4), ("gInSuI", 4),
    ("金雅", 5), ("kinga", 5),
    ("粉雅", 6), ("紫雅", 7), ("shiga", 7),
    ("极", 8), ("極", 8), ("  Kiwami  ", 8), ("极+连打满", 8), ("極スコア", 8),
    (8, 8),
])
def test_parse_score_rank_accepts_names_and_numbers(text, expected):
    assert sr.parse_score_rank(text) == expected


def test_copper_and_silver_are_not_swapped():
    """回归：第 3 档是「铜粹」，第 4 档是「银粹」。早期版本漏掉铜粹后名称整体低了一档。"""
    assert sr.SCORE_RANK_NAMES[3] == "铜粹"
    assert sr.SCORE_RANK_NAMES[4] == "银粹"
    assert sr.SCORE_RANK_NAMES[7] == "紫雅"
    assert sr.SCORE_RANK_NAMES[8] == "极"
    assert [sr.SCORE_RANK_NAMES[i] for i in range(1, 9)] == [
        "无", "白粹", "铜粹", "银粹", "金雅", "粉雅", "紫雅", "极",
    ]


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


@pytest.mark.parametrize("rank,ratio", [
    (2, 0.50), (3, 0.60), (4, 0.70), (5, 0.80), (6, 0.90), (7, 0.95), (8, 1.00),
])
def test_rank_threshold_is_a_ratio_of_kiwami_score(rank, ratio):
    """门槛 = 该谱極スコア × 比例；锚点是 極スコア，不是天井スコア。"""
    song = {"ceiling": 1_000_000, "top": 1_005_000, "rolls": 50}
    threshold = sr.rank_threshold(song, 500, rank)
    assert threshold["score"] == int(math.ceil(1_005_000 * ratio))
    assert threshold["anchor"] == 1_005_000
    assert sr.SCORE_RANK_RATIOS[rank] == ratio


def test_threshold_follows_each_songs_kiwami_score_not_a_flat_number():
    """同一分数在两首極スコア不同的谱面上可以落在不同档位 —— 这正是实测数据的规律。

    实测（1390 条）：用「極スコア × 比例」错判 2 条，用固定绝对值错判 22 条，
    用「天井スコア × 比例」错判 24 条。
    """
    # 極スコア 1,004,800（《秋竜》）：90% = 904,320，904,140 差一点 → 粉雅档
    assert sr.rank_of_score({"ceiling": 1_003_200, "top": 1_004_800, "rolls": 0}, 500, 904_140) == 5
    # 極スコア 1,000,889：90% = 900,801，同样 904,140 已过线 → 紫雅档
    assert sr.rank_of_score({"ceiling": 1_000_000, "top": 1_000_889, "rolls": 0}, 500, 904_140) == 6


def test_top_rank_threshold_is_the_kiwami_score_itself():
    """100% 档就是極スコア；rolls 只是「全良时所需连打打数」的参考值。"""
    song = {"ceiling": 1_000_000, "top": 1_005_000, "rolls": 50}
    threshold = sr.rank_threshold(song, 500, 8)
    assert threshold["score"] == 1_005_000
    assert threshold["rolls"] == 50
    assert "requiresAllGood" not in threshold


def test_rank_of_score_maps_all_eight_tiers():
    song = {"ceiling": 1_000_000, "top": 1_004_000, "rolls": 40}
    borders = {rank: math.ceil(1_004_000 * ratio) for rank, ratio in sr.SCORE_RANK_RATIOS.items()}
    assert sr.rank_of_score(song, 500, 499_999) == 1
    for rank, border in sorted(borders.items()):
        assert sr.rank_of_score(song, 500, border) == rank, rank
        assert sr.rank_of_score(song, 500, border - 1) == rank - 1, rank


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
    # 金雅门槛 = 極スコア 1002000 × 80% = 801600；缺口 51600；基本点 = 996000 ÷ 400 = 2490。
    assert item["targetScore"] == 801_600
    assert item["gap"] == 51_600
    assert item["okToGood"] == 42            # ⌈2 × 51600 / 2490⌉
    assert item["ngToGood"] == 1             # 40 个「可」全转「良」后仍差 1800 分，需再补 1 个「不可」
    assert item["rollsNeeded"] == 516        # ⌈51600 / 100⌉
    assert item["allGoodRolls"] == 24


def test_analyze_asks_for_miss_conversion_when_ok_count_is_not_enough():
    records = [_record(1, 4, 750_000, 3, ok=2, ng=10)]
    item = sr.analyze_rank_improvements(records, _charts(), _rank_data(), 5)["items"][0]
    assert item["okToGood"] == 42
    # 2 个「可」全部转「良」只补回 1 个基本点，剩余缺口仍需「不可」转「良」。
    assert item["ngToGood"] == 20


def test_analyze_skips_songs_the_game_already_rated_at_target():
    """游戏给的 best_score_rank 是权威；即使本地按分数算还没到，也不该列进待提升。"""
    records = [_record(1, 4, 780_000, 6, ok=10)]     # 分数只到银粹档，但游戏已判粉雅
    result = sr.analyze_rank_improvements(records, _charts(), _rank_data(), 6)
    assert result["alreadyAtTarget"] == 1
    assert result["candidateCount"] == 0


def test_analyze_top_rank_is_a_score_threshold_not_all_good():
    """「极」的门槛是分数 ≥ 極スコア，**不要求全良**。

    黄色连打每打固定 100 分，判定上亏掉的分可以用多打连打补回来；
    `allGoodRolls`（该谱全良时所需的连打打数）只是参考值。
    """
    records = [_record(1, 4, 1_001_000, 7, ok=3, ng=1)]
    item = sr.analyze_rank_improvements(records, _charts(), _rank_data(), 8)["items"][0]
    assert item["targetScore"] == 1_002_000     # 该谱極スコア
    assert item["gap"] == 1_000
    assert item["okToGood"] == 1                # 只需补 1 个「可」，不是「必须全良」
    assert item["ngToGood"] == 0
    assert item["rollsNeeded"] == 10            # 或不动判定，补 10 打连打
    assert item["allGoodRolls"] == 24           # 全良时才是 24 打，仅供参照
    assert "pathRequiresAllGood" not in item


def test_analyze_respects_level_filter_and_counts_already_at_target():
    records = [
        _record(1, 4, 900_000, 5),           # 已达金雅
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
    """没有 wiki 数据时 極スコア 未知，只能用估算天井当锚点，门槛标为估算。"""
    charts = {(9, 4): {"id": 9, "level": 4, "title": "丁", "titleJa": "丁", "genre": "X", "totalNotes": 500}}
    result = sr.analyze_rank_improvements([_record(9, 4, 400_000, 3)], charts, {"songs": {}}, 4)
    item = result["items"][0]
    assert item["targetScore"] == 700_000    # 估算極スコア 100 万 × 70%
    assert item["exact"] is False


def test_top_rank_without_wiki_data_falls_back_to_estimated_ceiling():
    charts = {(9, 4): {"id": 9, "level": 4, "title": "丁", "titleJa": "丁", "genre": "X", "totalNotes": 500}}
    result = sr.analyze_rank_improvements([_record(9, 4, 900_000, 7)], charts, {"songs": {}}, 8)
    item = result["items"][0]
    assert item["exact"] is False            # 極スコア 未知，只能用估算天井
    assert item["targetScore"] == 1_000_000


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
    assert data["targetName"] == "极"
    assert data["targetRatio"] == 1.0        # 最高档就是極スコア 的 100%


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

    # 紫雅门槛 = 極スコア 1002000 × 90% = 901800
    assert "粉雅" in text and "901800" in text
    assert "/rtlink improve" in text
    assert ok is True and Path(path).exists()
    with Image.open(path) as image:
        assert image.size == (improve_image.WIDTH, improve_image.HEIGHT)

    # 只有 1 张成绩，最常见评价是银粹（4 档），默认目标应为其上一档金雅（5 档）。
    assert "金雅" in default_text
