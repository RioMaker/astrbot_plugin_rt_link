"""The fixed chart constant is a difficulty input, not the player's Rating cap."""

import math

import pytest

from profile_data import build_profile_data
from profile_image import card_rating_ceiling, grade_ratio
from rating import CONSTANT_TO_X, calc_rating, calc_y, calculate_ai_values


def test_fixed_constant_maps_to_a_different_rating_scale():
    assert calc_y(1.0) == pytest.approx(15.5)
    assert calc_rating(10.0, 1.0) == pytest.approx(10.6502999769)
    assert calc_rating(11.1, 1.0) == pytest.approx(13.8320848878)
    chart = {"totalNotes": 1000, "feature": {"aiConstant": 11.1, "specializations": {}}}
    low = calculate_ai_values(chart, {"goodCount": 900, "okCount": 100, "ngCount": 0})
    high = calculate_ai_values(chart, {"goodCount": 1000, "okCount": 0, "ngCount": 0})
    assert low["constant"] == high["constant"] == 11.1
    assert low["rating"] > 11.1
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


def test_above_constant_is_not_colored_as_full_rating():
    row = {"aiConstant": 11.1, "rating": 11.54001861558463}
    ceiling = card_rating_ceiling(row)
    assert ceiling == pytest.approx(13.8320848878)
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
        "rating": 11.54001861558463,
        "accuracy": 0.956460674,
        "highScore": 957080,
    }
    profile_image.card(image, row, 1, 0, 0)
    assert seen["11.54"] < 8
    assert (
        "11.1" not in seen
    )  # Difficulty is a plain, fixed value, not a performance badge.
