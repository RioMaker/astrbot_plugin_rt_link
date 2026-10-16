"""Build bounded, uniquely identified single-player branch profiles with frozen v2.

Original source bytes and all master profiles remain unchanged. Mixed routes are
enumerated, not guessed from the closest note count. Run with --model-root.
"""

from __future__ import annotations

import argparse
import gzip
import itertools
import json
import sys
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.backfill_cn_constants import predictions, sha, write_gz, write_json
from scripts.tja_timeline import _read_tja, _strip_comment

VERSION = "2026-10-16-branches-v1"
# Reviewed single-player score totals; no player IDs, scores or credentials.
TARGETS = {
    (156, 5): [998],
    (182, 4): [569],
    (269, 4): [744, 753],
    (617, 4): [636],
    (627, 4): [981],
    (869, 4): [925],
    (1140, 5): [859],
    (1352, 4): [928],
    (1369, 4): [1270],
    (1404, 4): [764],
}


def reachable_routes(condition):
    """Conservative possible routes; remove only mathematically empty intervals."""
    mode, low, high = condition.split(",")
    low, high = float(low), float(high)
    if mode.lower() not in ("p", "r", "s") or low > high:
        raise ValueError("unsupported branch condition")
    maximum = 100 if mode.lower() == "p" else float("inf")
    return [
        r
        for r, valid in [
            ("N", low > 0),
            ("E", low < high and high > 0 and low <= maximum),
            ("M", high <= maximum),
        ]
        if valid
    ]


def split_body(body):
    parts, common, index = [], [], 0
    while index < len(body):
        line = _strip_comment(body[index])
        index += 1
        if line.upper().startswith("#LEVELHOLD"):
            raise ValueError("LEVELHOLD needs a separate route review")
        if not line.upper().startswith("#BRANCHSTART"):
            common.append(line)
            continue
        if common:
            parts.append(common)
            common = []
        condition = line.split(None, 1)[1]
        routes, route = {"N": [], "E": [], "M": []}, None
        while index < len(body):
            line = _strip_comment(body[index])
            marker = line.upper()
            if marker.startswith("#LEVELHOLD"):
                raise ValueError("LEVELHOLD unsupported")
            if marker.startswith("#BRANCHEND"):
                index += 1
                break
            if route and marker.startswith("#BRANCHSTART"):
                break
            index += 1
            if marker in ("#N", "#E", "#M"):
                route = marker[1]
            elif route:
                routes[route].append(line)
            else:
                common.append(line)
        if common:
            parts.append(common)
            common = []
        if not all(routes.values()):
            raise ValueError("missing branch route")
        parts.append({"condition": condition, "routes": routes})
    if common:
        parts.append(common)
    return parts


def course_body(path, wanted):
    course, active, body = "", False, []
    for raw in _read_tja(path).splitlines():
        line = _strip_comment(raw)
        if line.upper().startswith("COURSE:"):
            course = line.split(":", 1)[1].strip().lower()
        if line.upper().startswith("#START"):
            active = course == wanted
            if active and line.upper() != "#START":
                raise ValueError("not single play")
            continue
        if line.upper().startswith("#END") and active:
            return body
        if active:
            body.append(line)
    raise ValueError("course missing")


def enumerate_paths(parts):
    branches = [p for p in parts if isinstance(p, dict)]
    if not 1 <= len(branches) <= 8:
        raise ValueError("unreviewed branch count")
    choices = [reachable_routes(b["condition"]) for b in branches]
    for route in itertools.product(*choices):
        lines = []
        index = 0
        for part in parts:
            if isinstance(part, dict):
                lines.extend(part["routes"][route[index]])
                index += 1
            else:
                lines.extend(part)
        yield "".join(route), lines


def tap_count(lines):
    return sum(
        sum(c in "1234ABG" for c in line) for line in lines if not line.startswith("#")
    )


@contextmanager
def selected_path(parser_module, body, route, lines):
    """Change only the in-memory selector, keeping the pinned parser semantics."""
    original = parser_module._select_master_routes
    expected = [_strip_comment(l) for l in body]

    def select(candidate):
        if [_strip_comment(l) for l in candidate] != expected:
            return original(candidate)
        return lines, len(route), route[-1], []

    parser_module._select_master_routes = select
    try:
        yield
    finally:
        parser_module._select_master_routes = original


