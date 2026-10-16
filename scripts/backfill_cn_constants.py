"""Infer reviewed CN single-play charts with the frozen v2 model; never train.

Requires the pre-backfill resource snapshot ZIP and original model checkout.
The source archive and reviewed chart fingerprints are tracked with the plugin.
Run --library-only after rebuilding song names, aliases and Dan resources.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import io
import json
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
VERSION = "2026-10-16.1"
REVIEW = ROOT / "scripts/data/cn_constant_backfill.json"


def encoded(value):
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", "utf-8"
    )
    temporary.replace(path)


def write_gz(path, value):
    raw = encoded(value)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(gzip.compress(raw, compresslevel=9, mtime=0))
    temporary.replace(path)
    return {
        "sha256": sha(path.read_bytes()),
        "compressedBytes": path.stat().st_size,
        "rawBytes": len(raw),
    }


def unzip_tja(archive, destination):
    # Never extract arbitrary archive paths, audio, links or executable files.
    for name in archive.namelist():
        path = (destination / name).resolve()
        if (
            not path.is_relative_to(destination.resolve())
            or path.suffix.lower() != ".tja"
        ):
            raise ValueError(f"unsafe source archive entry: {name}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(archive.read(name))


def verified_sources(model_root, proof, directory):
    sys.path.insert(0, str(model_root))
    from taiko_model.parsers import get_parser
    from taiko_model.tja_features import parse_tja

    _, parse5 = get_parser("v5")
    raw = (ROOT / "resource" / proof["sourceArchive"]).read_bytes()
    if sha(raw) != proof["sourceArchiveSha256"]:
        raise ValueError("source archive hash mismatch")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        unzip_tja(archive, directory)
    sources = {}
    for review in proof["charts"]:
        if review["status"] != "verified":
            continue
        path = directory / review["path"]
        if sha(path.read_bytes()) != review["sha256"]:
            raise ValueError("source hash mismatch")
        charts4 = [
            c for c in parse_tja(path, directory) if c.course == review["course"]
        ]
        charts5 = [c for c in parse5(path, directory) if c.course == review["course"]]
        if len(charts4) != 1 or len(charts5) != 1:
            raise ValueError("ambiguous single-play course")
        c4, c5 = charts4[0], charts5[0]
        if (
            c4.fingerprint != review["fingerprintV4"]
            or c5.fingerprint != review["fingerprintV5"]
            or c4.total_notes != review["totalNotes"]
            or c5.total_notes != review["totalNotes"]
            or c4.level != review["sourceStars"]
        ):
            raise ValueError(f"unverified chart: {review['id']}|{review['level']}")
        sources[(review["id"], review["level"])] = (review, c4, c5)
    return sources


def predictions(bundle, rows):
    import numpy as np
    from ml.export_deploy import calibrated_profile, profile_specializations
    from taiko_model.feature_profiles import feature_family_profile

    bases = [
        feature_family_profile(row["features"], bundle["familyWeights"]) for row in rows
    ]
    inputs = []
    for row, base in zip(rows, bases):
        if set(bundle["rawFeatureNames"]) - set(row["features"]):
            raise ValueError("missing model input feature")
        inputs.append(
            [base["scores"][f] for f in bundle["familyOrder"]]
            + [float(row["features"][f] or 0.0) for f in bundle["rawFeatureNames"]]
        )
    matrix = np.asarray(inputs, dtype=np.float64)
    if not np.isfinite(matrix).all():
        raise ValueError("non-finite model input")
    outputs = {
        label: model.predict(matrix) for label, model in bundle["models"].items()
    }
    result = []
    for i, (base, row) in enumerate(zip(bases, rows)):
        predicted = {label: float(values[i]) for label, values in outputs.items()}
        if not all(np.isfinite(v) for v in predicted.values()):
            raise ValueError("non-finite prediction")
        predicted = {
            k: min(11.6, max(1.0, v)) if k == "constant" else min(100.0, max(0.0, v))
            for k, v in predicted.items()
        }
        result.append(
            {
                "aiConstant": round(predicted["constant"], 4),
                "specializations": {
                    k: round(v, 4)
                    for k, v in profile_specializations(bundle, predicted).items()
                },
                "proportions": calibrated_profile(base, predicted)["proportions"],
                "rhythmProfile": row.get("rhythmProfile", {}),
            }
        )
    return result


def backfill(baseline, model_root, proof, sources, directory):
    import joblib
    from ml.export_deploy import validate_model
    from taiko_model import taiko_patterns
    from taiko_model.parsers import get_parser

    import rating
    from profile_data import BANDS, bpm_band
    from scripts.build_rolls import parse_tja as parse_rolls
    from scripts.build_rolls import summarize_course

    output = ROOT / "resource"
    baseline_bytes = baseline.read("resource/charts.v1.json.gz")
    if sha(baseline_bytes) != proof["baselineChartsSha256"]:
        raise ValueError("wrong baseline catalog")
    before = {
        (r["id"], r["level"]): r for r in json.loads(gzip.decompress(baseline_bytes))
    }
    model_path = model_root / "ml/artifacts/feature-profile-model.v2.joblib"
    dataset_bytes = (model_root / "ml/artifacts/profile-dataset.v1.json").read_bytes()
    if (
        sha(model_path.read_bytes()) != proof["model"]["modelSha256"]
        or sha(dataset_bytes) != proof["model"]["datasetSha256"]
    ):
        raise ValueError("frozen model/dataset hash mismatch")
    bundle, dataset = joblib.load(model_path), json.loads(dataset_bytes)
    validate_model(bundle, dataset, sha(dataset_bytes))
    # Replay all old AI constants before admitting newly inferred charts.
    old_rows = dataset.get("profiles", dataset["rows"])
    replay = {
        (r["songNo"], r["level"]): p
        for r, p in zip(old_rows, predictions(bundle, old_rows))
    }
    checked = 0
    for key, chart in before.items():
        if chart.get("feature"):
            if replay[key]["aiConstant"] != chart["feature"]["aiConstant"]:
                raise ValueError(f"baseline replay differs: {key}")
            checked += 1
    print(f"Replayed {checked} existing AI constants without differences", flush=True)
    rows = [
        {
            "features": {
                **c4.features,
                "star_level": float(review["stars"]),
                "course_is_edit": float(c4.course == "edit"),
            },
            "rhythmProfile": c4.rhythm_profile,
        }
        for review, c4, _ in sources.values()
    ]
    predicted = predictions(bundle, rows)
    identities = json.loads((ROOT / "scripts/data/song_names.json").read_bytes())[
        "songs"
    ]
    charts, audit = copy.deepcopy(before), []
    for (key, (review, c4, _)), feature in zip(sources.items(), predicted):
        old = before.get(key, {})
        if old.get("feature"):
            raise ValueError(f"refusing to replace existing AI feature: {key}")
        identity = identities[str(key[0])]
        chart = charts.setdefault(
            key,
            {"id": key[0], "level": key[1], "genre": identity["genre"], "public": None},
        )
        entry = {
            "id": key[0],
            "level": key[1],
            "aiConstant": feature["aiConstant"],
            "totalNotes": c4.total_notes,
        }
        if old.get("public") and old["totalNotes"] != c4.total_notes:
            # A reference profile for a different chart must not be silently reused.
            entry["retiredReference"] = {
                "totalNotes": old["totalNotes"],
                "public": old["public"],
            }
            chart["public"] = None
        chart.update(
            title=identity["title"],
            titleJa=identity["titleJa"],
            totalNotes=c4.total_notes,
            feature=feature,
        )
        audit.append(entry)

    profiles = json.loads(
        gzip.decompress(baseline.read("resource/profile_configurations.v1.json.gz"))
    )
    profile_map = {(p["id"], p["level"]): p for p in profiles["profiles"]}
    provenance = json.loads(
        gzip.decompress(
            baseline.read("resource/profile_configurations.provenance.json.gz")
        )
    )
    _, parse5 = get_parser("v5")
    previous = taiko_patterns._bpm_band
    taiko_patterns._bpm_band = bpm_band
    try:
        for key, (review, _, _) in sources.items():
            course = next(
                c
                for c in parse5(directory / review["path"], directory)
                if c.course == review["course"]
            )
            profile_map[key] = {
                "id": key[0],
                "level": key[1],
                "totalNotes": course.total_notes,
                "rhythmProfile": {
                    field: course.rhythm_profile.get(field, [])
                    for field in ("cells", "arrangementCells")
                },
            }
            provenance.append(
                {
                    "id": key[0],
                    "level": key[1],
                    "path": review["path"],
                    "fingerprint": course.fingerprint,
                    "totalNotes": course.total_notes,
                    "sha256": review["sha256"],
                }
            )
    finally:
        taiko_patterns._bpm_band = previous
    configured, perfect = {}, []
    for key, profile in sorted(profile_map.items()):
        chart = copy.deepcopy(charts[key])
        chart["feature"]["rhythmProfile"] = profile["rhythmProfile"]
        configured[key] = chart
        score = {
            "id": key[0],
            "level": key[1],
            "title": chart["title"],
            "goodCount": chart["totalNotes"],
            "okCount": 0,
            "ngCount": 0,
            "dondafulComboCount": 1,
        }
        perfect.append(
            {
                **score,
                **rating.calculate_ai_values(chart, score),
                "chart": chart,
                "feature": chart["feature"],
            }
        )
    full = {
        c["key"]: c
        for c in rating.calculate_rhythm_ability(perfect, configured)["cells"]
    }
    _, prevalence = rating._rhythm_catalog_prevalence(configured)
    cells = [
        {
            "key": key,
            "pattern": key.split("|")[0],
            "band": key.split("|")[1],
            "ceiling": full.get(key, {}).get("score"),
            "catalogSamples": count,
        }
        for key, count in sorted(prevalence.items())
    ]
    stats = write_gz(
        output / "charts.v1.json.gz", [v for _, v in sorted(charts.items())]
    )
    manifest = json.loads(baseline.read("resource/charts.manifest.json"))
    manifest.update(
        chartCount=len(charts),
        **stats,
        backfillVersion=VERSION,
        source="frozen v2 model + scripts/data/cn_constant_backfill.json; existing AI features preserved",
    )
    manifest["catalogVersion"] = manifest["modelId"] + "+cn-" + VERSION
    write_json(output / "charts.manifest.json", manifest)
    config_version = "bpm7-2026-10-16-v1"
    profiles.update(
        version=config_version,
        chartsSha256=stats["sha256"],
        profiles=[p for _, p in sorted(profile_map.items())],
        cells=cells,
    )
    config_stats = write_gz(output / "profile_configurations.v1.json.gz", profiles)
    config_manifest = {
        "schemaVersion": 1,
        "version": config_version,
        "chartsSha256": stats["sha256"],
        "profiles": len(profile_map),
        "configurations": len(cells),
        "bands": BANDS,
        **config_stats,
        "source": "Preserved baseline BPM7 profiles + verified CN single-play TJA",
        "reviewSha256": sha(REVIEW.read_bytes()),
        "baseline": "Full-good catalog with unchanged rating.py configuration aggregation",
    }
    write_json(output / "profile_configurations.manifest.json", config_manifest)
    write_gz(output / "profile_configurations.provenance.json.gz", provenance)
    rolls = json.loads(gzip.decompress(baseline.read("resource/rolls.v1.json.gz")))
    for key, (review, _, _) in sources.items():
        courses = [
            c
            for c in parse_rolls(directory / review["path"])
            if {"3": "oni", "4": "edit"}.get(c["course"].lower(), c["course"].lower())
            == review["course"]
        ]
        if len(courses) != 1:
            raise ValueError(f"ambiguous roll course: {key}")
        rolls["songs"][f"{key[0]}|{key[1]}"] = {
            **summarize_course(courses[0]),
            "source": "tja",
        }
    rolls["data_version"] = VERSION
    roll_stats = write_gz(output / "rolls.v1.json.gz", rolls)
    roll_manifest = json.loads(baseline.read("resource/rolls.manifest.json"))
    songs = rolls["songs"]
    roll_manifest.update(
        dataVersion=VERSION,
        catalogCharts=len(charts),
        coveredSongs=len(songs),
        coverageRatio=round(len(songs) / len(charts), 4),
        **roll_stats,
        songsWithRolls=sum(v["rolls"] > 0 for v in songs.values()),
        balloonOnlySongs=sum(v["rolls"] <= 0 < v["balloons"] for v in songs.values()),
        songsWithoutLongNotes=sum(
            v["rolls"] <= 0 and v["balloons"] <= 0 for v in songs.values()
        ),
        supplementalReview="scripts/data/cn_constant_backfill.json",
    )
    write_json(output / "rolls.manifest.json", roll_manifest)
    write_json(
        ROOT / "docs/cn-constant-backfill-2026-10-16.json",
        {
            "version": VERSION,
            "retrained": False,
            "model": proof["model"],
            "baselineReplay": checked,
            "oldFeaturesPreserved": all(
                charts[k]["feature"] == v["feature"]
                for k, v in before.items()
                if v.get("feature")
            ),
            "added": audit,
            "pending": [r for r in proof["charts"] if r["status"] != "verified"],
        },
    )
    print(
        f"Added {len(audit)} AI profiles; catalog now {len(charts)} charts", flush=True
    )


def build_library(baseline, proof, sources, directory):
    from scripts.chart_metrics import summarize_route
    from scripts.tja_timeline import parse_timelines
    from song_alias import normalize

    output = ROOT / "resource"
    aliases = json.loads(gzip.decompress((output / "aliases.v1.json.gz").read_bytes()))[
        "songs"
    ]
    archive = zipfile.ZipFile(
        io.BytesIO(baseline.read("resource/chart-library-20261014.zip"))
    )
    old_id = json.loads(archive.read("chart_library/current.json"))["buildId"]
    prefix = f"chart_library/versions/{old_id}/"
    db_path = directory / "analysis.sqlite3"
    db_path.write_bytes(archive.read(prefix + "analysis.sqlite3"))
    manifest = json.loads(archive.read(prefix + "manifest.json"))
    hashes = json.loads(archive.read(prefix + "sources.json"))
    tja_path = directory / "tja.zip"
    tja_path.write_bytes(archive.read(prefix + "tja.zip"))
    db = sqlite3.connect(db_path)
    built = 0
    with zipfile.ZipFile(tja_path, "a", zipfile.ZIP_DEFLATED) as tja:
        for key, (review, _, c5) in sources.items():
            if review["bound"]:
                existing = db.execute(
                    "SELECT key FROM bindings WHERE song_id=? AND level=?", key
                ).fetchone()
                if not existing:
                    raise ValueError(f"lost baseline binding: {key}")
                payload = json.loads(
                    gzip.decompress(
                        db.execute(
                            "SELECT payload FROM charts WHERE key=?", existing
                        ).fetchone()[0]
                    )
                )
                if payload["source"]["fingerprint"] != c5.fingerprint:
                    raise ValueError("baseline binding fingerprint mismatch")
                continue
            relative = review["path"]
            raw = (directory / relative).read_bytes()
            if relative not in hashes:
                info = zipfile.ZipInfo(relative, (1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                tja.writestr(info, raw)
                hashes[relative] = sha(raw)
            chart_key = sha(encoded([relative, review["course"], 1]))[:24]
            timeline = next(
                c
                for c in parse_timelines(directory / relative)
                if c["course"] == review["course"]
            )
            route = "M" if "M" in timeline["routes"] else "single"
            if len(timeline["routes"][route]["taps"]) != c5.total_notes:
                raise ValueError(f"timeline note count mismatch: {key}")
            payload = {
                "schemaVersion": 1,
                "algorithm": "tja-reference-v1",
                "chartKey": chart_key,
                "source": {
                    "path": relative,
                    "sha256": review["sha256"],
                    "courseOccurrence": 1,
                    "fingerprint": c5.fingerprint,
                    "parser": "v5",
                },
                "title": c5.title,
                "titleJa": c5.title_ja,
                "course": c5.course,
                "level": key[1],
                "timeOrigin": "#START; seconds are not audio timestamps",
                "audioOffsetMetadata": timeline["offset"],
                "features": c5.features,
                "rhythmProfile": c5.rhythm_profile,
                "featureRoute": route,
                "warnings": list(c5.warnings),
                "routes": {
                    n: summarize_route(v) for n, v in timeline["routes"].items()
                },
            }
            db.execute(
                "INSERT INTO charts VALUES (?,?,?)",
                (
                    chart_key,
                    sha(encoded([review, payload])),
                    gzip.compress(encoded(payload), mtime=0),
                ),
            )
            alias = aliases[f"{key[0]}|{key[1]}"]
            db.execute(
                "INSERT INTO catalog VALUES (?,?,?,?,?,?)",
                (
                    chart_key,
                    alias["names"][0],
                    c5.title_ja,
                    key[1],
                    json.dumps([key[0]]),
                    relative,
                ),
            )
            db.execute("INSERT INTO bindings VALUES (?,?,?)", (*key, chart_key))
            built += 1
        # Refresh canonical display names and aliases for every binding, not only new charts.
        for sid, level, chart_key in db.execute(
            "SELECT song_id,level,key FROM bindings"
        ).fetchall():
            alias = aliases.get(f"{sid}|{level}", {})
            if alias.get("names"):
                db.execute(
                    "UPDATE catalog SET title=? WHERE key=?",
                    (alias["names"][0], chart_key),
                )
            for name in alias.get("names", []) + alias.get("aliases", []):
                if normalize(name):
                    db.execute(
                        "INSERT OR REPLACE INTO names VALUES (?,?,1)",
                        (normalize(name), chart_key),
                    )
    db.commit()
    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    manifest.update(
        analyses=db.execute("SELECT count(*) FROM charts").fetchone()[0],
        mappedCharts=db.execute("SELECT count(*) FROM bindings").fetchone()[0],
    )
    db.close()
    (directory / "sources.json").write_bytes(encoded(hashes))
    build_id = "20261016-cn-constants-v1"
    manifest.update(
        buildId=build_id,
        chartsSha256=sha((output / "charts.v1.json.gz").read_bytes()),
        aliasesSha256=sha((output / "aliases.v1.json.gz").read_bytes()),
        tjaFiles=len(hashes),
        baselineBuildId=old_id,
        supplementalReviewSha256=sha(REVIEW.read_bytes()),
        supplementalEngineSha256=sha(Path(__file__).read_bytes()),
        built=built,
        reused=manifest["analyses"] - built,
    )
    manifest["files"] = {
        name: {
            "bytes": (directory / name).stat().st_size,
            "sha256": sha((directory / name).read_bytes()),
        }
        for name in ("analysis.sqlite3", "sources.json", "tja.zip")
    }
    (directory / "manifest.json").write_bytes(encoded(manifest))
    files = {"chart_library/current.json": encoded({"buildId": build_id})}
    files.update(
        {
            f"chart_library/versions/{build_id}/{name}": (directory / name).read_bytes()
            for name in ("analysis.sqlite3", "sources.json", "tja.zip", "manifest.json")
        }
    )
    package = output / "chart-library-20261014.zip"
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as target:
        for name, raw in files.items():
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(info, raw, compresslevel=9)
    write_json(
        output / "chart_library.release.json",
        {
            "schemaVersion": 1,
            "version": VERSION,
            "buildId": build_id,
            "archiveFile": package.name,
            "archiveBytes": package.stat().st_size,
            "archiveSha256": sha(package.read_bytes()),
            "unpackedBytes": sum(map(len, files.values())),
            "chartsSha256": manifest["chartsSha256"],
        },
    )
    print(
        f"Library: {manifest['analyses']} analyses, {manifest['mappedCharts']} bindings",
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--library-only", action="store_true")
    args = parser.parse_args()
    proof = json.loads(REVIEW.read_bytes())
    with (
        tempfile.TemporaryDirectory(prefix="rtlink-cn-") as temp,
        zipfile.ZipFile(args.baseline) as baseline,
    ):
        directory = Path(temp)
        sources = verified_sources(args.model_root.resolve(), proof, directory)
        if args.library_only:
            build_library(baseline, proof, sources, directory)
        else:
            backfill(baseline, args.model_root.resolve(), proof, sources, directory)
