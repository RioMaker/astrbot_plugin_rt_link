"""Aggregate update badges use isolated, persistent and comparable baselines."""

import copy

import pytest
from PIL import Image, ImageDraw

from profile_data import BANDS, add_profile_rating_changes, profile_rating_baseline
from profile_image import render_configuration_image, render_profile_image
from rating import FAMILIES
from report_image import draw_delta_badge
from storage import ScoreDatabase


def analysis():
    return {
        "meta": {"playerId": "p1", "server": "cn"},
        "profileSource": "hiroba",
        "ratingAlgorithmVersion": "r2",
        "profileRating": 9.12345,
        "summary": {"rating": 9.12},
        "records": [
            {
                "id": 1,
                "level": 4,
                "title": "Preview",
                "rating": 8,
                "aiConstant": 10,
                "accuracy": 0.98,
                "highScore": 900000,
            }
        ],
        "profileScoreRows": [{"id": 1, "level": 4, "highScore": 900000}],
        "featureAbility": {
            "families": [
                {"key": key, "score": 8 + i * 0.1, "charts": 4, "best": []}
                for i, key in enumerate(FAMILIES)
            ]
        },
        "profileConfigurations": {
            "available": True,
            "version": "v1",
            "resourceHash": "h1",
            "algorithmVersion": "config-r2",
            "bands": BANDS,
            "cells": [
                {
                    "key": "16-3|normal",
                    "score": 4.0,
                    "ceiling": 10,
                    "playerSamples": 4,
                    "catalogSamples": 100,
                },
                {
                    "key": "16-4|normal",
                    "score": None,
                    "ceiling": 10,
                    "playerSamples": 0,
                    "catalogSamples": 100,
                },
            ],
        },
    }


def updated():
    old = analysis()
    new = copy.deepcopy(old)
    new["profileRating"] = 9.22345
    new["summary"]["rating"] = 9.22
    new["records"][0]["rating"] = 8.1
    for i, row in enumerate(new["featureAbility"]["families"]):
        row["score"] += 0.12 if i % 2 else -0.08
    new["profileConfigurations"]["cells"][0]["score"] = 4.12
    new["profileConfigurations"]["cells"][1]["score"] = 3
    changes = add_profile_rating_changes({"baseline": True, "items": []}, old, new)
    new["profileSyncChanges"] = changes
    return old, new, changes


def test_metric_deltas_have_correct_sign_and_ignore_new_samples():
    old, _new, changes = updated()
    delta = changes["metricDeltas"]
    assert delta["rating"] == 0.1
    assert len(delta["abilities"]) == 7
    assert delta["abilities"][FAMILIES[0]] == -0.08
    assert delta["abilities"][FAMILIES[1]] == 0.12
    assert delta["configurations"] == {"16-3|normal": 0.12}
    same = add_profile_rating_changes({"baseline": True, "items": []}, old, old)[
        "metricDeltas"
    ]
    assert same == {"rating": None, "abilities": {}, "configurations": {}}


def test_compact_baseline_survives_database_reopen(tmp_path):
    old, new, expected = updated()
    path = tmp_path / "scores.db"
    with_db = ScoreDatabase(path)
    with_db.kv_set("baseline", profile_rating_baseline(old))
    with_db.close()
    reopened = ScoreDatabase(path)
    try:
        baseline = reopened.kv_get("baseline")
        actual = add_profile_rating_changes(
            {"baseline": True, "items": []}, baseline, new
        )
        assert actual["metricDeltas"] == expected["metricDeltas"]
        assert "featureAbility" not in baseline
        assert len(baseline["profileSummary"]["abilities"]) == 7
    finally:
        reopened.close()


@pytest.mark.parametrize("field", ["version", "resourceHash", "algorithmVersion"])
def test_configuration_version_changes_suppress_config_badges(field):
    old, new, _ = updated()
    new["profileConfigurations"][field] = "different"
    delta = add_profile_rating_changes({"baseline": True, "items": []}, old, new)[
        "metricDeltas"
    ]
    assert delta["configurations"] == {}
    assert delta["rating"] == 0.1 and len(delta["abilities"]) == 7


def test_identity_model_and_insufficient_samples_do_not_show_false_growth():
    old, new, _ = updated()
    new["meta"]["playerId"] = "other"
    assert "metricDeltas" not in add_profile_rating_changes(
        {"baseline": True, "items": []}, old, new
    )
    new["meta"]["playerId"] = "p1"
    new["ratingAlgorithmVersion"] = "new-model"
    assert "metricDeltas" not in add_profile_rating_changes(
        {"baseline": True, "items": []}, old, new
    )
    new["ratingAlgorithmVersion"] = "r2"
    old["featureAbility"]["families"][0]["charts"] = 2
    old["profileRating"] = None
    delta = add_profile_rating_changes({"baseline": True, "items": []}, old, new)[
        "metricDeltas"
    ]
    assert delta["rating"] is None and FAMILIES[0] not in delta["abilities"]


def test_badge_geometry_and_zero_hiding():
    draw = ImageDraw.Draw(Image.new("RGB", (600, 100), "white"))
    for value in (None, 0, 0.004, float("nan")):
        assert draw_delta_badge(draw, value, 20, 20) is None
    for value in (0.01, -0.01, 13.41, -13.41):
        bounds = draw_delta_badge(draw, value, 180, 10, size=11, align="right")
        assert 120 <= bounds[0] < bounds[2] == 180
        assert bounds[1] == 10 and bounds[3] == 29


def test_all_requested_profile_regions_render_update_badges(tmp_path, monkeypatch):
    import profile_image
    import report_image

    _, new, _ = updated()
    original = draw_delta_badge
    calls = []
    labels = []

    def capture(draw, delta, x, y, size=14, dark=False, align="left"):
        result = original(draw, delta, x, y, size, dark, align)
        if result:
            calls.append((delta, x, y, size))
        return result

    original_text = profile_image.txt

    def text_capture(d, value, *args, **kwargs):
        labels.append(str(value))
        return original_text(d, value, *args, **kwargs)

    monkeypatch.setattr(profile_image, "draw_delta_badge", capture)
    monkeypatch.setattr(report_image, "draw_delta_badge", capture)
    monkeypatch.setattr(profile_image, "txt", text_capture)
    before = copy.deepcopy(new)
    render_profile_image(new, tmp_path / "profile.png")
    assert new == before
    assert any(v == 0.1 and y == 268 for v, x, y, size in calls)
    assert any(v == 0.1 and x == 414 and y == 883 for v, x, y, size in calls)
    assert len([c for c in calls if c[1] == 1167]) == 7
    assert any(size == 11 and 1390 < y < 1892 for v, x, y, size in calls)
    assert not any("全良上限" in label for label in labels)
    calls.clear()
    render_configuration_image(new, tmp_path / "progress.png")
    assert any(v == 0.12 and size == 12 for v, x, y, size in calls)
