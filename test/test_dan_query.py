# -*- coding: utf-8 -*-

import asyncio
import os
import sys
from pathlib import Path

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

import mock_astrbot as mock  # noqa: E402

mock.install()

import main  # noqa: E402
from dan_query import evaluate_player_dan_text, query_dan_courses_text  # noqa: E402
from service import MemoryBindingsStore, ScoreService  # noqa: E402
from storage import ScoreDatabase, load_charts, load_dan_courses  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]


def _catalog():
    charts = load_charts(ROOT / "resource" / "charts.v1.json.gz")
    return load_dan_courses(ROOT / "resource" / "dan_courses.v1.json.gz", charts)


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
