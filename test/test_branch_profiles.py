"""Real-source branch coverage, conservative ambiguity and cache integration."""

import asyncio
import copy
import gzip
import hashlib
import json
import zipfile
from pathlib import Path

import pytest

import rating
from profile_data import configuration_scores, load_configuration_catalog
from score_query import annotate_target, played_row
from scripts.build_branch_profiles import (
    TARGETS,
    course_body,
    enumerate_paths,
    reachable_routes,
    split_body,
    tap_count,
)
from service import RATING_CACHE_SCHEMA, MemoryBindingsStore, ScoreService, _slim_result
from storage import ScoreDatabase, load_charts

ROOT = Path(__file__).resolve().parents[1]
RESOURCE = ROOT / "resource"
RESOLVED = {key: notes[0] for key, notes in TARGETS.items() if key != (269, 4)}


@pytest.fixture(scope="module")
def charts():
    return load_charts(RESOURCE / "charts.v1.json.gz")


def payload(keys):
    return {
        "data": {
            "playedRecords": {
                "userid": "test-player",
                "server": "cn",
                "scoreInfo": [
                    {
                        "song_no": key[0],
                        "level": key[1],
                        "good_cnt": notes - 10,
                        "ok_cnt": 10,
                        "ng_cnt": 0,
                        "high_score": 900000,
                    }
                    for key, notes in keys.items()
                ],
            }
        }
    }


def test_all_nine_real_branch_profiles_and_preserved_masters(charts):
    result = rating.analyze(payload(RESOLVED), charts)
    assert len(result["records"]) == 9
    for row in result["records"]:
        key = row["id"], row["level"]
        profile = next(
            b for b in charts[key]["branchProfiles"] if b["totalNotes"] == RESOLVED[key]
        )
        assert row["totalNotes"] == RESOLVED[key]
        assert row["branchProfile"] == profile["key"]
        assert row["aiConstantRaw"] == profile["feature"]["aiConstant"]
        assert row["accuracy"] == pytest.approx((RESOLVED[key] - 5) / RESOLVED[key])
        assert row["ourTaikoV1"] is None
    raw = json.loads(gzip.decompress((RESOURCE / "charts.v1.json.gz").read_bytes()))
    for original in raw:
        loaded = charts[original["id"], original["level"]]
        assert {k: loaded[k] for k in original} == original
    assert (
        hashlib.sha256((RESOURCE / "charts.v1.json.gz").read_bytes()).hexdigest()
        == "4da033a2115c64295272fb10ddb9b772cc23d7eb31f9917d796e055745e9d99d"
    )


@pytest.mark.parametrize("notes", [744, 753])
def test_metal_hawk_ambiguous_paths_never_get_a_constant(charts, notes):
    result = rating.analyze(payload({(269, 4): notes}), charts)
    assert not result["records"]
    assert any(d["code"] == "branch-route-ambiguous" for d in result["diagnostics"])
    assert not charts[269, 4]["branchProfiles"]


def test_unknown_count_and_lower_accuracy_remain_rejected(charts):
    assert not rating.analyze(payload({(182, 4): 568}), charts)["records"]
    p = payload({(182, 4): 569})
    r = p["data"]["playedRecords"]["scoreInfo"][0]
    r.update(good_cnt=100, ok_cnt=100, ng_cnt=369)
    result = rating.analyze(p, charts)
    assert not result["records"]
    assert any(d["code"] == "below-threshold" for d in result["diagnostics"])


def test_master_record_still_works_and_history_chooses_best(charts):
    p = payload({(182, 4): 569})
    items = p["data"]["playedRecords"]["scoreInfo"]
    items.append(
        {"song_no": 182, "level": 4, "good_cnt": 576, "ok_cnt": 0, "ng_cnt": 0}
    )
    both = rating.analyze(p, charts)["records"]
    separate = [
        rating.analyze({"data": {"playedRecords": {"scoreInfo": [item]}}}, charts)[
            "records"
        ][0]
        for item in items
    ]
    assert len(both) == 1 and both[0]["rating"] == max(r["rating"] for r in separate)
    assert not separate[1].get("branchProfile")


