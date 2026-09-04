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
    assert len(catalog["courses"]) == 133
    assert sum(len(course["songs"]) for course in catalog["courses"]) == 399
    assert len(catalog["by_key"]) == 133

    statuses = [
        song["mapping_status"]
        for course in catalog["courses"]
        for song in course["songs"]
    ]
    assert statuses.count("not_in_chart_resource") == 3
    assert "unmapped" not in statuses


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
