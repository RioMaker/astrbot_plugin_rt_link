# -*- coding: utf-8 -*-

import asyncio
import os
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

import mock_astrbot as mock  # noqa: E402

mock.install()

import main  # noqa: E402
from dan_query import (  # noqa: E402
    evaluate_player_dan_text, match_rank, match_region, query_dan_courses_text, split_level,
)
from service import MemoryBindingsStore, ScoreService  # noqa: E402
from song_alias import load_aliases  # noqa: E402
from storage import ScoreDatabase, load_charts, load_dan_courses  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]


def _catalog():
    charts = load_charts(ROOT / "resource" / "charts.v1.json.gz")
    return load_dan_courses(ROOT / "resource" / "dan_courses.v1.json.gz", charts)


def _aliases():
    charts = load_charts(ROOT / "resource" / "charts.v1.json.gz")
    return load_aliases(ROOT / "resource" / "aliases.v1.json.gz", charts)


def test_summary_and_exact_course_query():
    catalog = _catalog()
    summary = query_dan_courses_text(catalog)
    assert "2022, 2023, 2024, 2025" in summary
    assert "song_name 或 song_no" in summary

    result = query_dan_courses_text(catalog, year=2025, region="国服", rank="十段")
    assert "2025 中国大陆版 十段" in result
    assert "天狗囃子" in result
    assert "合格条件（普通 / 金）" in result
    assert "每曲" not in result
    assert "逐曲" in result
    assert "official_cn_2025" in result


def test_song_name_and_song_id_reverse_lookup():
    catalog = _catalog()
    by_name = query_dan_courses_text(catalog, song_name="天狗囃子")
    assert "2025 日版/国际版 十段" in by_name
    assert "2025 中国大陆版 十段" in by_name

    by_id = query_dan_courses_text(catalog, song_no=615, region="cn")
    assert "中国大陆版 十段" in by_id
    assert "日版/国际版" not in by_id

    canonical_region = query_dan_courses_text(
        catalog, year=2025, region="jp_worldwide", rank="十段"
    )
    assert "2025 日版/国际版 十段" in canonical_region


def test_llm_tool_is_registered_and_uses_public_catalog():
    plugin = object.__new__(main.RTLinkPlugin)
    plugin.dan_courses = _catalog()
    assert main.RTLinkPlugin.query_dan_course._llm_tool_name == "query_dan_course"
    result = asyncio.run(
        main.RTLinkPlugin.query_dan_course(
            plugin, None, year=2023, region="jp", rank="玄人"
        )
    )
    assert "2023 日版/国际版 玄人" in result
    assert "单曲历史成绩只能作为段位能力参考" in result


def test_invalid_region_returns_actionable_message():
    result = query_dan_courses_text(_catalog(), region="mars", rank="十段")
    assert "区域参数无法识别" in result


# ---------------------------------------------------------------------------
# 曲名 / 别名匹配
# ---------------------------------------------------------------------------

def test_course_listing_shows_cn_and_jp_names_with_ids():
    result = query_dan_courses_text(_catalog(), year=2025, region="cn", rank="十段",
                                    alias_data=_aliases())
    assert "《天狗配乐》（天狗囃子）" in result
    assert "ID 615" in result
    assert "鬼★9" in result


def test_alias_lookup_finds_dan_appearances():
    """「六天」这种简称既不是国服名也不是日文名，靠别名表才能命中。"""
    result = query_dan_courses_text(_catalog(), song_name="六天", alias_data=_aliases())
    assert "2024 中国大陆版 达人" in result
    assert "2024 日版/国际版 达人" in result
    assert "第六天魔王" in result and "ID 765" in result


def test_romaji_and_jp_names_match_the_same_song():
    catalog, aliases = _catalog(), _aliases()
    for query in ("天狗囃子", "天狗配乐", "Tengu Bayashi"):
        result = query_dan_courses_text(catalog, song_name=query, alias_data=aliases)
        assert "十段" in result, query


def test_song_not_in_dan_reports_candidates_instead_of_blank_miss():
    """曲目存在但没进过段位时，要说明是「没有出现记录」而不是「没找到这首歌」。"""
    result = query_dan_courses_text(_catalog(), song_name="北埼玉", alias_data=_aliases())
    assert "没有找到符合条件的段位资料" in result
    assert "338" in result and "没有出现记录" in result
    assert "/rtlink alias" in result


def test_level_prefix_filters_the_song_lookup():
    catalog, aliases = _catalog(), _aliases()
    plain = query_dan_courses_text(catalog, song_name="第六天魔王", alias_data=aliases)
    filtered = query_dan_courses_text(catalog, song_name="里 第六天魔王", alias_data=aliases)
    other = query_dan_courses_text(catalog, song_name="鬼 第六天魔王", alias_data=aliases)
    assert "达人" in plain
    assert "达人" in filtered
    assert "没有找到" in other


@pytest.mark.parametrize("text,expected", [
    ("十段", "十段"), ("10段", ""), ("玄人", "玄人"), ("達人", "达人"), ("初段", "初段"),
])
def test_match_rank_normalizes(text, expected):
    assert match_rank(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("cn", "cn"), ("国服", "cn"), ("中國大陸", "cn"), ("jp", "jp_worldwide"), ("国际版", "jp_worldwide"),
])
def test_match_region_normalizes(text, expected):
    assert match_region(text) == expected


