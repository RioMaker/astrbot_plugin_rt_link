"""Freeze public song identities separately from the rating/model catalog.

Inputs are public Sakura/kinoko catalogs and the already reviewed ESE mapping.
No player data, API credentials, rating constants or inferred IDs are stored.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.build_aliases import read_tja_title
from scripts.song_identity import exact_candidates
from song_alias import normalize

DATA_VERSION = "2026-10-15.1"
SOURCE_URLS = {
    "sakura": "https://viewer.sakura-bot.cn/api/content/songs",
    "kinoko": "https://kinoko.zorua.cn/api/scores/catalog?schema_version=3",
    "rating": "resource/charts.v1.json.gz",
    "ese": "https://ese.tjadataba.se/ESE/ESE.git",
}


def read(path):
    raw = Path(path).read_bytes()
    return json.loads(gzip.decompress(raw) if str(path).endswith(".gz") else raw)


def keyed(rows, field):
    result = {}
    for row in rows:
        sid = row[field]
        if type(sid) is not int or sid <= 0 or sid in result:
            raise ValueError(f"invalid/duplicate game ID: {sid}")
        result[sid] = row
    return result


def build(sakura_path, kinoko_path, ese_root, mapping_path, index_path):
    sakura = keyed(read(sakura_path)["songs"], "id")
    kinoko = keyed(read(kinoko_path)["songs"], "game_id")
    charts = read(ROOT / "resource/charts.v1.json.gz")
    rated = {}
    for row in charts:
        rated.setdefault(row["id"], []).append(row)
    mapping, index = read(mapping_path), read(index_path)
    if mapping["eseRevision"] != index["eseRevision"]:
        raise ValueError("ESE revision mismatch")
    excluded = [
        {
            "sourceId": sid,
            "title": row["song_name"],
            "reason": "Sakura other shelf; no confirmed game_id in kinoko/rating",
        }
        for sid, row in sakura.items()
        if row.get("shelf_status") == 2 and sid not in kinoko and sid not in rated
    ]
    sakura = {
        sid: row
        for sid, row in sakura.items()
        if sid not in {entry["sourceId"] for entry in excluded}
    }
    songs, differences = {}, []
    for sid in sorted(set(sakura) | set(kinoko) | set(rated)):
        s, k, r = sakura.get(sid, {}), kinoko.get(sid, {}), rated.get(sid, [])
        names = {}

        def add(value, source, *, names=names):
            if isinstance(value, str) and value.strip() and value != "-":
                names.setdefault(value.strip(), [])
                if source not in names[value.strip()]:
                    names[value.strip()].append(source)

        # Current mainland title first. Retired songs retain the previously
        # localized title, rather than being renamed to an archive's romaji.
        title = (
            (s.get("song_name") if s.get("shelf_status") == 0 else None)
            or (r[0]["title"] if r else s.get("song_name"))
            or k.get("title", {}).get("zh")
            or k.get("title", {}).get("jp")
        )
        jp = (
            (r[0].get("titleJa") if r else None)
            or s.get("song_name_jp")
            or k.get("title", {}).get("jp")
        )
        if not title:
            raise ValueError(f"missing title: {sid}")
        for row in r:
            add(row["title"], "rating:title")
            add(row.get("titleJa"), "rating:titleJa")
        add(s.get("song_name"), "sakura:cn")
        add(s.get("song_name_jp"), "sakura:jp")
        add(k.get("title", {}).get("zh"), "kinoko:zh")
        add(k.get("title", {}).get("jp"), "kinoko:jp")
        if s and k and normalize(s.get("song_name_jp")) != normalize(k["title"]["jp"]):
            differences.append(
                {
                    "songNo": sid,
                    "sakura": s["song_name_jp"],
                    "kinoko": k["title"]["jp"],
                    "decision": "same_game_id; retain source spelling and version qualifiers",
                }
            )
        levels = {
            row["level"]: {"stars": None, "totalNotes": row["totalNotes"]} for row in r
        }
        for level in range(1, 6):
            stars = s.get(f"level_{level}")
            if type(stars) is int and stars > 0:
                notes = (s.get("max_combo") or [None] * 5)[level - 1]
                levels.setdefault(
                    level,
                    {
                        "stars": stars,
                        "totalNotes": notes if type(notes) is int else None,
                    },
                )
                levels[level]["stars"] = stars
        for row in k.get("charts", []):
            if type(row.get("stars")) is int and row["stars"] > 0:
                levels.setdefault(
                    row["level"], {"stars": row["stars"], "totalNotes": None}
                )
        songs[str(sid)] = {
            "title": title,
            "titleJa": jp,
            "genre": s.get("type") or (r[0].get("genre") if r else k.get("genre_name")),
            "cnStatus": {0: "current", 1: "archive", 2: "other"}.get(
                s.get("shelf_status"), "unknown"
            ),
            "kinokoId": k.get("kinoko_id"),
            "names": names,
            "levels": {str(level): data for level, data in sorted(levels.items())},
        }

    # Keep proven mappings; extend only with an exact independent source title, course,
    # note count AND stars, and one source chart. Ambiguous variants stay out.
    linked = {}
    for row in mapping["mappings"]:
        if row.get("status") == "matched" and row.get("selected"):
            linked[(row["songNo"], row["level"])] = row["selected"]
    extra = []
    for sid, song in songs.items():
        for level in (4, 5):
            key = (int(sid), level)
            data = song["levels"].get(str(level))
            if not data:
                continue
            if key not in linked:
                matches = exact_candidates(index["charts"], song, level)
                if len(matches) == 1:
                    selected = {
                        key: matches[0][key]
                        for key in (
                            "relativePath",
                            "course",
                            "fingerprint",
                            "totalNotes",
                        )
                    }
                    linked[key] = selected
                    extra.append(
                        {
                            "songNo": int(sid),
                            "level": level,
                            "selected": selected,
                            "evidence": "game_id+catalog_title+level+stars+notes+unique_ese_chart",
                        }
                    )
            selected = linked.get(key)
            if selected:
                title, jp = read_tja_title(Path(ese_root) / selected["relativePath"])
                for name, tag in ((title, "ese:title"), (jp, "ese:titleJa")):
                    if name:
                        sources = song["names"].setdefault(name, [])
                        if tag not in sources:
                            sources.append(tag)
    sources = {
        name: {
            "url": SOURCE_URLS[name],
            "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        }
        for name, path in (
            ("sakura", sakura_path),
            ("kinoko", kinoko_path),
            ("rating", ROOT / "resource/charts.v1.json.gz"),
            ("ese", mapping_path),
        )
    }
    sources["ese"].update(
        revision=index["eseRevision"],
        indexSha256=hashlib.sha256(Path(index_path).read_bytes()).hexdigest(),
    )
    return {
        "schemaVersion": 1,
        "dataVersion": DATA_VERSION,
        "retrievedDate": "2026-10-15",
        "sources": sources,
        "sourceDifferences": differences,
        "excludedSourceEntries": excluded,
        "eseSupplementalMappings": extra,
        "songs": songs,
    }


def catalog_charts(payload):
    return [
        {
            "id": int(sid),
            "level": int(level),
            "title": song["title"],
            "titleJa": song["titleJa"],
            "names": list(song["names"]),
            **data,
        }
        for sid, song in payload["songs"].items()
        for level, data in song["levels"].items()
    ]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("sakura", "kinoko", "ese-root", "mapping", "index"):
        parser.add_argument("--" + arg, required=True, type=Path)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "scripts/data/song_names.json"
    )
    args = parser.parse_args()
    payload = build(args.sakura, args.kinoko, args.ese_root, args.mapping, args.index)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "songs": len(payload["songs"]),
                "sourceDifferences": len(payload["sourceDifferences"]),
                "extraESE": len(payload["eseSupplementalMappings"]),
            },
            ensure_ascii=False,
        )
    )
