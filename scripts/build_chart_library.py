"""Build a portable, versioned TJA reference library; never train a model.

The upstream parser-v5 ESE index supplies whole-chart features. This builder
adds timelines and measure metrics, archives every original TJA, and publishes
an atomic current.json pointer only after all validation succeeds.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import uuid
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from song_alias import load_aliases, normalize
from scripts.song_identity import exact_candidates
from storage import load_charts

if __package__:
    from .chart_metrics import summarize_route
    from .tja_timeline import parse_timelines
else:
    from chart_metrics import summarize_route
    from tja_timeline import parse_timelines

ALGORITHM = "tja-reference-v1"


def encoded(value):
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def build(ese_root, index_path, mapping_path, output, quota_mib=512):
    ese_root, output = ese_root.resolve(), output.resolve()
    index_bytes, mapping_bytes = index_path.read_bytes(), mapping_path.read_bytes()
    index, mapping = json.loads(index_bytes), json.loads(mapping_bytes)
    revision = subprocess.check_output(
        [
            "git",
            "-c",
            f"safe.directory={ese_root.as_posix()}",
            "-C",
            str(ese_root),
            "rev-parse",
            "HEAD",
        ],
        text=True,
    ).strip()
    if (
        revision != index.get("eseRevision")
        or revision != mapping.get("eseRevision")
        or index.get("parserId") != "v5"
    ):
        raise ValueError(
            "ESE revision/parser mismatch; regenerate the upstream index first"
        )
    dirty = subprocess.check_output(
        [
            "git",
            "-c",
            f"safe.directory={ese_root.as_posix()}",
            "-C",
            str(ese_root),
            "status",
            "--porcelain",
            "--",
            "*.tja",
        ],
        text=True,
    )
    if dirty.strip():
        raise ValueError(
            "ESE has modified/untracked TJA files; a clean revision is required"
        )
    charts = load_charts(ROOT / "resource/charts.v1.json.gz")
    aliases = load_aliases(ROOT / "resource/aliases.v1.json.gz", charts)
    occurrences = Counter()
    rows = []
    for row in index["charts"]:
        source_pair = (row["relativePath"], row["course"])
        occurrences[source_pair] += 1
        rows.append({**row, "courseOccurrence": occurrences[source_pair]})
    by_source = {(r["relativePath"], r["course"], r["fingerprint"]): r for r in rows}
    if len(by_source) != len(rows):
        raise ValueError(
            "duplicate identical path/course/fingerprint in upstream index"
        )
    links = {}
    for row in mapping["mappings"]:
        selected = row.get("selected")
        key = (row["songNo"], row["level"])
        if row.get("status") != "matched" or not selected or key not in charts:
            continue
        source_key = (
            selected["relativePath"],
            selected["course"],
            selected["fingerprint"],
        )
        reference = by_source.get(source_key)
        if (
            not reference
            or reference["fingerprint"] != selected["fingerprint"]
            or reference["totalNotes"] != charts[key]["totalNotes"]
        ):
            raise ValueError(f"unverified mapping: {key}")
        links.setdefault(source_key, []).append(key)

    # A game ID can exist before a rating model. Supplemental bindings use
    # reviewed public identity + exact ESE title/course/stars/notes/fingerprint.
    # A rated song may still have an unbound chart or a newly added Ura chart.
    identity_path = ROOT / "scripts/data/song_names.json"
    identities = json.loads(identity_path.read_bytes()) if identity_path.exists() else {}
    if identities.get("sources", {}).get("ese", {}).get("revision") == revision:
        for entry in identities.get("eseSupplementalMappings", []):
            selected = entry["selected"]
            key = (entry["songNo"], entry["level"])
            source_key = (selected["relativePath"], selected["course"], selected["fingerprint"])
            reference = by_source.get(source_key)
            identity = identities["songs"][str(key[0])]
            meta = identity["levels"][str(key[1])]
            candidates = exact_candidates(rows, identity, key[1])
            already_bound = any(key in values for values in links.values())
            if (not reference or len(candidates) != 1
                    or candidates[0]["fingerprint"] != selected["fingerprint"]
                    or candidates[0]["relativePath"] != selected["relativePath"]
                    or candidates[0]["course"] != selected["course"]
                    or already_bound
                    or (key in charts and charts[key]["totalNotes"] != meta["totalNotes"])):
                raise ValueError(f"unverified supplemental identity: {key}")
            charts[key] = {"title": identity["title"], "titleJa": identity["titleJa"], **meta}
            links.setdefault(source_key, []).append(key)

    output.mkdir(parents=True, exist_ok=True)
    existing_bytes = sum(p.stat().st_size for p in output.rglob("*") if p.is_file())
    if quota_mib <= 0 or existing_bytes + 64 * 1048576 > quota_mib * 1048576:
        raise ValueError(
            "library quota lacks 64 MiB build headroom; old versions retained"
        )
    if shutil.disk_usage(output).free < 256 * 1048576:
        raise ValueError("disk has less than 256 MiB free")
    build_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:8]
    )
    staging = output / "versions" / build_id
    staging.mkdir(parents=True)
    current_path = output / "current.json"
    old = None
    if current_path.exists():
        old_id = json.loads(current_path.read_bytes())["buildId"]
        if (
            not old_id
            or Path(old_id).name != old_id
            or "/" in old_id
            or "\\" in old_id
            or old_id in (".", "..")
        ):
            raise ValueError("invalid existing library pointer")
        old_path = output / "versions" / old_id / "analysis.sqlite3"
        old = sqlite3.connect(old_path.as_uri() + "?mode=ro", uri=True)
    engine_hash = sha(
        b"".join(
            (Path(__file__).parent / p).read_bytes()
            for p in ("build_chart_library.py", "chart_metrics.py", "tja_timeline.py")
        )
    )
    db = sqlite3.connect(staging / "analysis.sqlite3")
    db.executescript("""
        CREATE TABLE charts (key TEXT PRIMARY KEY, input_hash TEXT NOT NULL, payload BLOB NOT NULL);
        CREATE TABLE catalog (key TEXT PRIMARY KEY, title TEXT, title_ja TEXT, level INTEGER, song_ids TEXT, relative_path TEXT);
        CREATE TABLE names (name TEXT, key TEXT, priority INTEGER, PRIMARY KEY(name,key));
        CREATE INDEX names_lookup ON names(name);
        CREATE TABLE bindings (song_id INTEGER, level INTEGER, key TEXT, PRIMARY KEY(song_id,level));
    """)
    file_hashes, timelines, reused, built = {}, {}, 0, 0
    try:
        files = sorted(ese_root.rglob("*.tja"))
        with zipfile.ZipFile(
            staging / "tja.zip", "w", zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            for path in files:
                if not path.resolve().is_relative_to(ese_root):
                    raise ValueError("TJA path escapes ESE root")
                raw = path.read_bytes()
                relative = path.relative_to(ese_root).as_posix()
                file_hashes[relative] = sha(raw)
                entry = zipfile.ZipInfo(relative, (1980, 1, 1, 0, 0, 0))
                entry.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(entry, raw, compresslevel=9)
        for n, row in enumerate(rows):
            relative, course = row["relativePath"], row["course"]
            if relative not in file_hashes:
                raise ValueError(f"missing source: {relative}")
            key = sha(encoded([relative, course, row["courseOccurrence"]]))[:24]
            input_hash = sha(encoded([engine_hash, file_hashes[relative], row]))
            previous = (
                old.execute(
                    "SELECT payload FROM charts WHERE key=? AND input_hash=?",
                    (key, input_hash),
                ).fetchone()
                if old
                else None
            )
            if previous:
                blob = previous[0]
                # Detect corruption before reusing and publishing an old blob.
                payload = json.loads(gzip.decompress(blob))
                if (
                    payload["chartKey"] != key
                    or payload["source"]["sha256"] != file_hashes[relative]
                ):
                    raise ValueError("invalid reusable analysis")
                reused += 1
            else:
                if relative not in timelines:
                    timelines[relative] = {
                        (c["course"], c["courseOccurrence"]): c
                        for c in parse_timelines(ese_root / relative)
                    }
                timeline_key = (course, row["courseOccurrence"])
                timeline = timelines[relative][timeline_key]
                reference_route = "M" if "M" in timeline["routes"] else "single"
                if (
                    len(timeline["routes"][reference_route]["taps"])
                    != row["totalNotes"]
                ):
                    raise ValueError(f"note count mismatch: {relative} {course}")
                payload = {
                    "schemaVersion": 1,
                    "algorithm": ALGORITHM,
                    "chartKey": key,
                    "source": {
                        "path": relative,
                        "sha256": file_hashes[relative],
                        "courseOccurrence": row["courseOccurrence"],
                        "fingerprint": row["fingerprint"],
                        "parser": "v5",
                    },
                    "title": row["title"],
                    "titleJa": row.get("titleJa"),
                    "course": course,
                    "level": 4 if course == "oni" else 5,
                    "timeOrigin": "#START; seconds are not audio timestamps",
                    "audioOffsetMetadata": timeline["offset"],
                    "features": row["features"],
                    "rhythmProfile": row["rhythmProfile"],
                    "featureRoute": reference_route,
                    "warnings": row["warnings"]
                    + (
                        ["duplicate-course-block"]
                        if occurrences[(relative, course)] > 1
                        else []
                    ),
                    "routes": {
                        name: summarize_route(value)
                        for name, value in timeline["routes"].items()
                    },
                }
                blob = gzip.compress(encoded(payload), compresslevel=9, mtime=0)
                built += 1
                # Only keep the other difficulty of this file until used.
                timelines[relative].pop(timeline_key)
                if not timelines[relative]:
                    del timelines[relative]
            db.execute("INSERT INTO charts VALUES (?,?,?)", (key, input_hash, blob))
            linked = links.get((relative, course, row["fingerprint"]), [])
            alias = aliases["songs"].get(f"{linked[0][0]}|{linked[0][1]}", {}) if linked else {}
            title = ((alias.get("names") or [charts[linked[0]]["title"]])[0]
                     if linked else row["title"])
            level = 4 if course == "oni" else 5
            variant = relative + (
                f" #{course} block {row['courseOccurrence']} (stars {row['level']})"
                if occurrences[(relative, course)] > 1
                else ""
            )
            db.execute(
                "INSERT INTO catalog VALUES (?,?,?,?,?,?)",
                (
                    key,
                    title,
                    row.get("titleJa"),
                    level,
                    json.dumps([k[0] for k in linked]),
                    variant,
                ),
            )
            names = {row["title"], row.get("titleJa", ""), Path(relative).stem}
            for chart_id, difficulty in linked:
                db.execute(
                    "INSERT INTO bindings VALUES (?,?,?)", (chart_id, difficulty, key)
                )
                alias = aliases["songs"].get(f"{chart_id}|{difficulty}", {})
                names.update(alias.get("names", []))
                names.update(alias.get("aliases", []))
                names.update(
                    [
                        charts[(chart_id, difficulty)]["title"],
                        charts[(chart_id, difficulty)].get("titleJa", ""),
                    ]
                )
            for name in names:
                normalized = normalize(name)
                if normalized:
                    db.execute(
                        "INSERT OR REPLACE INTO names VALUES (?,?,?)",
                        (normalized, key, 1 if linked else 0),
                    )
            if (n + 1) % 250 == 0:
                print(f"Analyzed {n + 1}/{len(rows)}", flush=True)
        db.commit()
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity check failed")
    finally:
        db.close()
        if old:
            old.close()
    (staging / "sources.json").write_bytes(encoded(file_hashes))
    file_stats = {
        p.name: {"bytes": p.stat().st_size, "sha256": sha(p.read_bytes())}
        for p in staging.iterdir()
        if p.is_file()
    }
    manifest = {
        "schemaVersion": 1,
        "buildId": build_id,
        "algorithm": ALGORITHM,
        "eseRevision": revision,
        "engineSha256": engine_hash,
        "indexSha256": sha(index_bytes),
        "mappingSha256": sha(mapping_bytes),
        "chartsSha256": sha((ROOT / "resource/charts.v1.json.gz").read_bytes()),
        "aliasesSha256": sha((ROOT / "resource/aliases.v1.json.gz").read_bytes()),
        "tjaFiles": len(files),
        "analyses": len(rows),
        "mappedCharts": sum(map(len, links.values())),
        "built": built,
        "reused": reused,
        "errors": index.get("errors", []),
        "files": file_stats,
    }
    (staging / "manifest.json").write_bytes(encoded(manifest))
    if (
        sum(p.stat().st_size for p in output.rglob("*") if p.is_file())
        > quota_mib * 1048576
    ):
        raise ValueError(
            "library quota exceeded; current pointer unchanged, staging retained"
        )
    # Existing immutable generations are the backup; no destructive replacement.
    pointer = output / f"current.{build_id}.tmp"
    pointer.write_bytes(encoded({"buildId": build_id}))
    pointer.replace(current_path)
    print(json.dumps(manifest, ensure_ascii=True), flush=True)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ese-root", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="plugin data directory / chart_library",
    )
    parser.add_argument(
        "--quota-mib", type=int, default=512, help="includes retained generations"
    )
    args = parser.parse_args()
    build(args.ese_root, args.index, args.mapping, args.output, args.quota_mib)