def build(model_root):
    sys.path.insert(0, str(model_root))
    import joblib
    from ml.export_deploy import validate_model
    from taiko_model import taiko_patterns, tja_features
    from taiko_model.parsers import get_parser

    from profile_data import bpm_band

    proof = json.loads((ROOT / "scripts/data/cn_constant_backfill.json").read_bytes())
    reviews = {(r["id"], r["level"]): r for r in proof["charts"]}
    model_path = model_root / "ml/artifacts/feature-profile-model.v2.joblib"
    dataset_raw = (model_root / "ml/artifacts/profile-dataset.v1.json").read_bytes()
    assert sha(model_path.read_bytes()) == proof["model"]["modelSha256"]
    assert sha(dataset_raw) == proof["model"]["datasetSha256"]
    bundle = joblib.load(model_path)
    validate_model(bundle, json.loads(dataset_raw), sha(dataset_raw))
    raw = (ROOT / "resource" / proof["sourceArchive"]).read_bytes()
    assert sha(raw) == proof["sourceArchiveSha256"]
    masters = {
        (r["id"], r["level"]): r
        for r in json.loads(
            gzip.decompress((ROOT / "resource/charts.v1.json.gz").read_bytes())
        )
    }
    _, parse5 = get_parser("v5")
    result = []
    audit = []
    with (
        zipfile.ZipFile(__import__("io").BytesIO(raw)) as archive,
        tempfile.TemporaryDirectory() as work,
    ):
        directory = Path(work)
        for key, totals in TARGETS.items():
            review = reviews[key]
            data = archive.read(review["path"])
            assert sha(data) == review["sha256"] and "双打" not in review["title"]
            path = directory / Path(review["path"]).name
            path.write_bytes(data)
            body = course_body(path, review["course"])
            parts = split_body(body)
            original = next(
                c
                for c in tja_features.parse_tja(path, directory)
                if c.course == review["course"]
            )
            assert original.fingerprint == review["fingerprintV4"]
            model_input = lambda c, stars=float(review["stars"]): {
                "features": {
                    **c.features,
                    "star_level": stars,
                    "course_is_edit": float(c.course == "edit"),
                },
                "rhythmProfile": c.rhythm_profile,
            }
            assert (
                predictions(bundle, [model_input(original)])[0]
                == masters[key]["feature"]
            )
            entry = {"id": key[0], "level": key[1], "profiles": [], "ambiguous": []}
            for total in totals:
                candidates = {}
                for route, lines in enumerate_paths(parts):
                    if tap_count(lines) != total:
                        continue
                    with selected_path(tja_features, body, route, lines):
                        c = next(
                            c
                            for c in tja_features.parse_tja(path, directory)
                            if c.course == review["course"]
                        )
                        assert c.total_notes == total
                        old_band = taiko_patterns._bpm_band
                        taiko_patterns._bpm_band = bpm_band
                        try:
                            c5 = next(
                                c
                                for c in parse5(path, directory)
                                if c.course == review["course"]
                            )
                        finally:
                            taiko_patterns._bpm_band = old_band
                    # Feature equality includes long-note/balloon details as well as taps.
                    signature = sha(
                        json.dumps(
                            [
                                c.fingerprint,
                                c5.fingerprint,
                                c.features,
                                c.rhythm_profile,
                                c5.rhythm_profile,
                            ],
                            sort_keys=True,
                        ).encode()
                    )
                    if signature not in candidates:
                        candidates[signature] = {"chart": c, "config": c5, "routes": []}
                    candidates[signature]["routes"].append(route)
                evidence = {
                    "id": key[0],
                    "level": key[1],
                    "title": review["title"],
                    "totalNotes": total,
                    "sourcePath": review["path"],
                    "sourceSha256": review["sha256"],
                    "sourceUrl": review["source"]["url"],
                    "conditions": [
                        p["condition"] for p in parts if isinstance(p, dict)
                    ],
                    "candidateCount": len(candidates),
                    "paths": [r for v in candidates.values() for r in v["routes"]],
                }
                if len(candidates) != 1:
                    entry["ambiguous"].append(
                        {
                            "totalNotes": total,
                            "candidateCount": len(candidates),
                            "paths": evidence["paths"],
                        }
                    )
                    evidence["status"] = "ambiguous" if candidates else "unmatched"
                else:
                    value = next(iter(candidates.values()))
                    c = value["chart"]
                    c5 = value["config"]
                    feature = predictions(bundle, [model_input(c)])[0]
                    profile = {
                        "key": f"{key[0]}-{key[1]}-{total}",
                        "totalNotes": total,
                        "paths": value["routes"],
                        "feature": feature,
                        "configurationRhythmProfile": {
                            field: c5.rhythm_profile.get(field, [])
                            for field in ("cells", "arrangementCells")
                        },
                        "fingerprintV4": c.fingerprint,
                        "fingerprintV5": c5.fingerprint,
                        "sourceSha256": review["sha256"],
                    }
                    entry["profiles"].append(profile)
                    evidence.update(
                        status="verified",
                        aiConstant=feature["aiConstant"],
                        fingerprintV4=c.fingerprint,
                        fingerprintV5=c5.fingerprint,
                        warnings=list(c.warnings),
                    )
                audit.append(evidence)
            result.append(entry)
    output = {
        "schemaVersion": 1,
        "version": VERSION,
        "chartsSha256": sha((ROOT / "resource/charts.v1.json.gz").read_bytes()),
        "sourceArchiveSha256": proof["sourceArchiveSha256"],
        "model": proof["model"],
        "charts": result,
    }
    stats = write_gz(ROOT / "resource/branch_profiles.v1.json.gz", output)
    write_json(
        ROOT / "resource/branch_profiles.manifest.json",
        {
            "schemaVersion": 1,
            "version": VERSION,
            "chartsSha256": output["chartsSha256"],
            **stats,
        },
    )
    manifest = json.loads((ROOT / "resource/charts.manifest.json").read_bytes())
    manifest["branchProfilesVersion"] = VERSION
    manifest["branchProfilesSha256"] = stats["sha256"]
    manifest["catalogVersion"] = (
        manifest["modelId"] + "+cn-" + manifest["backfillVersion"] + "+" + VERSION
    )
    write_json(ROOT / "resource/charts.manifest.json", manifest)
    write_json(
        ROOT / "docs/branch-note-audit-2026-10-16.json",
        {
            "version": VERSION,
            "retrained": False,
            "masterProfilesUnchanged": True,
            "charts": audit,
        },
    )
    for e in audit:
        print(e["id"], e["totalNotes"], e["status"], e["paths"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-root", type=Path, required=True)
    build(parser.parse_args().model_root.resolve())
