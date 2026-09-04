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
from dan_query import query_dan_courses_text  # noqa: E402
from storage import load_charts, load_dan_courses  # noqa: E402


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
