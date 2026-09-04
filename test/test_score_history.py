# -*- coding: utf-8 -*-

import sqlite3
from pathlib import Path

from rating import normalize_scores
from service import MemoryBindingsStore, ScoreService
from storage import ScoreDatabase


def _row(score=900000, ok=10):
    raw = {
        "song_no": 10, "level": 2, "good_cnt": 200, "ok_cnt": ok,
        "ng_cnt": 1, "pound_cnt": 30, "combo_cnt": 180, "stage_cnt": 5,
        "clear_cnt": 3, "full_combo_cnt": 0, "dondaful_combo_cnt": 0,
        "high_score": score, "best_score_rank": 4,
        "highscore_datetime": "2026-09-01 12:00:00",
        "update_datetime": "2026-09-01 12:00:00",
    }
    return {
        "id": 10, "level": 2, "good_cnt": 200, "ok_cnt": ok, "ng_cnt": 1,
        "pound_cnt": 30, "combo_cnt": 180, "stage_cnt": 5, "clear_cnt": 3,
        "full_combo_cnt": 0, "dondaful_cnt": 0, "high_score": score,
        "best_score_rank": 4, "highscore_datetime": "2026-09-01 12:00:00",
        "update_datetime": "2026-09-01 12:00:00", "raw": raw,
    }


def test_all_difficulties_can_be_normalized_for_storage():
    payload = {"data": {"playedRecords": {"userid": "p1", "server": "cn", "scoreInfo": [
        {"song_no": 10, "level": 2, "good_cnt": 200, "ok_cnt": 10, "ng_cnt": 1},
        {"song_no": 11, "level": 4, "good_cnt": 500, "ok_cnt": 20, "ng_cnt": 2},
    ]}}}
    assert [row["level"] for row in normalize_scores(payload)["rows"]] == [4]
    assert [row["level"] for row in normalize_scores(payload, rated_only=False)["rows"]] == [2, 4]


def test_current_scores_and_deduplicated_history_are_separate(tmp_path: Path):
    path = tmp_path / "scores.db"
    db = ScoreDatabase(path)
    try:
        assert db.replace_scores("qq1", "hiroba", [_row()], game_player_id="p1", server="cn") == 1
        assert len(db.get_scores("qq1")) == 1
        assert len(db.get_player_history("qq1", 10, 2)) == 1
        assert db.get_score_syncs("qq1")[0]["changed_count"] == 1

        db.replace_scores("qq1", "hiroba", [_row()], game_player_id="p1", server="cn")
        assert len(db.get_player_history("qq1", 10, 2)) == 1
        assert db.get_score_syncs("qq1")[0]["changed_count"] == 0

        db.replace_scores("qq1", "hiroba", [_row(score=920000, ok=5)], game_player_id="p1", server="cn")
        assert len(db.get_player_history("qq1", 10, 2)) == 2
        assert db.get_scores("qq1")[0]["high_score"] == 920000
        stats = db.storage_stats()
        assert stats["score_history_count"] == 2
        assert stats["score_sync_count"] == 3
    finally:
        db.close()
    reopened = ScoreDatabase(path)
    try:
        assert len(reopened.get_scores("qq1")) == 1
        assert len(reopened.get_player_history("qq1", 10, 2)) == 2
        assert len(reopened.get_score_syncs("qq1")) == 3
    finally:
        reopened.close()


def test_old_scores_table_is_migrated_in_place(tmp_path: Path):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT, player_id TEXT NOT NULL,
            song_no INTEGER NOT NULL, level INTEGER NOT NULL, source TEXT NOT NULL,
            good_cnt INTEGER, ok_cnt INTEGER, ng_cnt INTEGER, dondaful_cnt INTEGER,
            high_score INTEGER, best_score_rank INTEGER, highscore_datetime TEXT,
            update_datetime TEXT, raw_json TEXT NOT NULL, fetched_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

    db = ScoreDatabase(path)
    try:
        columns = {row[1] for row in db._conn.execute("PRAGMA table_info(scores)")}
        assert {"pound_cnt", "combo_cnt", "stage_cnt", "clear_cnt", "full_combo_cnt", "server"} <= columns
    finally:
        db.close()


def test_multiple_kinoko_states_keep_one_current_and_all_unique_history(tmp_path: Path):
    db = ScoreDatabase(tmp_path / "kinoko.db")
    try:
        count = db.replace_scores(
            "qq1", "kinoko", [_row(score=900000, ok=10), _row(score=930000, ok=3)],
            game_player_id="p1", server="cn",
        )
        assert count == 1
        assert db.get_scores("qq1", "kinoko")[0]["high_score"] == 930000
        assert len(db.get_player_history("qq1", 10, 2, "kinoko")) == 2
        batch = db.get_score_syncs("qq1")[0]
        assert batch["received_count"] == 2
        assert batch["current_count"] == 1
        assert batch["changed_count"] == 2
    finally:
        db.close()


def test_service_store_payload_persists_low_levels_and_full_counts(tmp_path: Path):
    db = ScoreDatabase(tmp_path / "service.db")
    service = ScoreService(MemoryBindingsStore(), lambda _key: None, charts={}, score_db=db)
    payload = {"data": {"playedRecords": {"userid": "game1", "server": "cn", "scoreInfo": [
        {
            "song_no": 10, "level": 2, "good_cnt": 200, "ok_cnt": 10, "ng_cnt": 1,
            "pound_cnt": 30, "combo_cnt": 180, "stage_cnt": 5, "clear_cnt": 3,
            "full_combo_cnt": 1, "dondaful_combo_cnt": 0, "high_score": 900000,
            "best_score_rank": 4,
        },
        {
            "song_no": 11, "level": 4, "good_cnt": 500, "ok_cnt": 20, "ng_cnt": 2,
            "pound_cnt": 50, "combo_cnt": 400, "stage_cnt": 8, "clear_cnt": 6,
            "full_combo_cnt": 0, "dondaful_combo_cnt": 0, "high_score": 950000,
            "best_score_rank": 5,
        },
    ]}}}
    try:
        assert service._store_payload("qq1", "hiroba", payload) == 2
        rows = db.get_scores("qq1", "hiroba")
        assert [row["level"] for row in rows] == [2, 4]
        assert rows[0]["pound_cnt"] == 30
        assert rows[0]["stage_cnt"] == 5
        assert rows[0]["full_combo_cnt"] == 1
        assert db.kv_get("score_storage_schema:qq1") == 2
        assert db.storage_stats()["score_history_count"] == 2
    finally:
        db.close()
