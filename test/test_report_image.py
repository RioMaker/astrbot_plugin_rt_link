# -*- coding: utf-8 -*-

from pathlib import Path

from PIL import Image, ImageDraw

from report_image import _lines, build_report_data, render_report_image
from service import RATING_CACHE_SCHEMA, _slim_result, _slim_song


def test_slim_evidence_keeps_image_metrics():
    row = {
        "id": 101,
        "level": 4,
        "title": "证据谱面",
        "rating": 10.25,
        "accuracy": 0.9876,
        "constant": 10.1,
        "aiConstant": 10.3,
    }
    slim = _slim_song(row)
    assert slim["accuracy"] == 0.9876
    assert slim["constant"] == 10.1
    assert slim["aiConstant"] == 10.3


def test_slim_result_marks_current_cache_schema():
    result = {
        "summary": {"rating": 10},
        "ourTaikoV1": {"summary": {"rating": 9.8}, "chartCount": 1},
        "counts": {},
        "meta": {},
        "records": [],
        "featureAbility": {"families": [], "strengths": [], "weaknesses": [], "matchedCharts": 0},
        "rhythmAbility": {"cells": [], "best": [], "weakest": [], "visual": {}},
    }
    assert _slim_result(result)["_cacheSchema"] == RATING_CACHE_SCHEMA


def test_chinese_punctuation_does_not_start_a_wrapped_line():
    image = Image.new("RGB", (400, 200), "white")
    lines = _lines(
        ImageDraw.Draw(image),
        "选择已经稳定通过的同类谱面，把目标改为减少可，保持落点一致。",
        180,
        15,
    )
    assert not any(line.startswith(tuple("，。；：！？、）」》】〕〉”’…")) for line in lines)


def test_report_image_keeps_template_sections_in_bounds(tmp_path: Path):
    analysis = {
        "summary": {"rating": 9.86},
        "featureAbility": {
            "families": [
                {"key": key, "score": score, "charts": 10}
                for key, score in (
                    ("chartPower", 10.89), ("sustainedEndurance", 12.04),
                    ("burstSpeed", 11.55), ("hitPrecision", 10.68),
                    ("patternControl", 12.32), ("timingAdaptation", 11.8),
                    ("visualReading", 11.83),
                )
            ],
            "strengths": [{"key": "patternControl", "score": 12.32}],
            "weaknesses": [{"key": "hitPrecision", "score": 10.68}],
            "matchedCharts": 10,
        },
        "meta": {"playerId": "test", "server": "cn", "uniqueCharts": 1},
        "counts": {"belowThreshold": 0, "missing": 0},
        "records": [{"title": "Test", "level": 4, "constant": 10, "accuracy": 0.99, "rating": 10}],
        "ourTaikoV1": {"summary": {"rating": 9.5}},
        "rhythmAbility": {
            "best": [],
            "weakest": [{"pattern": "16-3", "bpmBand": "180_209", "score": 9.2, "charts": 4, "averageBpm": 190, "best": []}],
            "visual": {},
        },
    }
    output = render_report_image(analysis, str(tmp_path / "report.png"))
    assert Path(output).is_file()
    assert Path(output).stat().st_size > 10_000
    with Image.open(output) as image:
        assert image.size == (1440, 2400)
        assert image.mode == "RGB"


def test_report_summary_matches_website_contract():
    analysis = {
        "summary": {"rating": 9.86},
        "featureAbility": {
            "matchedCharts": 7,
            "families": [
                {"key": key, "score": score, "charts": 7, "best": []}
                for key, score in (
                    ("chartPower", 10.89), ("sustainedEndurance", 12.04),
                    ("burstSpeed", 11.55), ("hitPrecision", 10.68),
                    ("patternControl", 12.32), ("timingAdaptation", 11.8),
                    ("visualReading", 11.83),
                )
            ],
        },
        "meta": {"playerId": "30053354", "server": "cn", "uniqueCharts": 7},
        "counts": {"belowThreshold": 1, "missing": 2},
        "records": [],
        "ourTaikoV1": {"summary": {"rating": 9.5}},
        "rhythmAbility": {"best": [], "weakest": [], "visual": {}},
    }
    data = build_report_data(analysis)
    assert data["headline"] == "复合控制最突出，精度兑现是当前突破口"
    assert data["center"] == 11.8
    assert data["metrics"][3]["value"] == "3"
    assert [planet["rank"] for planet in data["planets"]] == [6, 2, 5, 7, 1, 4, 3]
