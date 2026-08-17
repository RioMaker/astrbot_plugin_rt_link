# -*- coding: utf-8 -*-

from pathlib import Path

from report_image import render_report_image


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
        },
        "meta": {"playerId": "test", "server": "cn", "uniqueCharts": 1},
        "counts": {"belowThreshold": 0, "missing": 0},
        "records": [{"title": "Test", "level": 4, "constant": 10, "accuracy": 0.99, "rating": 10}],
        "ourTaikoV1": {"summary": {"rating": 9.5}},
    }
    output = render_report_image(analysis, str(tmp_path / "report.png"))
    assert Path(output).is_file()
    assert Path(output).stat().st_size > 10_000
