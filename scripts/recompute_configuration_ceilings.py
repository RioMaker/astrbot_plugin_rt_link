"""Recompute ceilings from embedded verified BPM profiles; no TJA/model rebuild."""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from profile_data import BANDS, CONFIGURATION_ALGORITHM
from rating import calculate_ai_values, calculate_rhythm_ability
from storage import load_charts


def rebuild(output):
    resource = ROOT / "resource"
    source = resource / "profile_configurations.v1.json.gz"
    payload = json.loads(gzip.decompress(source.read_bytes()))
    master = resource / "charts.v1.json.gz"
    if payload.get("schemaVersion") != 1 or payload.get("bands") != [
        list(b) for b in BANDS
    ]:
        raise ValueError("Unsupported configuration schema or BPM bands")
    if payload["chartsSha256"] != hashlib.sha256(master.read_bytes()).hexdigest():
        raise ValueError("Configuration profiles do not match the fixed chart resource")
    charts = load_charts(master)
    catalog = {}
    for profile in payload["profiles"]:
        key = profile["id"], profile["level"]
        chart = copy.deepcopy(charts[key])
        if key in catalog or chart["totalNotes"] != profile["totalNotes"]:
            raise ValueError(f"Duplicate or mismatched chart profile: {key}")
        chart["feature"]["rhythmProfile"] = profile["rhythmProfile"]
        catalog[key] = chart
    perfect = []
    for (song, level), chart in catalog.items():
        score = {
            "id": song,
            "level": level,
            "title": chart["title"],
            "goodCount": chart["totalNotes"],
            "okCount": 0,
            "ngCount": 0,
            "dondafulComboCount": 1,
        }
        perfect.append(
            {
                **score,
                **calculate_ai_values(chart, score),
                "chart": chart,
                "feature": chart["feature"],
            }
        )
    full = {
        cell["key"]: cell
        for cell in calculate_rhythm_ability(perfect, catalog)["cells"]
    }
    for cell in payload["cells"]:
        cell["ceiling"] = full.get(cell["key"], {}).get("score")
    payload["version"] = "bpm7-2026-10-26-cap-v1"
    payload["algorithmVersion"] = CONFIGURATION_ALGORITHM
    compressed = gzip.compress(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        mtime=0,
    )
    manifest = json.loads(
        (resource / "profile_configurations.manifest.json").read_text(encoding="utf-8")
    )
    manifest.update(
        version=payload["version"],
        algorithmVersion=CONFIGURATION_ALGORITHM,
        sha256=hashlib.sha256(compressed).hexdigest(),
        compressedBytes=len(compressed),
        rawBytes=len(gzip.decompress(compressed)),
        baseline="Full-good catalog under fixed-constant-capped nonlinear player Rating; verified profiles unchanged",
    )
    output.mkdir(parents=True, exist_ok=True)
    (output / "profile_configurations.v1.json.gz").write_bytes(compressed)
    (output / "profile_configurations.manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "profiles": len(catalog),
                "cells": len(payload["cells"]),
                "sha256": manifest["sha256"],
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "resource")
    rebuild(parser.parse_args().output)