@pytest.mark.parametrize("text,level,name", [
    ("鬼 天竺2000", 4, "天竺2000"),
    ("里：きたさいたま2000", 5, "きたさいたま2000"),
    ("天竺2000", None, "天竺2000"),
    ("玄人 天竺2000", None, "玄人 天竺2000"),
])
def test_split_level_parses_difficulty_prefix(text, level, name):
    assert split_level(text) == (level, name)


def test_player_dan_evaluation_uses_actual_judgements_and_drumrolls():
    catalog = _catalog()
    course = catalog["by_key"][(2025, "cn", "十段")]
    scores = []
    drumrolls = [40, 260, 40]
    for song, pound in zip(course["songs"], drumrolls):
        scores.append({
            "song_no": song["song_no"], "level": song["level"], "source": "hiroba",
            "good_cnt": song["total_notes"], "ok_cnt": 0, "ng_cnt": 0,
            "pound_cnt": pound, "combo_cnt": song["total_notes"],
            "high_score": 1000000, "best_score_rank": 8,
            "update_datetime": "2026-09-04 12:00:00",
        })
    result = evaluate_player_dan_text(catalog, scores, 2025, "cn", "十段")
    assert "良 734 / 可 0 / 不可 0 / 连打 40" in result
    assert "各曲最佳记录满足目前可计算的金合格条件" in result
    assert "魂槽" in result and "无法核对" in result
    assert "不能据此断言已经过段" in result

    scores[0]["pound_cnt"] = None
    incomplete = evaluate_player_dan_text(catalog, scores, 2025, "cn", "十段")
    assert "部分良/可/不可或连打字段缺失" in incomplete


@pytest.mark.parametrize("text,year,region,rank,song", [
    ("2025 十段", 2025, "", "十段", ""),
    ("十段 国服", 0, "国服", "十段", ""),
    ("2024 日版 达人", 2024, "日版", "达人", ""),
    ("六天", 0, "", "", "六天"),
    ("鬼 天狗囃子", 0, "", "", "鬼 天狗囃子"),
    ("2025 国服 十段 天狗", 2025, "国服", "十段", "天狗"),
    ("", 0, "", "", ""),
])
def test_parse_dan_args(text, year, region, rank, song):
    args = main.RTLinkPlugin._parse_dan_args(text)
    assert (args["year"], args["region"], args["rank"], args["song_name"]) == (year, region, rank, song)


def test_dan_command_dispatches_and_uses_alias_catalog():
    """/rtlink dan 与 /rtlink 段位 都走同一套查询，并带上内置别名。"""
    plugin = object.__new__(main.RTLinkPlugin)
    plugin.dan_courses = _catalog()
    plugin.aliases = _aliases()
    event = mock.AstrMessageEvent(
        "10001", private=False, is_admin=False, message_str="rtlink dan 2025 cn 十段"
    )
    results = asyncio.run(_collect(plugin.dan_cmd(event)))
    assert len(results) == 1
    assert "2025 中国大陆版 十段" in results[0]
    assert "《天狗配乐》（天狗囃子）" in results[0]

    chinese = mock.AstrMessageEvent(
        "10001", private=False, is_admin=False, message_str="rtlink 段位 六天"
    )
    results = asyncio.run(_collect(plugin.dan_cmd(chinese)))
    assert "2024 中国大陆版 达人" in results[0]


async def _collect(agen):
    return [item async for item in agen]


def test_player_dan_llm_tool_is_registered():
    assert main.RTLinkPlugin.evaluate_player_dan._llm_tool_name == "evaluate_player_dan"

    class FakeDanService:
        async def get_player_dan_capability_text(self, qq, catalog, year, region, rank):
            return f"{qq}:{year}:{region}:{rank}:{catalog['data_version']}"

    plugin = object.__new__(main.RTLinkPlugin)
    plugin.service = FakeDanService()
    plugin.dan_courses = _catalog()
    event = mock.AstrMessageEvent("10001", private=True, is_admin=False, message_str="")
    result = asyncio.run(
        main.RTLinkPlugin.evaluate_player_dan(plugin, event, 2025, "十段", "cn")
    )
    assert result.startswith("10001:2025:cn:十段:")


def test_low_level_player_can_be_evaluated_even_when_rating_is_unavailable(tmp_path):
    catalog = _catalog()
    db = ScoreDatabase(tmp_path / "low-level.db")
    store = MemoryBindingsStore({
        "10001": {"apikey": "tk_test", "player_id": "game1", "server": "cn"}
    })
    service = ScoreService(store, lambda _key: None, charts={}, score_db=db)
    course = catalog["by_key"][(2023, "cn", "五级")]
    rows = []
    for song in course["songs"]:
        rows.append({
            "id": song["song_no"], "level": song["level"],
            "good_cnt": song["total_notes"], "ok_cnt": 0, "ng_cnt": 0,
            "pound_cnt": 100, "combo_cnt": song["total_notes"],
            "high_score": 900000, "best_score_rank": 4, "raw": {},
        })
    db.replace_scores("10001", "hiroba", rows, game_player_id="game1", server="cn")
    db.kv_set("score_storage_schema:10001", {
        "schema": 2, "playerId": "game1", "server": "cn"
    })

    async def rating_unavailable(_qq):
        return None, "该账号暂无鬼/里谱面成绩，无法评级。"

    service._get_analysis = rating_unavailable
    try:
        result = asyncio.run(
            service.get_player_dan_capability_text(
                "10001", catalog, 2023, "cn", "五级"
            )
        )
        assert "2023 中国大陆版 五级" in result
        assert "各曲最佳记录满足目前可计算的金合格条件" in result
    finally:
        db.close()
