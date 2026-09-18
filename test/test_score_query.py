# -*- coding: utf-8 -*-
"""score_query 自定义检索层，以及 `/rtlink <评价>` 简写分发的测试。"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import score_query as sq  # noqa: E402
import score_rank as sr  # noqa: E402


# ---------------------------------------------------------------------------
# 测试数据
# ---------------------------------------------------------------------------

def make_charts():
    return {
        (1, 4): {"id": 1, "level": 4, "title": "夏祭", "titleJa": "夏祭り", "genre": "J-POP", "totalNotes": 400,
                 "public": {"constant": 9.0}, "feature": {"aiConstant": 9.2}},
        (2, 4): {"id": 2, "level": 4, "title": "天竺2000", "titleJa": "てんぢく2000", "genre": "ナムコオリジナル",
                 "totalNotes": 831, "public": {"constant": 10.5}, "feature": {"aiConstant": 10.6}},
        (2, 5): {"id": 2, "level": 5, "title": "天竺2000", "titleJa": "てんぢく2000", "genre": "ナムコオリジナル",
                 "totalNotes": 900, "public": {"constant": 10.8}, "feature": {"aiConstant": 10.9}},
        (3, 4): {"id": 3, "level": 4, "title": "未游玩曲", "titleJa": "みプレイ", "genre": "アニメ",
                 "totalNotes": 500, "public": {"constant": 8.0}, "feature": {"aiConstant": 8.1}},
        (4, 4): {"id": 4, "level": 4, "title": "零不可曲", "titleJa": "ゼロミス", "genre": "クラシック",
                 "totalNotes": 600, "public": {"constant": 9.5}, "feature": {"aiConstant": 9.6}},
    }


def make_rank_data():
    return {
        "songs": {
            "1|4": {"ceiling": 1_000_000, "top": 1_004_000, "rolls": 40, "kind": ""},
            "2|4": {"ceiling": 996_000, "top": 1_000_000, "rolls": 0, "kind": "完全精度曲"},
            "4|4": {"ceiling": 1_000_000, "top": 1_005_000, "rolls": 50, "kind": ""},
        }
    }


def make_records():
    return [
        {"id": 1, "level": 4, "title": "夏祭", "titleJa": "夏祭り", "genre": "J-POP",
         "rating": 12.0, "accuracy": .980, "constant": 9.0, "highScore": 950_000, "bestScoreRank": 7,
         "goodCount": 380, "okCount": 20, "ngCount": 0, "poundCount": 0,
         "fullComboCount": 1, "dondafulComboCount": 0, "clearCount": 5, "updatedAt": "2026-09-01 10:00:00"},
        {"id": 2, "level": 4, "title": "天竺2000", "titleJa": "てんぢく2000", "genre": "ナムコオリジナル",
         "rating": 13.4, "accuracy": .995, "constant": 10.5, "highScore": 999_000, "bestScoreRank": 7,
         "goodCount": 800, "okCount": 31, "ngCount": 0, "poundCount": 120,
         "fullComboCount": 1, "dondafulComboCount": 0, "clearCount": 9, "updatedAt": "2026-09-10 20:00:00"},
        {"id": 2, "level": 5, "title": "天竺2000", "titleJa": "てんぢく2000", "genre": "ナムコオリジナル",
         "rating": 13.0, "accuracy": .960, "constant": 10.8, "highScore": 880_000, "bestScoreRank": 5,
         "goodCount": 800, "okCount": 90, "ngCount": 10, "poundCount": 60,
         "fullComboCount": 0, "dondafulComboCount": 0, "clearCount": 3, "updatedAt": "2026-08-20 09:00:00"},
        {"id": 4, "level": 4, "title": "零不可曲", "titleJa": "ゼロミス", "genre": "クラシック",
         "rating": 11.0, "accuracy": .990, "constant": 9.5, "highScore": 960_000, "bestScoreRank": 7,
         "goodCount": 590, "okCount": 10, "ngCount": 0, "poundCount": 0,
         "fullComboCount": 0, "dondafulComboCount": 0, "clearCount": 2, "updatedAt": "2026-09-05 12:00:00"},
    ]


def records_ok():
    """把夏祭（id 1 / 鬼）压到 650000 分，便于验证缺口换算。

    评价也要一并改成与分数一致的档位：游戏给的 best_score_rank 是权威，
    留着 7（极）会让「已达目标」判断提前命中，测不到缺口换算。
    """
    records = make_records()
    records[0]["highScore"] = 650_000
    records[0]["bestScoreRank"] = 3          # 银粹档（60 万 ~ 70 万）
    return records


def select(**kwargs):
    return sq.select(make_records(), make_charts(), make_rank_data(), **kwargs)


def select_with(records, **kwargs):
    return sq.select(records, make_charts(), make_rank_data(), **kwargs)


def titles(result):
    return [f"{row['id']}|{row['level']}" for row in result["rows"]]


# ---------------------------------------------------------------------------
# 匹配方式
# ---------------------------------------------------------------------------

def test_contains_matches_title_title_ja_and_genre_by_default():
    assert titles(select(query="夏祭")) == ["1|4"]
    assert titles(select(query="夏祭り")) == ["1|4"]
    # match_fields=any 也覆盖分区
    assert set(titles(select(query="ナムコ", limit=10))) == {"2|4", "2|5"}


def test_match_fields_restricts_the_searched_columns():
    # 「J-POP」只在分区里出现，限定只看曲名时不应命中。
    assert titles(select(query="J-POP", match_fields="title")) == []
    assert titles(select(query="J-POP", match_fields="genre")) == ["1|4"]


def test_exact_mode_requires_full_equality():
    assert titles(select(query="天竺2000", match_mode="exact", match_fields="title", limit=10)) == ["2|4", "2|5"]
    assert titles(select(query="天竺", match_mode="exact", match_fields="title")) == []


def test_regex_mode():
    assert set(titles(select(query=r"2000$", match_mode="regex", limit=10))) == {"2|4", "2|5"}
    assert titles(select(query=r"^夏", match_mode="regex")) == ["1|4"]


def test_invalid_regex_falls_back_to_contains_with_note():
    result = select(query="[unclosed", match_mode="regex")
    assert result["total"] == 0
    assert any("正则表达式无效" in note for note in result["notes"])


def test_all_and_any_match_modes_split_on_whitespace():
    # 「天 2000」两个分词都在日文名里 -> all 命中
    assert set(titles(select(query="天 2000", match_mode="all", limit=10))) == {"2|4", "2|5"}
    # 「夏 零」没有一首同时包含 -> all 空，any 命中两首
    assert titles(select(query="夏 零", match_mode="all")) == []
    assert set(titles(select(query="夏 零", match_mode="any", limit=10))) == {"1|4", "4|4"}


def test_alias_matching_uses_the_alias_index():
    result = sq.select(make_records(), make_charts(), make_rank_data(),
                       alias_index={1: ["なつまつり"]}, query="なつまつり")
    assert titles(result) == ["1|4"]


# ---------------------------------------------------------------------------
# 作用域
# ---------------------------------------------------------------------------

def test_scope_played_unplayed_and_all():
    assert set(titles(select(scope="played", limit=10))) == {"1|4", "2|4", "2|5", "4|4"}
    assert titles(select(scope="unplayed", limit=10)) == ["3|4"]
    assert len(select(scope="all", limit=99)["rows"]) == 5


def test_unplayed_rows_expose_chart_metadata_without_scores():
    row = select(scope="unplayed")["rows"][0]
    assert row["played"] is False
    assert row["rated"] is False
    assert row["constant"] == 8.0
    assert row["totalNotes"] == 500
    assert row["highScore"] is None and row["bestScoreRank"] == 0


def test_unrated_scope_exposes_played_but_unrated_charts():
    """打过但被 analyze 丢弃的曲目（谱面资料版本不一致 / 精度过低）。"""
    result = sq.select(make_records(), make_charts(), make_rank_data(),
                       unrated=[{"id": 3, "level": 4, "code": "calculation-error",
                                 "reason": "缺少 AI v2 谱面预测"}],
                       scope="unrated")
    assert titles(result) == ["3|4"]
    row = result["rows"][0]
    assert row["played"] is True and row["rated"] is False
    assert row["unratedCode"] == "calculation-error"
    assert "缺少 AI v2 谱面预测" in row["unratedReason"]


def test_unrated_keys_are_excluded_from_unplayed():
    """回归：这些曲目玩家其实打过，不能报成「未游玩」。"""
    unrated = [{"id": 3, "level": 4, "code": "calculation-error", "reason": "x"}]
    result = sq.select(make_records(), make_charts(), make_rank_data(),
                       unrated=unrated, scope="unplayed")
    assert result["total"] == 0
    # all 仍然覆盖全部 5 张谱面，且不重复计算。
    everything = sq.select(make_records(), make_charts(), make_rank_data(),
                           unrated=unrated, scope="all", limit=99)
    assert everything["total"] == 5
    assert titles(everything).count("3|4") == 1


def test_unrated_entries_without_chart_or_already_rated_are_ignored():
    result = sq.select(make_records(), make_charts(), make_rank_data(),
                       unrated=[{"id": 999, "level": 4}, {"id": 1, "level": 4}],
                       scope="unrated")
    assert result["total"] == 0


# ---------------------------------------------------------------------------
# 数值与状态条件
# ---------------------------------------------------------------------------

def test_constant_range_filter():
    assert set(titles(select(constant_min=10.0, limit=10))) == {"2|4", "2|5"}
    assert titles(select(constant_min=10.0, constant_max=10.6, limit=10)) == ["2|4"]


def test_constant_max_zero_means_unset():
    # 定数上限为 0 不可能是有效约束，按「不限」处理而不是查出空集。
    assert len(select(constant_max=0, limit=99)["rows"]) == 4
    assert len(select(constant_max=-1, limit=99)["rows"]) == 4


def test_accuracy_accepts_both_ratio_and_percent():
    assert titles(select(accuracy_min=0.99, limit=10)) == ["2|4", "4|4"]
    assert titles(select(accuracy_min=99, limit=10)) == ["2|4", "4|4"]


def test_ng_and_ok_upper_bounds_accept_zero():
    # ng_max=0 是有效条件：零不可
    assert set(titles(select(ng_max=0, limit=10))) == {"1|4", "2|4", "4|4"}
    # ok_max=0 表示一个「可」都没有
    assert titles(select(ok_max=0, limit=10)) == []


def test_rank_range_filter_and_zero_rank_max_is_unset():
    assert set(titles(select(rank_min=7, limit=10))) == {"1|4", "2|4", "4|4"}
    assert titles(select(rank_max=5, limit=10)) == ["2|5"]
    # rank_max=0 不是有效评价，按不限处理。
    assert len(select(rank_max=0, limit=99)["rows"]) == 4


def test_combo_modes():
    assert set(titles(select(combo="full", limit=10))) == {"1|4", "2|4"}
    assert titles(select(combo="no-fc", limit=10)) == ["2|5", "4|4"]
    assert set(titles(select(combo="no-miss", limit=10))) == {"1|4", "2|4", "4|4"}
    assert titles(select(combo="miss", limit=10)) == ["2|5"]


def test_score_and_notes_range_filters():
    assert set(titles(select(score_min=960_000, limit=10))) == {"2|4", "4|4"}
    assert titles(select(notes_min=800, limit=10)) == ["2|4", "2|5"]


def test_level_and_genre_and_song_no_filters():
    assert set(titles(select(levels=(5,), limit=10))) == {"2|5"}
    assert set(titles(select(genre="ナムコ", limit=10))) == {"2|4", "2|5"}
    assert set(titles(select(song_no=2, limit=10))) == {"2|4", "2|5"}


# ---------------------------------------------------------------------------
# 目标评价差距
# ---------------------------------------------------------------------------

def test_target_rank_annotates_gap_and_requirements():
    row = [r for r in select_with(records_ok(), target_rank=5)["rows"]
           if r["id"] == 1 and r["level"] == 4][0]
    assert row["targetRank"] == 5 and row["targetName"] == "粉雅"
    assert row["targetScore"] == 800_000          # 天井 100 万 × 80%
    assert row["reached"] is False
    assert row["gap"] == 150_000                  # 650000 → 800000
    assert row["okToGood"] == 120                 # ⌈2 × 150000 ÷ 2500⌉，基本点 = 100万/400
    assert row["rollsNeeded"] == 1500             # ⌈150000 ÷ 100⌉


def test_gap_max_excludes_already_reached_rows():
    result = select_with(records_ok(), target_rank=5, gap_max=200_000)
    assert all(row["reached"] is False for row in result["rows"])
    # 天竺2000(鬼) 999000 已达粉雅，天竺2000(里) 880000 也已达；只剩夏祭。
    assert titles(result) == ["1|4"]


def test_reached_filter_can_select_finished_songs():
    result = select_with(records_ok(), target_rank=5, reached="yes", limit=10)
    assert all(row["reached"] for row in result["rows"])
    assert "1|4" not in titles(result)


def test_top_rank_requires_all_good_and_rolls():
    row = [r for r in select_with(records_ok(), target_rank=8)["rows"]
           if r["id"] == 2 and r["level"] == 4][0]
    assert row["targetRequiresAllGood"] is True
    assert row["targetScore"] == 1_000_000        # 该谱精度曲：极 = 天井
    assert row["okToGood"] == 31                  # 必须把残留的「可」全部打成「良」
    assert row["rollsNeeded"] == 0                # 精度曲无需连打


# ---------------------------------------------------------------------------
# 排序与分页
# ---------------------------------------------------------------------------

def test_sort_desc_and_asc():
    assert titles(select(sort="rating", limit=10)) == ["2|4", "2|5", "1|4", "4|4"]
    assert titles(select(sort="rating", order="asc", limit=10)) == ["4|4", "1|4", "2|5", "2|4"]


def test_missing_sort_values_always_come_last():
    # 未游玩曲目没有 Rating；无论升降序都排在最后。
    assert titles(select(scope="all", sort="rating", limit=99))[-1] == "3|4"
    assert titles(select(scope="all", sort="rating", order="asc", limit=99))[-1] == "3|4"


def test_sort_aliases_and_unknown_key_fallback():
    assert sq.normalize_sort("精度") == "accuracy"
    assert sq.normalize_sort("分数") == "score"
    assert sq.normalize_sort("没见过的键") == "rating"


def test_limit_and_offset_paging():
    first = select(sort="rating", limit=2)
    second = select(sort="rating", limit=2, offset=2)
    assert first["shown"] == 2 and first["total"] == 4
    assert titles(first) + titles(second) == titles(select(sort="rating", limit=99))
    assert second["offset"] == 2


def test_limit_is_clamped_to_maximum():
    assert select(limit=9999)["limit"] == sq.MAX_LIMIT


# ---------------------------------------------------------------------------
# 条件描述
# ---------------------------------------------------------------------------

def test_describe_filters_lists_every_active_condition():
    result = select(query="天", match_mode="all", levels=(4,), constant_min=10.0,
                    rank_min=6, combo="no-miss", target_rank=6, gap_max=5000)
    text = "；".join(result["filterText"])
    for fragment in ("同时包含", "难度 4", "定数 10.0", "评价 紫雅~-", "零不可", "目标评价「紫雅」", "缺口 ≤5000"):
        assert fragment in text, fragment


def test_normalize_filters_rejects_unknown_scope_combo_and_match_mode():
    spec = sq.normalize_filters({"scope": "乱写", "combo": "乱写", "match_mode": "乱写"})
    assert spec["scope"] == "played"
    assert spec["combo"] == ""
    assert spec["match_mode"] == "乱写"      # 在 make_matcher 里才回退，便于提示


# ---------------------------------------------------------------------------
# /rtlink <评价> 简写与难度解析（需要 mock AstrBot）
# ---------------------------------------------------------------------------

import mock_astrbot as mock  # noqa: E402

mock.install()

import main  # noqa: E402


class FakeService:
    def __init__(self):
        self.improve_calls = []
        self.query_calls = []

    async def generate_rank_improve_image(self, qq, target=None, level=None):
        self.improve_calls.append((qq, target, level))
        return True, f"improve-{qq}-{target}-{level}.png"

    async def query_scores_text(self, qq, detail="brief", **filters):
        self.query_calls.append((qq, detail, filters))
        return "fake-query"

    async def score_sync_reminder_text(self, qq):
        return ""

    async def generate_help_image(self, qq):
        return True, "help.png"


class FakeEvent:
    def __init__(self, message, sender="10001"):
        self._message = message
        self._sender = sender

    def get_message_str(self):
        return self._message

    def get_sender_id(self):
        return self._sender

    def is_admin(self):
        return False

    def is_private_chat(self):
        return True

    def plain_result(self, text):
        return ("text", text)

    def image_result(self, path):
        return ("image", path)


def _plugin():
    plugin = main.RTLinkPlugin(main.Context({}))
    plugin.service = FakeService()
    return plugin


def _run(plugin, message):
    async def collect():
        return [item async for item in plugin.rtlink(FakeEvent(message), "")]
    return asyncio.run(collect())


@pytest.mark.parametrize("message,expected", [
    ("/rtlink 金雅", (4, None)),
    ("/rtlink 紫雅 鬼", (6, 4)),
    ("/rtlink improve 紫雅 里", (6, 5)),
    ("/rtlink 极+连打满", (8, None)),
    ("/rtlink 提升 银粹", (3, None)),
])
def test_rank_shorthand_dispatches_to_improve(message, expected):
    plugin = _plugin()
    result = _run(plugin, message)
    assert result and result[0][0] == "image"
    assert plugin.service.improve_calls[0][1:] == expected


def test_unknown_subcommand_still_reports_error():
    plugin = _plugin()
    result = _run(plugin, "/rtlink 这不是评价")
    assert result[0][0] == "text"
    assert "未知子指令" in result[0][1]


def test_bare_command_still_generates_report_image():
    plugin = _plugin()

    async def fake_report(qq):
        return True, "report.png"

    plugin.service.generate_report_image = fake_report
    assert _run(plugin, "/rtlink")[0] == ("image", "report.png")


@pytest.mark.parametrize("text,expected", [
    ("", None), ("鬼", (4,)), ("里", (5,)), ("4,5", (4, 5)), ("鬼 里", (4, 5)),
    ("鬼里", (4, 5)), ("45", (4, 5)), ("4/5", (4, 5)), ("oni", (4,)),
    ("松", None), ("乱写", None),
])
def test_parse_levels(text, expected):
    assert main.RTLinkPlugin._parse_levels(text) == expected
