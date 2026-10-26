"""R2 nonlinear player Rating is bounded by the fixed chart constant."""

import math
from itertools import pairwise

import pytest

from profile_data import build_profile_data
from profile_image import card_rating_ceiling, card_rating_text, grade_ratio
from rating import (
    CONSTANT_TO_X,
    calc_rating,
    calc_reference_rating,
    calc_y,
    calculate_ai_values,
)


def test_reference_curve_is_preserved_and_ai_rating_caps_at_constant():
    assert calc_y(1.0) == pytest.approx(15.5)
    assert calc_reference_rating(10.0, 1.0) == pytest.approx(10.6502999769)
    assert calc_rating(10.0, 1.0) == 10.0
    assert calc_reference_rating(11.1, 1.0) == pytest.approx(13.8320848878)
    assert calc_rating(11.1, 1.0) == 11.1
    chart = {"totalNotes": 1000, "feature": {"aiConstant": 11.1, "specializations": {}}}
    low = calculate_ai_values(chart, {"goodCount": 900, "okCount": 100, "ngCount": 0})
    high = calculate_ai_values(chart, {"goodCount": 1000, "okCount": 0, "ngCount": 0})
    assert low["constant"] == high["constant"] == 11.1
    assert low["rating"] < 11.1
    assert high["rating"] > low["rating"]


def test_legal_constant_accuracy_grid_stays_below_full_good_ceiling():
    for constant, _ in CONSTANT_TO_X:
        ceiling = calc_rating(constant, 1.0)
        previous = -1.0
        for i in range(1001):
            value = calc_rating(constant, 0.75 + i / 4000)
            assert math.isfinite(value) and 0 <= value <= 15.5 + 1e-9
            assert value <= ceiling + 1e-9
            assert value >= previous - 1e-9
            previous = value


def test_below_constant_is_not_colored_as_full_rating():
    row = {"aiConstant": 11.1, "rating": 9.260657932020216}
    ceiling = card_rating_ceiling(row)
    assert ceiling == 11.1
    assert grade_ratio(row["rating"], ceiling) < 8
    assert grade_ratio(ceiling, ceiling) == 8
    assert card_rating_ceiling({"aiConstant": None}) is None


def test_old_cache_constant_only_annotations_are_removed():
    analysis = {
        "records": [],
        "profileSyncChanges": {
            "baseline": True,
            "items": [
                {
                    "id": 1,
                    "level": 4,
                    "delta": 0,
                    "constantDelta": 0.2,
                    "previousConstant": 10,
                    "aiConstant": 10.2,
                },
                {
                    "id": 2,
                    "level": 4,
                    "delta": 0,
                    "ratingDelta": 0.1,
                    "constantDelta": 0.2,
                },
            ],
        },
    }
    data = build_profile_data(analysis)
    items = data["analysis"]["profileSyncChanges"]["items"]
    assert len(items) == 1 and items[0]["id"] == 2
    assert "constantDelta" not in items[0]
    assert len(analysis["profileSyncChanges"]["items"]) == 2


def test_card_uses_theoretical_rating_for_color(monkeypatch):
    from PIL import Image

    import profile_image

    seen = {}
    original = profile_image.colored_text

    def capture(im, text, x, y, size, rank, align="left"):
        seen[text] = rank
        return original(im, text, x, y, size, rank, align)

    monkeypatch.setattr(profile_image, "colored_text", capture)
    image = Image.new("RGBA", (420, 276), "white")
    row = {
        "id": 1,
        "level": 4,
        "title": "Above difficulty constant",
        "aiConstant": 11.1,
        "rating": 9.260657932020216,
        "accuracy": 0.956460674,
        "highScore": 957080,
    }
    profile_image.card(image, row, 1, 0, 0)
    assert seen["9.26"] < 8
    assert (
        "11.1" not in seen
    )  # Difficulty is a plain, fixed value, not a performance badge.


def test_bounded_curve_is_monotone_in_difficulty_and_only_full_good_reaches_cap():
    previous = [-1.0] * len(CONSTANT_TO_X)
    for step in range(1001):
        accuracy = 0.75 + step / 4000
        values = [calc_rating(c, accuracy) for c, _ in CONSTANT_TO_X]
        assert all(a <= b + 1e-9 for a, b in pairwise(values))
        for index, ((constant, _), value) in enumerate(zip(CONSTANT_TO_X, values)):
            assert previous[index] <= value + 1e-9
            assert value <= constant
            assert (value == constant) == (accuracy == 1)
        previous = values
    assert calc_rating(6, 0.95) / 6 != pytest.approx(calc_rating(11.1, 0.95) / 11.1)
    assert calc_rating(10, 0.875) != pytest.approx(
        (calc_rating(10, 0.75) + calc_rating(10, 1)) / 2
    )
    for constant, _ in CONSTANT_TO_X:
        assert calc_rating(constant, math.nextafter(1.0, 0.0)) < constant
    with pytest.raises(ValueError):
        calc_rating(10, 1.01)


def test_nonperfect_display_does_not_round_up_to_full_good():
    row = {"aiConstant": 10, "accuracy": 0.999999, "rating": 9.99999}
    assert card_rating_text(row) == "9.99"
    row.update(accuracy=1, rating=10)
    assert card_rating_text(row) == "10.00"


def test_ourtaiko_reference_calculation_is_unchanged():
    from rating import calculate_values

    chart = {
        "totalNotes": 1000,
        "public": {
            "constant": 10,
            "avgDensity": 50,
            "instDensity": 60,
            "separation": 10,
            "bpmChange": 5,
            "composite": 20,
        },
    }
    score = {"goodCount": 1000, "okCount": 0, "ngCount": 0}
    assert calculate_values(chart, score)["rating"] == calc_reference_rating(10, 1)
    assert calculate_values(chart, score)["rating"] > 10


def test_configuration_resource_rejects_different_rating_algorithm(tmp_path):
    import gzip
    import json

    from profile_data import RESOURCE, load_configuration_catalog
    from storage import load_charts

    payload = json.loads(gzip.decompress(RESOURCE.read_bytes()))
    payload["algorithmVersion"] = "previous-model"
    path = tmp_path / "old-config.json.gz"
    path.write_bytes(gzip.compress(json.dumps(payload).encode("utf-8")))
    result = load_configuration_catalog(load_charts("resource/charts.v1.json.gz"), path)
    assert not result["available"]
