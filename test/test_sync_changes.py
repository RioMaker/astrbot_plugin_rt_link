"""Sync deltas must survive caching and compare isolated consecutive bests."""

import asyncio
import copy

import pytest
from PIL import Image

from profile_data import score_sync_changes
from profile_image import render_profile_image, score_change_label
from service import MemoryBindingsStore, ScoreService
from storage import ScoreDatabase, load_charts


def test_compare_duplicates_difficulties_missing_and_new():
    previous = [
        {"song_no": 1, "level": 4, "high_score": 900000},
        {"song_no": 1, "level": 5, "high_score": 1000000},
        {"song_no": 2, "level": 4, "high_score": None},
        {"song_no": 3, "level": 4, "high_score": 50},
    ]
    current = [
        {"id": 1, "level": 4, "highScore": 920000},
        {"id": 1, "level": 4, "highScore": 910000},
        {"id": 1, "level": 5, "highScore": 990000},
        {"id": 2, "level": 4, "highScore": 900000},
        {"id": 3, "level": 4, "highScore": 50},
        {"id": 4, "level": 4, "highScore": 0},
        {"id": 5, "level": 4, "highScore": None},
        {"id": 6, "level": 2, "highScore": 100},
    ]
    changes = score_sync_changes(previous, current)
    assert [(r["id"], r["level"], r["delta"]) for r in changes["items"]] == [
        (1, 4, 20000),
        (1, 5, -10000),
        (4, 4, None),
    ]
    assert score_sync_changes([], current) == {"baseline": False, "items": []}
    assert score_change_label(changes["items"][0])[0] == "↑ +20,000"
    assert score_change_label(changes["items"][1])[0] == "↓ -10,000"


@pytest.mark.parametrize("source", ["kinoko", "hiroba", "sakura"])
def test_consecutive_sync_cache_restart_failure_and_identity(tmp_path, source):
    charts = load_charts("resource/charts.v1.json.gz")
    key, chart = next(
        (k, c) for k, c in charts.items() if k[1] == 4 and c["totalNotes"] > 10
    )
    score = 900000
    fail = False

    class Client:
        def payload(self, value):
            if fail:
                from api_client import KinokoAPIError

                raise KinokoAPIError("offline")
            return {
                "data": {
                    "playedRecords": {
                        "userid": "p1",
                        "server": "cn",
                        "scoreInfo": [
                            {
                                "song_no": key[0],
                                "level": 4,
                                "good_cnt": chart["totalNotes"] - 2,
                                "ok_cnt": 2,
                                "ng_cnt": 0,
                                "high_score": value,
                                "best_score_rank": 5,
                            }
                        ],
                    }
                }
            }

        def kinoko(self, *args):
            if source == "hiroba":
                from api_client import KinokoAPIError

                raise KinokoAPIError("fallback")
            return self.payload(score)

        def hiroba(self, *args):
            return self.payload(score + 100000 if score is not None else None)

        def fetch(self):
            from sakura_client import SakuraAPIError

            if fail:
                raise SakuraAPIError("offline")
            return {
                "ok": True,
                "taikoId": "p1",
                "data": {
                    "profile": {"userid": "p1"},
                    "_meta": {"source": "wahlap"},
                    "songs": [
                        {
                            "song_no": key[0],
                            "level": 4,
                            "good_cnt": chart["totalNotes"] - 2,
                            "ok_cnt": 2,
                            "ng_cnt": 0,
                            "high_score": score,
                            "best_score_rank": 5,
                        }
                    ],
                },
            }

    async def run():
        nonlocal score, fail
        path = tmp_path / "scores.db"
        db = ScoreDatabase(path)
        store = MemoryBindingsStore(
            {"qq": {"apikey": "test", "player_id": "p1", "server": "cn"}}
        )
        svc = ScoreService(
            store,
            lambda _: Client(),
            charts=charts,
            score_db=db,
            provider="sakura" if source == "sakura" else "kinoko",
        )
        try:
            ok, error, first = await svc._sync("qq")
            assert ok, error
            assert first["profileSyncChanges"]["baseline"] is False
            score += 23456
            ok, error, raised = await svc._sync("qq")
            assert ok, error
            change = raised["profileSyncChanges"]["items"][0]
            assert change["delta"] == 23456
            assert raised["profileSyncChanges"]["source"] == source
            assert change["title"] == chart["title"]
            cached, error = await svc._get_analysis("qq")
            assert cached["profileSyncChanges"] == raised["profileSyncChanges"]
            db.close()
            db = ScoreDatabase(path)
            svc.db = db
            assert (
                db.get_rating_cache("qq")["profileSyncChanges"]
                == raised["profileSyncChanges"]
            )
            score -= 5000
            ok, error, lowered = await svc._sync("qq")
            assert ok, error
            assert lowered["profileSyncChanges"]["items"][0]["delta"] == -5000
            # Returning to a previously seen state must still compare with the last sync.
            score += 5000
            _, _, returned = await svc._sync("qq")
            assert returned["profileSyncChanges"]["items"][0]["delta"] == 5000
            fail = True
            ok, _, _ = await svc._sync("qq")
            assert ok is False
            assert (
                db.get_rating_cache("qq")["profileSyncChanges"]
                == returned["profileSyncChanges"]
            )
            fail = False
            _, _, unchanged = await svc._sync("qq")
            assert unchanged["profileSyncChanges"]["items"] == []
            saved_score = score
            score = None
            _, _, missing = await svc._sync("qq")
            assert missing["profileSyncChanges"]["items"] == []
            assert missing["profileScoreRows"][0]["highScore"] is None
            score = saved_score
            _, _, restored = await svc._sync("qq")
            assert restored["profileSyncChanges"]["items"] == []
            # A different identity must never inherit deltas from old current rows.
            db._conn.execute("UPDATE scores SET game_player_id='other', server='jp'")
            db._conn.commit()
            score += 1
            _, _, isolated = await svc._sync("qq")
            assert isolated["profileSyncChanges"]["baseline"] is False
        finally:
            db.close()

    asyncio.run(run())


def test_render_all_changes_and_best20_markers(tmp_path, monkeypatch):
    import profile_image

    texts = []
    original = profile_image.txt

    def capture(d, value, *args, **kwargs):
        texts.append(str(value))
        return original(d, value, *args, **kwargs)

    monkeypatch.setattr(profile_image, "txt", capture)
    rows = [
        {
            "id": i,
            "level": 5 if i % 2 else 4,
            "title": "歌曲名称" * 12,
            "rating": 10 - i / 100,
            "aiConstant": 10,
            "accuracy": 0.98,
            "highScore": 1000000,
            "bestScoreRank": 5,
        }
        for i in range(22)
    ]
    changes = [
        {
            "id": r["id"],
            "level": r["level"],
            "title": r["title"],
            "previousScore": 990000 if i % 2 else 1010000,
            "highScore": 1000000,
            "delta": 10000 if i % 2 else -10000,
        }
        for i, r in enumerate(rows)
    ]
    data = {
        "records": rows,
        "summary": {"rating": 10},
        "profileSyncChanges": {"baseline": True, "source": "kinoko", "items": changes},
    }
    before = copy.deepcopy(data)
    path = render_profile_image(data, tmp_path / "changes.png")
    assert data == before
    assert texts.count("↑ +10,000") == 21  # All 11 changes plus 10 BEST20 cards.
    assert texts.count("↓ -10,000") == 21
    with Image.open(path) as im:
        assert im.width == 1440 and im.height > 5000