def test_branch_config_survives_slim_cache_and_query(charts):
    result = rating.analyze(payload(RESOLVED), charts)
    slim = _slim_result(result)
    catalog = load_configuration_catalog(charts)
    full = configuration_scores(result["records"], catalog)
    restored = configuration_scores(slim["records"], catalog)
    assert full == restored and full["available"]
    wrong = copy.deepcopy(slim["records"])
    for record in wrong:
        record.pop("branchProfile")
    assert full["cells"] != configuration_scores(wrong, catalog)["cells"]
    halloween = next(r for r in slim["records"] if r["id"] == 182)
    assert played_row(halloween, charts[182, 4])["totalNotes"] == 569
    row = played_row(halloween, charts[182, 4])
    annotate_target(row, charts, {}, 8)
    assert "targetScore" not in row


def test_real_source_route_conditions_and_counts(tmp_path):
    proof = json.loads((ROOT / "scripts/data/cn_constant_backfill.json").read_bytes())
    audit = json.loads((ROOT / "docs/branch-note-audit-2026-10-16.json").read_bytes())
    reviews = {(r["id"], r["level"]): r for r in proof["charts"]}
    with zipfile.ZipFile(RESOURCE / proof["sourceArchive"]) as archive:
        for row in audit["charts"]:
            review = reviews[row["id"], row["level"]]
            data = archive.read(review["path"])
            assert hashlib.sha256(data).hexdigest() == row["sourceSha256"]
            path = tmp_path / Path(review["path"]).name
            path.write_bytes(data)
            parts = split_body(course_body(path, review["course"]))
            matches = [
                route
                for route, lines in enumerate_paths(parts)
                if tap_count(lines) == row["totalNotes"]
            ]
            assert sorted(matches) == sorted(row["paths"])
    assert reachable_routes("p,101,102") == ["N"]
    assert reachable_routes("p,-1,-1") == ["M"]
    assert reachable_routes("p,95,95") == ["N", "M"]


def test_stale_branch_supplement_is_rejected(tmp_path):
    for name in [
        "charts.v1.json.gz",
        "branch_profiles.v1.json.gz",
        "branch_profiles.manifest.json",
    ]:
        (tmp_path / name).write_bytes((RESOURCE / name).read_bytes())
    p = tmp_path / "branch_profiles.manifest.json"
    manifest = json.loads(p.read_bytes())
    manifest["chartsSha256"] = "invalid"
    p.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="分支画像"):
        load_charts(tmp_path / "charts.v1.json.gz")


def test_service_sync_persists_branch_and_invalidates_old_cache(tmp_path, charts):
    p = payload(RESOLVED)

    class Client:
        def __init__(self):
            self.calls = 0

        def kinoko(self, *args):
            self.calls += 1
            return copy.deepcopy(p)

        hiroba = kinoko

    async def run():
        client = Client()
        db = ScoreDatabase(tmp_path / "scores.db")
        service = ScoreService(
            MemoryBindingsStore(
                {
                    "qq": {
                        "apikey": "tk_test",
                        "player_id": "test-player",
                        "server": "cn",
                    }
                }
            ),
            lambda _: client,
            charts,
            db,
        )
        try:
            ok, _, slim = await service._sync("qq")
            assert ok and len(slim["records"]) == 9
            assert all(
                row["branchProfile"] for row in db.get_rating_cache("qq")["records"]
            )
            old = copy.deepcopy(slim)
            old["_cacheSchema"] = RATING_CACHE_SCHEMA - 1
            db.put_rating_cache("qq", old)
            calls = client.calls
            refreshed, error = await service._get_analysis("qq")
            assert (
                not error
                and refreshed["_cacheSchema"] == RATING_CACHE_SCHEMA
                and client.calls == calls + 2
            )
        finally:
            db.close()

    asyncio.run(run())
