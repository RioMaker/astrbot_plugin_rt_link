# -*- coding: utf-8 -*-

from datetime import datetime
from pathlib import Path
import time

from PIL import Image

from profile_image import build_profile_data, render_profile_image
from rating import RHYTHM_RARE_CATALOG_COVERAGE, calculate_rhythm_ability
from service import _slim_result
from weakness_image import build_weakness_data, render_weakness_image


def _song(title, rating, level=4):
    return {
        "id": abs(hash(title)) % 100000,
        "title": title,
        "level": level,
        "rating": rating,
        "accuracy": .975,
        "constant": 10.0,
        "aiConstant": 10.2,
        "fullComboCount": 1,
        "dondafulComboCount": 0,
    }


def _analysis():
    family_scores = {
        "chartPower": 10.89,
        "sustainedEndurance": 12.04,
        "burstSpeed": 11.55,
        "hitPrecision": 10.68,
        "patternControl": 12.32,
        "timingAdaptation": 11.80,
        "visualReading": 11.83,
    }
    records = [_song("测试谱面一", 12.4), _song("测试谱面二", 12.1, 5), _song("测试谱面三", 11.9)]
    common = [
        {"key": "16-3|180_209", "pattern": "16-3", "bpmBand": "180_209", "score": 9.2, "charts": 8, "averageBpm": 194, "compoundRatio": .63, "catalogCharts": 349, "catalogCoverage": .2505, "rarity": "common", "best": records},
        {"key": "16-5|210_239", "pattern": "16-5", "bpmBand": "210_239", "score": 9.48, "charts": 6, "averageBpm": 224, "compoundRatio": .58, "catalogCharts": 81, "catalogCoverage": .0581, "rarity": "common", "best": []},
    ]
    rare = [
        {"key": "24-fish|gte240", "pattern": "24-fish", "bpmBand": "gte240", "score": 8.54, "charts": 3, "averageBpm": 252, "compoundRatio": .66, "catalogCharts": 7, "catalogCoverage": .005, "rarity": "rare", "best": []},
    ]
    return {
        "summary": {"rating": 9.86},
        "meta": {"playerId": "test-player", "server": "cn", "uniqueCharts": len(records)},
        "counts": {"belowThreshold": 0, "missing": 0},
        "records": records,
        "featureAbility": {
            "families": [{"key": key, "score": score, "charts": 10, "best": []} for key, score in family_scores.items()],
            "strengths": [], "weaknesses": [], "matchedCharts": len(records),
        },
        "rhythmAbility": {
            "cells": common + rare, "best": list(reversed(common)), "weakest": common,
            "rareWeakest": rare, "catalogCharts": 1393,
            "rareCatalogCoverageThreshold": RHYTHM_RARE_CATALOG_COVERAGE,
            "visual": {},
        },
        "ourTaikoV1": {"summary": {"rating": 9.5}, "chartCount": len(records)},
    }


def test_rhythm_ability_separates_catalog_rare_cells():
    common_key = ("16-3", "180_209")
    rare_key = ("32-fish", "210_239")
    catalog = []
    for index in range(100):
        cells = []
        if index < 10:
            cells.append({"pattern": common_key[0], "bpmBand": common_key[1], "noteRatio": .1})
        if index < 2:
            cells.append({"pattern": rare_key[0], "bpmBand": rare_key[1], "noteRatio": .1})
        catalog.append({"feature": {"rhythmProfile": {"cells": cells}}})
    records = []
    for index in range(4):
        records.append({
            "id": index, "level": 4, "title": f"谱面{index}", "rating": 9 + index * .1,
            "feature": {"rhythmProfile": {"cells": [
                {"pattern": common_key[0], "bpmBand": common_key[1], "noteRatio": .1, "averageBpm": 190},
                {"pattern": rare_key[0], "bpmBand": rare_key[1], "noteRatio": .1, "averageBpm": 220},
            ], "topArrangements": [], "arrangementCells": [], "visual": {}}},
        })
    result = calculate_rhythm_ability(records, catalog)
    assert [item["key"] for item in result["weakest"]] == ["16-3|180_209"]
    assert [item["key"] for item in result["rareWeakest"]] == ["32-fish|210_239"]
    assert result["weakest"][0]["catalogCoverage"] == .1
    assert result["rareWeakest"][0]["catalogCoverage"] == .02


def test_slim_result_keeps_rhythm_rarity_contract():
    slim = _slim_result(_analysis())
    rhythm = slim["rhythmAbility"]
    assert rhythm["catalogCharts"] == 1393
    assert rhythm["rareWeakest"][0]["rarity"] == "rare"
    assert rhythm["rareWeakest"][0]["catalogCoverage"] == .005


def test_profile_image_renders_approved_canvas(tmp_path: Path):
    analysis = _analysis()
    data = build_profile_data(analysis, datetime(2026, 9, 3))
    assert data["strongest"]["key"] == "patternControl"
    assert data["weakest"]["key"] == "hitPrecision"
    output = render_profile_image(analysis, str(tmp_path / "profile.png"), datetime(2026, 9, 3))
    with Image.open(output) as image:
        assert image.size == (1440, 2598)  # Sparse records use one card row, without blank BEST 20 rows.
        assert image.mode == "RGB"


def test_weakness_image_renders_common_and_rare_sections(tmp_path: Path):
    analysis = _analysis()
    data = build_weakness_data(analysis, datetime(2026, 9, 3))
    assert data["focus"]["key"] == "16-3|180_209"
    assert data["common"][0]["rarity"] == "common"
    assert data["rare"][0]["rarity"] == "rare"
    output = render_weakness_image(analysis, str(tmp_path / "weakness.png"), datetime(2026, 9, 3))
    with Image.open(output) as image:
        assert image.size == (1440, 2200)
        assert image.mode == "RGB"


def test_generated_image_pruning_is_scoped_and_retains_latest(tmp_path: Path):
    from service import MemoryBindingsStore, ScoreService

    service = ScoreService(MemoryBindingsStore(), lambda key: None)
    paths = []
    for index in range(5):
        path = tmp_path / f"profile_123_{index}.png"
        path.write_bytes(b"png")
        stamp = time.time_ns() + index
        path.touch()
        paths.append(path)
    unrelated = tmp_path / "weakness_123_0.png"
    unrelated.write_bytes(b"png")
    service._prune_analysis_images(tmp_path, "profile", "123", paths[-1], retain=3)
    remaining = [path.name for path in tmp_path.iterdir()]
    assert len([name for name in remaining if name.startswith("profile_123_")]) == 3
    assert paths[-1].name in remaining
    assert unrelated.name in remaining
