# -*- coding: utf-8 -*-
"""Rating 历史快照与手动更新回归测试。"""

import asyncio
import os
import sys
from pathlib import Path

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

import service as service_mod  # noqa: E402
from service import (  # noqa: E402
    CATALOG_SCHEMA_VERSION,
    CATALOG_VERSION,
    RATING_ALGORITHM_VERSION,
    RATING_HISTORY_SCHEMA,
    MemoryBindingsStore,
    ScoreService,
    _history_snapshot,
)
from storage import ScoreDatabase  # noqa: E402


def _analysis():
    return {
        "summary": {
            "rating": 8.75,
            "fundamental": 8.4,
            "stamina": 8.2,
            "speed": 8.1,
            "accuracy": 9.0,
            "pattern": 7.9,
            "rhythm": 8.3,
            "reading": 8.6,
        },
        "meta": {"playerId": "30053354", "server": "cn"},
        "counts": {"rated": 2},
        "records": [{"id": 1}, {"id": 2}],
        "featureAbility": {
            "families": [
                {"key": "stream", "score": 8.1, "charts": 9, "exposure": 0.7, "best": []}
            ]
        },
        "rhythmAbility": {
            "cells": [
                {
                    "key": "triplet|180-209",
                    "pattern": "triplet",
                    "bpmBand": "180-209",
                    "score": 7.8,
                    "charts": 8,
                    "catalogCharts": 70,
                    "catalogCoverage": 0.05,
                    "rarity": "common",
                },
                {
                    "key": "compound|240+",
                    "pattern": "compound",
                    "bpmBand": "240+",
                    "score": 7.2,
                    "charts": 3,
                    "catalogCharts": 12,
                    "catalogCoverage": 0.008,
                    "rarity": "rare",
                },
            ],
            "rareCatalogCoverageThreshold": 0.03,
        },
    }


def test_snapshot_persists_all_common_and_rare_cells(tmp_path):
    db_path = tmp_path / "rt_link.db"
    snapshot = _history_snapshot(_analysis())
    db = ScoreDatabase(db_path)
    db.add_rating_snapshot("10001", "rating_image", snapshot, "2026-09-01T00:00:00+00:00")
    db.close()

    reopened = ScoreDatabase(db_path)
    rows = reopened.get_rating_snapshots("10001")
    stats = reopened.storage_stats()
    reopened.close()

    assert len(rows) == 1
    assert rows[0]["game_player_id"] == "30053354"
    assert rows[0]["trigger"] == "rating_image"
    assert [cell["rarity"] for cell in rows[0]["payload"]["rhythmCells"]] == [
        "common",
        "rare",
    ]
    assert rows[0]["payload"]["summary"]["pattern"] == 7.9
    assert rows[0]["payload"]["algorithmVersion"] == RATING_ALGORITHM_VERSION
    assert rows[0]["payload"]["schema"] == RATING_HISTORY_SCHEMA == 2
    assert rows[0]["payload"]["catalogVersion"] == CATALOG_VERSION
    assert rows[0]["payload"]["catalogSchemaVersion"] == CATALOG_SCHEMA_VERSION
    assert stats["snapshot_count"] == 1


def test_recent_snapshot_limit_keeps_chronological_order(tmp_path):
    db = ScoreDatabase(tmp_path / "rt_link.db")
    for day in range(1, 5):
        payload = _history_snapshot(_analysis())
        payload["summary"]["rating"] = 8 + day / 10
        db.add_rating_snapshot(
            "10001", "update", payload, f"2026-09-0{day}T00:00:00+00:00"
        )
    rows = db.get_rating_snapshots("10001", limit=2)
    db.close()
    assert [row["payload"]["summary"]["rating"] for row in rows] == [8.3, 8.4]


def test_force_update_and_rating_image_each_append_snapshot(tmp_path):
    async def run():
        db = ScoreDatabase(tmp_path / "rt_link.db")
        svc = ScoreService(
            MemoryBindingsStore({"10001": {"apikey": "tk_test", "player_id": "30053354"}}),
            client_factory=lambda _key: None,
            score_db=db,
            report_dir=str(tmp_path),
        )

        async def fake_sync(_qq):
            return True, "", _analysis()

        async def fake_get_analysis(_qq):
            return _analysis(), ""

        svc._sync = fake_sync
        svc._get_analysis = fake_get_analysis
        original_renderer = service_mod.render_report_image
        service_mod.render_report_image = (
            lambda _analysis_data, path: Path(path).write_bytes(b"PNG")
        )
        try:
            ok, message = await svc.force_update("10001")
            image_ok, _path = await svc.generate_report_image("10001")
            rows = db.get_rating_snapshots("10001")
        finally:
            service_mod.render_report_image = original_renderer
            db.close()
        assert ok and image_ok
        assert "历史快照已记录" in message
        assert [row["trigger"] for row in rows] == ["update", "rating_image"]

    asyncio.run(run())
