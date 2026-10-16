"""Release acceptance for reviewed CN backfill and real bundled source data."""

import asyncio
import gzip
import hashlib
import json
import zipfile
from collections import Counter
from pathlib import Path

import rating
from chart_library import ChartLibrary
from chart_library_installer import ChartLibraryInstaller
from profile_data import load_configuration_catalog
from scripts.build_song_names import apply_reviewed_cn_updates
from scripts.tja_timeline import parse_timelines
from storage import load_charts

ROOT = Path(__file__).resolve().parents[1]
RESOURCE = ROOT / "resource"
REVIEW = json.loads((ROOT / "scripts/data/cn_constant_backfill.json").read_bytes())


def test_reviewed_single_charts_rate_with_current_note_counts(tmp_path):
    charts = load_charts(RESOURCE / "charts.v1.json.gz")
    records = []
    verified = [r for r in REVIEW["charts"] if r["status"] == "verified"]
    with zipfile.ZipFile(RESOURCE / REVIEW["sourceArchive"]) as archive:
        for row in verified:
            raw = archive.read(row["path"])
            assert hashlib.sha256(raw).hexdigest() == row["sha256"]
            path = tmp_path / Path(row["path"]).name
            path.write_bytes(raw)
            course = next(
                c for c in parse_timelines(path) if c["course"] == row["course"]
            )
            route = course["routes"].get("M", course["routes"].get("single"))
            assert len(route["taps"]) == row["totalNotes"]
            chart = charts[row["id"], row["level"]]
            assert chart["totalNotes"] == row["totalNotes"]
            assert 1 <= chart["feature"]["aiConstant"] <= 11.6
            records.append(
                {
                    "song_no": row["id"],
                    "level": row["level"],
                    "good_cnt": row["totalNotes"],
                    "ok_cnt": 0,
                    "ng_cnt": 0,
                }
            )
    result = rating.analyze({"data": {"playedRecords": {"scoreInfo": records}}}, charts)
    assert result["counts"]["featureMatched"] == len(verified) == 86
    assert result["counts"]["invalid"] == 0
    config = load_configuration_catalog(charts)
    assert config["available"], config
    assert all((r["id"], r["level"]) in config["catalog"] for r in verified)


def test_pending_charts_are_never_filled_and_reference_versions_stay_separate():
    charts = load_charts(RESOURCE / "charts.v1.json.gz")
    added = {
        (r["id"], r["level"]) for r in REVIEW["charts"] if r["status"] == "verified"
    }
    preserved = [
        [sid, level, chart["feature"]]
        for (sid, level), chart in sorted(charts.items())
        if (sid, level) not in added and chart.get("feature")
    ]
    encoded = json.dumps(preserved, ensure_ascii=False, separators=(",", ":")).encode()
    assert len(preserved) == 1327
    assert hashlib.sha256(encoded).hexdigest() == REVIEW["baselineFeaturesSha256"]
    from service import CATALOG_VERSION

    assert CATALOG_VERSION.endswith("+cn-2026-10-16.1")
    assert Counter(r["status"] for r in REVIEW["charts"]) == {
        "verified": 86,
        "deferred-double": 6,
        "deferred-p1-mapping": 4,
        "missing-tja": 2,
    }
    for row in REVIEW["charts"]:
        if row["status"] != "verified":
            assert not charts.get((row["id"], row["level"]), {}).get("feature")
    audit = json.loads(
        (ROOT / "docs/cn-constant-backfill-2026-10-16.json").read_bytes()
    )
    assert audit["oldFeaturesPreserved"] and audit["baselineReplay"] == 1327
    for row in audit["added"]:
        if row.get("retiredReference"):
            assert charts[row["id"], row["level"]]["public"] is None
            assert row["retiredReference"]["totalNotes"] != row["totalNotes"]
    assert charts[1501, 5]["totalNotes"] == 999
    assert (1501, 4) not in charts and (1500, 4) not in charts


def test_dated_cn_corrections_survive_rebuild_and_keep_previous_names():
    payload = json.loads((ROOT / "scripts/data/song_names.json").read_bytes())
    songs = payload["songs"]
    for sid in (1447, 1448, 1449, 1464, 1465, 1502):
        songs[str(sid)]["cnStatus"] = "archive"
    songs["937"]["cnStatus"] = "current"
    apply_reviewed_cn_updates(songs)
    assert all(
        songs[str(sid)]["cnStatus"] == "current"
        for sid in (1447, 1448, 1449, 1464, 1465, 1502)
    )
    assert songs["937"]["cnStatus"] == "archive"
    assert songs["1502"]["title"] == "钝响Likelihood"
    assert "DONKYO Likelihood" in songs["1502"]["names"]
    assert songs["156"]["levels"]["5"]["totalNotes"] == 999
    assert songs["69"]["levels"]["4"]["cnAvailable"] is True
    assert songs["69"]["levels"]["5"]["cnAvailable"] is False
    assert (
        sum(
            meta["cnAvailable"]
            for song in songs.values()
            for level, meta in song["levels"].items()
            if level in ("4", "5")
        )
        == 1398
    )


def test_actual_bundled_library_installs_and_resolves_every_added_chart(tmp_path):
    chart_hash = hashlib.sha256(
        (RESOURCE / "charts.v1.json.gz").read_bytes()
    ).hexdigest()
    library = ChartLibrary(tmp_path / "library", chart_hash)
    installer = ChartLibraryInstaller(library, RESOURCE / "chart_library.release.json")

    async def run():
        installer.start()
        await installer._task
        assert library.status()["available"], installer.status()
        for row in REVIEW["charts"]:
            if row["status"] != "verified":
                continue
            result = library.query(str(row["id"]), level=row["level"])
            assert result["status"] == "ok", (row["id"], result)
        await installer.close()

    asyncio.run(run())
    release = json.loads((RESOURCE / "chart_library.release.json").read_bytes())
    with zipfile.ZipFile(RESOURCE / release["archiveFile"]) as archive:
        name = f"chart_library/versions/{release['buildId']}/manifest.json"
        manifest = json.loads(archive.read(name))
        assert (
            manifest["aliasesSha256"]
            == hashlib.sha256(
                (RESOURCE / "aliases.v1.json.gz").read_bytes()
            ).hexdigest()
        )
    profiles = json.loads(
        gzip.decompress((RESOURCE / "profile_configurations.v1.json.gz").read_bytes())
    )
    assert len(profiles["profiles"]) == 1413
