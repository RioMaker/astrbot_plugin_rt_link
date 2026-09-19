# -*- coding: utf-8 -*-
"""连打资料（合計連打秒数 / 秒速 / 理論値）与「补连打」路线的单元测试。

覆盖的核心诉求：
1. 没有黄条的谱面要能判出来，并明确「补分只能靠判定」。
2. 必须全良才能达到目标时要写出来（只有判定一条路 / 判定路线本身就是全良）。
3. 秒速按 wiki 规定算：黄色連打打数 ÷ 合計黄色連打秒数，风船不计入。
4. 还差几打、总打数、秒速都要给出；超出該谱連打理論値时要说明打不出来。
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parent.parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

import improve_text as it  # noqa: E402
import score_rank as sr  # noqa: E402

RESOURCE = PLUGIN_DIR / "resource" / "rolls.v1.json.gz"


# ---------------------------------------------------------------------------
# 资源加载
# ---------------------------------------------------------------------------

def _write_resource(tmp_path, payload) -> Path:
    path = tmp_path / "rolls.v1.json.gz"
    path.write_bytes(gzip.compress(json.dumps(payload, ensure_ascii=False).encode("utf-8")))
    return path


def _payload(songs: dict) -> dict:
    return {"schema_version": 1, "data_version": "test", "source": "unit", "songs": songs}


def test_load_rolls_normalises_entries(tmp_path):
    path = _write_resource(tmp_path, _payload({
        "1|4": {"seconds": 2.5, "rolls": 2, "maxHits": 151, "balloonSeconds": 1.25,
                "balloons": 1, "balloonHits": 7, "speed": 17.2, "source": "tja"},
        "2|5": {"seconds": 0, "rolls": 0, "balloonSeconds": 3.0, "balloons": 2},
    }))
    data = sr.load_rolls(path)
    assert data["data_version"] == "test"
    first = data["songs"]["1|4"]
    assert first["seconds"] == 2.5 and first["rolls"] == 2 and first["speed"] == 17.2
    assert first["balloonHits"] == 7
    # 没有黄条的谱面：seconds=0、maxHits=0，但风船资料保留。
    second = data["songs"]["2|5"]
    assert second["seconds"] == 0.0 and second["rolls"] == 0
    assert second["balloonSeconds"] == 3.0 and second["balloons"] == 2


def test_load_rolls_rejects_wrong_schema(tmp_path):
    path = _write_resource(tmp_path, {"schema_version": 99, "songs": {}})
    with pytest.raises(sr.ScoreRankDataError):
        sr.load_rolls(path)


def test_load_rolls_fills_theory_hits_when_missing(tmp_path):
    path = _write_resource(tmp_path, _payload({"1|4": {"seconds": 1.0, "rolls": 1}}))
    entry = sr.load_rolls(path)["songs"]["1|4"]
    assert entry["maxHits"] == sr.theoretical_hits(1.0) == 61


def test_theoretical_hits_follows_the_wiki_rule():
    """連打理論値 = ⌈(秒数 + 0.001) × 60⌉：0.5 秒 → 31 打（0.5 秒也可能只进 30 打）。"""
    assert sr.theoretical_hits(0.5) == 31
    assert sr.theoretical_hits(0.51) == 31
    assert sr.theoretical_hits(0.495) == 30
    assert sr.theoretical_hits(0.166) == 11


def test_bundled_roll_resource_covers_most_charts_and_marks_no_roll_songs():
    charts = {}
    with gzip.open(PLUGIN_DIR / "resource" / "charts.v1.json.gz", "rb") as handle:
        for chart in json.loads(handle.read().decode("utf-8")):
            charts[(chart["id"], chart["level"])] = chart
    data = sr.load_rolls(RESOURCE, charts)
    assert len(data["songs"]) / len(charts) > 0.9
    with_rolls = [item for item in data["songs"].values() if item["rolls"] > 0]
    without = [item for item in data["songs"].values() if item["rolls"] == 0]
    assert len(with_rolls) > 900
    assert len(without) > 100          # 确实存在没有黄条的谱面
    # 有黄条的条目必须给出秒数，秒速才能算出来。
    assert all(item["seconds"] > 0 for item in with_rolls)
    assert all(item["maxHits"] > 0 for item in with_rolls)
    # 没有黄条的条目不允许残留秒数，避免误报「可以靠连打补」。
    assert all(item["seconds"] == 0 for item in without)


def test_bundled_roll_resource_matches_wiki_for_known_songs():
    """用几张 wiki 公布过连打秒数的谱面回归：解析结果必须与 wiki 一致（±0.02 秒）。"""
    data = sr.load_rolls(RESOURCE)
    songs = data["songs"]
    # wiki「連打秒数表」：Garakuta Doll Play(裏) 合计 3.730 秒；Rotter Tarmination(裏) 黄条 1.025 秒。
    assert songs["154|5"]["seconds"] == pytest.approx(3.730, abs=0.02)
    assert songs["154|5"]["rolls"] == 25
    assert songs["402|5"]["seconds"] == pytest.approx(1.025, abs=0.02)
    # ネクロファンタジア ～ Arr.Demetori：合计 17.833 秒（12 条）。
    assert songs["421|4"]["rolls"] == 12
    assert songs["421|4"]["seconds"] == pytest.approx(17.833, abs=0.02)
    # Rotter Tarmination(表) 只有风船没有黄条 —— 正是「不能靠连打补分」的典型。
    assert songs["402|4"]["rolls"] == 0
    assert songs["402|4"]["balloons"] > 0


# ---------------------------------------------------------------------------
# 判定路线与全良判定
# ---------------------------------------------------------------------------

def test_judgment_plan_flags_all_good_when_every_ok_must_be_converted():
    # 基本点 2000：一个「可→良」= 1000 分；缺口 3000 需要 3 个「可」，正好用完 3 个可。
    plan = sr.judgment_plan(3000, 2000, ok_count=3, ng_count=0)
    assert plan["okToGood"] == 3
    assert plan["ngToGood"] == 0
    assert plan["requiresAllGood"] is True
    assert plan["covers"] is True


def test_judgment_plan_does_not_flag_all_good_when_one_ok_can_remain():
    plan = sr.judgment_plan(3000, 2000, ok_count=4, ng_count=0)
    assert plan["okToGood"] == 3
    assert plan["requiresAllGood"] is False


def test_judgment_plan_flags_all_good_when_misses_must_be_converted():
    plan = sr.judgment_plan(5000, 2000, ok_count=1, ng_count=2)
    assert plan["okToGood"] == 5      # 先按整点算，再回落到「可」不够
    assert plan["ngToGood"] == 2
    assert plan["requiresAllGood"] is True


def test_judgment_plan_does_not_flag_all_good_without_any_ok_or_miss():
    """本来就没有可/不可时不算「必须全良」——此时判定路线根本补不了分。"""
    plan = sr.judgment_plan(5000, 2000, ok_count=0, ng_count=0)
    assert plan["requiresAllGood"] is False
    assert plan["covers"] is False


def test_judgment_plan_reports_when_all_good_is_not_enough():
    plan = sr.judgment_plan(10000, 2000, ok_count=1, ng_count=1)
    assert plan["covers"] is False    # 全良最多补 1000 + 2000 = 3000 分


# ---------------------------------------------------------------------------
# 连打路线
# ---------------------------------------------------------------------------

def _entry(**overrides) -> dict:
    entry = {
        "seconds": 4.0, "rolls": 3, "maxHits": 241,
        "balloonSeconds": 0.0, "balloons": 0, "balloonHits": 0,
        "speed": None, "source": "tja",
    }
    entry.update(overrides)
    return entry


def test_roll_plan_converts_gap_into_hits_and_speed():
    """秒速 = 黄条总打数 ÷ 合計秒数：现有 100 打 + 补 50 打 = 150 打 ÷ 4 秒 = 37.50。"""
    plan = sr.roll_plan(_entry(), gap=5000, pound_count=100, ceiling=995000)
    assert plan["hitsNeeded"] == 50
    assert plan["currentHits"] == 100
    assert plan["totalHits"] == 150
    assert plan["speed"] == 37.5
    assert plan["feasible"] is True
    assert plan["maxScore"] == 995000 + 100 * 241


def test_roll_plan_rounds_speed_to_two_decimals():
    """wiki 规定秒速四舍五入到小数点后 2 位。"""
    plan = sr.roll_plan(_entry(seconds=2.964286), gap=5100, pound_count=0, ceiling=1_000_000)
    assert plan["hitsNeeded"] == 51
    assert plan["speed"] == pytest.approx(17.20, abs=0.005)


def test_roll_plan_excludes_balloons_from_hits_and_seconds():
    """风船打数要从结算连打数里扣掉，风船秒数也不进分母。"""
    entry = _entry(seconds=10.0, balloonSeconds=5.0, balloons=1, balloonHits=40)
    plan = sr.roll_plan(entry, gap=2000, pound_count=140, ceiling=990000)
    assert plan["balloonHits"] == 40          # 要求 40 打 < 5 秒 × 17 打的常规量
    assert plan["currentHits"] == 100         # 140 - 40
    assert plan["totalHits"] == 120
    assert plan["speed"] == pytest.approx(12.0)


def test_roll_plan_caps_absurd_balloon_requirements():
    """大風船的要求打数可能远高于实际能打出的量（Rotter Tarmination 表记 999），按常规量封顶。"""
    entry = _entry(seconds=1.0, balloonSeconds=4.0, balloons=1, balloonHits=999)
    plan = sr.roll_plan(entry, gap=0, pound_count=100, ceiling=1_000_000)
    assert plan["balloonHits"] == 68          # ⌈4 秒 × 17 打/秒⌉
    assert plan["currentHits"] == 32


def test_roll_plan_without_rolls_says_route_is_unavailable():
    entry = _entry(seconds=0.0, rolls=0, maxHits=0, balloonSeconds=4.7, balloons=1, balloonHits=79)
    plan = sr.roll_plan(entry, gap=5000, pound_count=90, ceiling=996000)
    assert plan["hasRolls"] is False
    assert plan["speed"] is None and plan["feasible"] is False
    assert plan["balloons"] == 1


def test_roll_plan_without_data_is_unknown():
    plan = sr.roll_plan(None, gap=5000, pound_count=10, ceiling=1_000_000)
    assert plan["known"] is False
    assert plan["hasRolls"] is False and plan["speed"] is None


def test_roll_plan_flags_shortfall_when_theory_hits_run_out():
    entry = _entry(seconds=2.0, rolls=1, maxHits=121)
    plan = sr.roll_plan(entry, gap=20000, pound_count=100, ceiling=1_000_000)
    assert plan["hitsNeeded"] == 200
    assert plan["totalHits"] == 300
    assert plan["feasible"] is False
    assert plan["shortfall"] == 179          # 300 - 121


# ---------------------------------------------------------------------------
# 组合：提升评价分析
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


def _rolls_data() -> dict:
    return {
        "songs": {
            "1|4": {"seconds": 4.0, "rolls": 3, "maxHits": 241, "balloonSeconds": 0.0,
                    "balloons": 0, "balloonHits": 0, "speed": 17.3, "source": "tja"},
            "2|4": {"seconds": 0.0, "rolls": 0, "maxHits": 0, "balloonSeconds": 3.0,
                    "balloons": 1, "balloonHits": 12, "speed": None, "source": "tja"},
        }
    }


def _record(song_no, level, score, rank, ok=0, ng=0, good=0, pound=0):
    return {
        "id": song_no, "level": level, "highScore": score, "bestScoreRank": rank,
        "okCount": ok, "ngCount": ng, "goodCount": good, "poundCount": pound,
        "rating": 0.0, "constant": None,
    }


def test_analyze_reports_roll_route_with_speed_and_total_hits():
    records = [_record(1, 4, 750_000, 3, ok=40, pound=200)]
    item = sr.analyze_rank_improvements(
        records, _charts(), _rank_data(), 5, rolls_data=_rolls_data()
    )["items"][0]
    assert item["hasRolls"] is True
    assert item["rollCount"] == 3 and item["rollSeconds"] == 4.0
    assert item["rollsNeeded"] == 516          # ⌈51600 ÷ 100⌉
    assert item["rollCurrentHits"] == 200
    assert item["rollTotalHits"] == 716
    assert item["rollSpeed"] == pytest.approx(179.0)
    assert item["rollFeasible"] is False       # 超过理論値 241 打
    assert item["mustAllGood"] is True         # 连打走不通，只能全良


def test_analyze_marks_songs_without_yellow_rolls():
    """没有黄条的谱面必须明确标出来 —— 这类曲目只能靠判定提升。"""
    records = [_record(2, 4, 880_000, 5, ok=30)]
    result = sr.analyze_rank_improvements(
        records, _charts(), _rank_data(), 6, rolls_data=_rolls_data()
    )
    item = result["items"][0]
    assert item["rollKnown"] is True
    assert item["hasRolls"] is False
    assert item["rollBalloons"] == 1
    assert item["rollSpeed"] is None
    assert result["noRollCount"] == 1
    assert "没有黄条" in it.roll_route_text(item)


def test_analyze_without_rolls_resource_marks_data_unknown():
    records = [_record(1, 4, 750_000, 3, ok=40)]
    result = sr.analyze_rank_improvements(records, _charts(), _rank_data(), 5)
    item = result["items"][0]
    assert item["rollKnown"] is False
    assert result["rollUnknownCount"] == 1
    assert "缺少" in it.roll_route_text(item)


def test_analyze_counts_all_good_and_unreachable_candidates():
    """连打超上限 → 必须全良；连全良＋黄条打满都够不到 極スコア → 不可达。"""
    rank = _rank_data()
    rank["songs"]["3|5"] = {"ceiling": 1_000_000, "top": 1_010_000, "rolls": 100, "kind": ""}
    rolls = _rolls_data()
    rolls["songs"]["3|5"] = {"seconds": 0.9, "rolls": 1, "maxHits": 50, "balloonSeconds": 0.0,
                             "balloons": 0, "balloonHits": 0, "speed": None, "source": "tja"}
    records = [
        _record(1, 4, 750_000, 3, ok=40),        # 打「极」要补 2520 打，远超黄条上限 → 必须全良
        _record(3, 5, 900_000, 7, ok=0, ng=0),   # 極スコア 1,010,000 但上限只有 1,005,000
    ]
    result = sr.analyze_rank_improvements(
        records, _charts(), rank, 8, rolls_data=rolls
    )
    assert result["allGoodRequiredCount"] == 1
    assert result["unreachableCount"] == 1
    unreachable = [item for item in result["items"] if item["unreachable"]][0]
    assert unreachable["maxScore"] == 1_005_000
    assert it.gap_route_lines(unreachable)[0].startswith("本曲上限约")


# ---------------------------------------------------------------------------
# 文案
# ---------------------------------------------------------------------------

def test_roll_text_shows_needed_hits_total_and_speed():
    entry = _entry(seconds=8.22, maxHits=sr.theoretical_hits(8.22))
    plan = sr.roll_plan(entry, gap=14900, pound_count=262, ceiling=985000)
    item = dict(plan, rollKnown=True, hasRolls=True, rollsNeeded=plan["hitsNeeded"],
                rollSeconds=plan["seconds"], rollCount=plan["rollCount"],
                rollMaxHits=plan["maxHits"], rollTotalHits=plan["totalHits"],
                rollCurrentHits=plan["currentHits"], rollSpeed=plan["speed"],
                rollFeasible=plan["feasible"], rollShortfall=plan["shortfall"])
    assert plan["feasible"] is True
    text = it.roll_route_text(item)
    assert "补 149 打" in text
    assert "黄条共约 411 打" in text
    assert "秒速约 50.00 打/秒" in text


def test_roll_text_explains_when_no_yellow_bar():
    item = {"rollKnown": True, "hasRolls": False, "rollBalloons": 2, "rollsNeeded": 120,
            "judgmentCovers": True}
    assert "没有黄条" in it.roll_route_text(item)
    assert "只能靠判定" in it.roll_route_text(item)


def test_roll_text_says_target_is_out_of_reach_when_judgment_also_falls_short():
    item = {"rollKnown": True, "hasRolls": False, "rollBalloons": 1, "rollsNeeded": 120,
            "judgmentCovers": False}
    text = it.roll_route_text(item)
    assert "暂时达不到" in text


def test_roll_text_compares_with_the_charts_kiwami_speed():
    """要求秒速明显偏高时，用该谱拿「极」的要求速度做参照（比一个固定区间更贴切）。"""
    item = {"rollKnown": True, "hasRolls": True, "rollsNeeded": 100, "rollCount": 3,
            "rollSeconds": 2.78, "rollMaxHits": 168, "rollFeasible": True,
            "rollTotalHits": 160, "rollCurrentHits": 60, "rollSpeed": 57.65,
            "rollKiwamiSpeed": 17.65}
    text = it.roll_route_text(item)
    assert "秒速约 57.65 打/秒" in text
    assert "该谱拿「极」约需 17.65 打/秒" in text


def test_roll_text_explains_when_theory_hits_are_not_enough():
    item = {"rollKnown": True, "hasRolls": True, "rollsNeeded": 400, "rollCount": 3,
            "rollSeconds": 2.78, "rollMaxHits": 168, "rollFeasible": False,
            "rollShortfall": 352}
    text = it.roll_route_text(item)
    assert "已超上限" in text
    assert "理論値共 168 打" in text


def test_judgment_text_mentions_all_good_when_required():
    item = {"okCount": 5, "ngCount": 2, "okToGood": 5, "ngToGood": 2,
            "judgmentCovers": True, "judgmentRequiresAllGood": True}
    text = it.judgment_route_text(item)
    assert "全良" in text
    assert "5 个「可」全打成「良」" in text
    assert "2 个「不可」打成「良」" in text


def test_judgment_text_clamps_to_available_ok_and_reports_shortfall():
    """「可」不够时不能报出比实际更多的良数；全良也补不满要说清楚还差多少分。"""
    item = {"okCount": 2, "ngCount": 1, "okToGood": 7, "ngToGood": 3,
            "judgmentCovers": False, "judgmentRequiresAllGood": True,
            "judgmentGain": 4980, "judgmentShortfall": 1120}
    text = it.judgment_route_text(item)
    assert "把 2 个「可」全打成「良」" in text
    assert "＋1 个「不可」打成「良」" in text
    assert "只能补 4980 分" in text
    assert "还差 1120 分" in text


def test_gap_route_lines_reports_unreachable_ceiling():
    item = {"unreachable": True, "maxScore": 1_004_000, "targetName": "极"}
    lines = it.gap_route_lines(item)
    assert len(lines) == 1
    assert "1004000" in lines[0] and "达不到" in lines[0]
