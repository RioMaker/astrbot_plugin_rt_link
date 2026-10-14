# -*- coding: utf-8 -*-

import gzip
import json
from pathlib import Path

import pytest

from storage import DanCourseDataError, load_charts, load_dan_courses


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_dan_resource_is_complete_and_indexed():
    charts = load_charts(ROOT / "resource" / "charts.v1.json.gz")
    catalog = load_dan_courses(ROOT / "resource" / "dan_courses.v1.json.gz", charts)

    assert catalog["schema_version"] == 1
    assert catalog["data_version"] == "2026-10-14.1"
    # 2022–2026 五届日版/国际版 + 国服 2023/2024/2025，8 套完整课程 + 国服 2026 五级至十段
    assert len(catalog["courses"]) == 167
    assert sum(len(course["songs"]) for course in catalog["courses"]) == 501
    assert len(catalog["by_key"]) == 167

    statuses = [
        song["mapping_status"]
        for course in catalog["courses"]
        for song in course["songs"]
    ]
    # 原有 11 条缺曲记录 + 国服 2026 十段中的 2 条重复引用。
    assert statuses.count("not_in_chart_resource") == 13
    assert "unmapped" not in statuses


def test_song_mapping_prefers_matching_level_and_note_count():
    """同名曲目必须按难度 + 音符数收敛，不能只靠 ID 最小。"""
    charts = load_charts(ROOT / "resource" / "charts.v1.json.gz")
    catalog = load_dan_courses(ROOT / "resource" / "dan_courses.v1.json.gz", charts)
    by_id = {}
    for (song_no, level), chart in charts.items():
        by_id.setdefault(song_no, {})[level] = chart

    checked = 0
    for course in catalog["courses"]:
        for song in course["songs"]:
            if not song["song_no_candidates"]:
                continue
            best = by_id[song["song_no"]]
            if song["level"] not in best:
                continue
            # 主 ID 必须是「难度对得上且音符数对得上」的候选
            assert best[song["level"]]["totalNotes"] == song["total_notes"], song["title"]
            assert song["mapping_evidence"].startswith("title+level+notes"), song["title"]
            checked += 1
    assert checked >= 300

    # エンジェル ドリーム（鬼★8 / 765）：デレマス版（ID 153、694 音符）不能被选中
    course = catalog["by_key"][(2026, "jp_worldwide", "四段")]
    angel = next(song for song in course["songs"] if song["title"].startswith("エンジェル"))
    assert angel["song_no"] == 433
    assert angel["song_no_candidates"][0] == 433
    assert 153 in angel["song_no_candidates"]


def test_2026_courses_and_high_rank_openings():
    charts = load_charts(ROOT / "resource" / "charts.v1.json.gz")
    catalog = load_dan_courses(ROOT / "resource" / "dan_courses.v1.json.gz", charts)

    assert catalog["by_key"][(2026, "jp_worldwide", "五级")]["opens_at"] == "2026-06-06"
    assert catalog["by_key"][(2026, "jp_worldwide", "十段")]["opens_at"] == "2026-06-06"
    assert catalog["by_key"][(2026, "jp_worldwide", "玄人")]["opens_at"] == "2026-09-12"
    assert catalog["by_key"][(2026, "jp_worldwide", "达人")]["opens_at"] == "2026-09-12"
    assert catalog["by_key"][(2026, "jp_worldwide", "达人")]["closes_at"] is None
    assert catalog["by_key"][(2026, "cn", "十段")]["opens_at"] == "2026-10-14"
    assert (2026, "cn", "玄人") not in catalog["by_key"]
    assert (2026, "cn", "达人") not in catalog["by_key"]
    assert catalog["by_key"][(2025, "cn", "达人")]["closes_at"] == "2026-10-01"
    assert (
        catalog["by_key"][(2026, "cn", "十段")]["verification_status"]
        == "reference_cross_checked"
    )

    jp_2026 = [
        course
        for course in catalog["courses"]
        if course["year"] == 2026 and course["region"] == "jp_worldwide"
    ]
    assert len(jp_2026) == 19
    for course in jp_2026:
        assert course["region"] == "jp_worldwide"
        assert course["verification_status"] == "verified"
        assert "official_jp_2026" in course["source_ids"]

    # 十段逐曲条件：可 18/25/30 未满、连打 7/46/80 以上
    ten = catalog["by_key"][(2026, "jp_worldwide", "十段")]
    ok_cond = next(cond for cond in ten["conditions"] if cond["metric"] == "ok_count")
    roll_cond = next(cond for cond in ten["conditions"] if cond["metric"] == "drumroll_count")
    assert (ok_cond["scope"], ok_cond["normal"], ok_cond["gold"]) == ("per_song", [18, 25, 30], [13, 20, 23])
    assert (roll_cond["scope"], roll_cond["normal"], roll_cond["gold"]) == ("per_song", [7, 46, 80], [8, 51, 93])


def test_cn_overrides_and_song_reverse_index_are_available():
    charts = load_charts(ROOT / "resource" / "charts.v1.json.gz")
    catalog = load_dan_courses(ROOT / "resource" / "dan_courses.v1.json.gz", charts)

    cn_2023 = catalog["by_key"][(2023, "cn", "五级")]
    jp_2023 = catalog["by_key"][(2023, "jp_worldwide", "五级")]
    assert [song["title"] for song in cn_2023["songs"]] != [
        song["title"] for song in jp_2023["songs"]
    ]
    assert cn_2023["opens_at"] == "2024-07-18"
    assert catalog["by_key"][(2022, "jp_worldwide", "玄人")]["opens_at"] == "2022-09-19"
    assert catalog["by_key"][(2025, "jp_worldwide", "达人")]["opens_at"] == "2025-09-13"
    assert catalog["by_key"][(2025, "cn", "达人")]["opens_at"] == "2026-01-21"

    mapped_song = next(song for song in cn_2023["songs"] if song["song_no_candidates"])
    for song_no in mapped_song["song_no_candidates"]:
        assert any(ref["course"] is cn_2023 for ref in catalog["by_song"][song_no])


def test_loader_rejects_unknown_schema(tmp_path):
    path = tmp_path / "bad.json.gz"
    path.write_bytes(gzip.compress(json.dumps({"schema_version": 999}).encode("utf-8")))
    with pytest.raises(DanCourseDataError, match="不支持的段位资源版本"):
        load_dan_courses(path)
