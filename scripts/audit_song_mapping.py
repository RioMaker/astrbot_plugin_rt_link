"""Audit all game IDs, source titles, difficulties and packaged ESE bindings.

Authenticated input is optional. Only aggregate validation counts are exported;
credentials, player identities and individual score records are never copied.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.audit_song_aliases import audit as audit_aliases
from scripts.song_identity import exact_candidates, source_names, title_matches
from song_alias import load_aliases, match_names, normalize
from storage import load_charts


def read(path):
    return json.loads(Path(path).read_bytes())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def positive(value):
    return type(value) is int and value > 0


def notes_from_sakura(row, level):
    values = row.get("max_combo") or []
    value = values[level - 1] if len(values) >= level else None
    return value if positive(value) else None


def audit_scores(payload, songs, aliases):
    counts = Counter()
    records = payload["data"]["playedRecords"]["scoreInfo"]
    seen = set()
    for record in records:
        sid, level = record["song_no"], record["level"]
        key = (sid, level)
        counts["records"] += 1
        counts["duplicateKeys"] += key in seen
        seen.add(key)
        song = songs.get(str(sid))
        if not song:
            counts["missingIds"] += 1
            continue
        counts["matchedIds"] += 1
        meta = song["levels"].get(str(level))
        if not meta:
            counts["missingLevels"] += 1
        detail = record.get("song_detail") or {}
        if detail.get("id") is not None and detail["id"] != sid:
            counts["detailIdMismatches"] += 1
        for field in ("song_name", "song_name_jp"):
            if detail.get(field):
                counts["titlesChecked"] += 1
                counts["unmatchedTitles"] += sid not in match_names(
                    aliases, detail[field]
                )
        observed = sum(
            record.get(field, 0) for field in ("good_cnt", "ok_cnt", "ng_cnt")
        )
        if observed > 0 and meta and positive(meta.get("totalNotes")):
            counts["noteComparisons"] += 1
            counts["noteDifferences"] += observed != meta["totalNotes"]
        else:
            counts["notesNotComparable"] += 1
    return {
        **dict(counts),
        "uniqueSongs": len({sid for sid, _ in seen}),
        "scope": "本次授权拉取的国服成绩快照；仅汇总，不代表全曲库均有实玩验证",
        "noteRule": "良可不可合计受分歧路线、双打侧别等影响；差异不单独证明ID错误",
    }


def build_report(sakura_path, kinoko_path, index_path, library, score_path=None):
    report = audit_aliases()
    identities = read(ROOT / "scripts/data/song_names.json")
    songs = identities["songs"]
    aliases = load_aliases(ROOT / "resource/aliases.v1.json.gz")
    ratings = load_charts(ROOT / "resource/charts.v1.json.gz")
    sakura_rows, kinoko_rows = read(sakura_path)["songs"], read(kinoko_path)["songs"]
    sakura = {s["id"]: s for s in sakura_rows}
    kinoko = {s["game_id"]: s for s in kinoko_rows}
    if len(sakura) != len(sakura_rows) or len(kinoko) != len(kinoko_rows):
        raise ValueError("duplicate source game IDs")
    expected_ids = (
        set(kinoko)
        | {sid for sid, _ in ratings}
        | {sid for sid, row in sakura.items() if row.get("shelf_status") != 2}
    )
    if expected_ids != {int(sid) for sid in songs}:
        raise ValueError("identity catalog does not cover source game IDs")
    index = read(index_path)
    if index["eseRevision"] != identities["sources"]["ese"]["revision"]:
        raise ValueError("ESE revision mismatch")
    source_index = {
        (x["relativePath"], x["course"], x["fingerprint"]): x for x in index["charts"]
    }
    title_index = {}
    for pos, chart in enumerate(index["charts"]):
        for name in {normalize(chart.get("title")), normalize(chart.get("titleJa"))} - {
            ""
        }:
            title_index.setdefault((name, chart["course"]), set()).add(pos)
    generation = (
        Path(library) / "versions" / read(Path(library) / "current.json")["buildId"]
    )
    manifest = read(generation / "manifest.json")
    if manifest["aliasesSha256"] != sha(ROOT / "resource/aliases.v1.json.gz"):
        raise ValueError("library aliases are stale")
    if manifest["chartsSha256"] != sha(ROOT / "resource/charts.v1.json.gz"):
        raise ValueError("library ratings are stale")
    for filename, info in manifest["files"].items():
        if sha(generation / filename) != info["sha256"]:
            raise ValueError(f"library file hash mismatch: {filename}")
    bound, analyses, integrity = {}, {}, []
    with sqlite3.connect(
        f"file:{(generation / 'analysis.sqlite3').as_posix()}?mode=ro", uri=True
    ) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity failure")
        for key, blob in db.execute("SELECT key,payload FROM charts"):
            payload = json.loads(gzip.decompress(blob))
            source = payload["source"]
            ref = source_index.get(
                (source["path"], payload["course"], source["fingerprint"])
            )
            if ref is None or payload["level"] != (
                4 if payload["course"] == "oni" else 5
            ):
                raise ValueError(f"invalid ESE analysis: {key}")
            analyses[key] = (payload, ref)
        for sid, level, key in db.execute("SELECT song_id,level,key FROM bindings"):
            if str(sid) not in songs or str(level) not in songs[str(sid)]["levels"]:
                raise ValueError(f"orphan binding: {sid}|{level}")
            payload, ref = analyses[key]
            if payload["level"] != level:
                raise ValueError(f"wrong bound course: {sid}|{level}")
            song = songs[str(sid)]
            meta = song["levels"][str(level)]
            if ref["totalNotes"] != meta["totalNotes"]:
                raise ValueError(f"wrong bound note count: {sid}|{level}")
            if not title_matches(ref, song):
                raise ValueError(f"binding lacks independent title: {sid}|{level}")
            if positive(meta["stars"]) and meta["stars"] != ref["level"]:
                integrity.append(
                    {
                        "id": sid,
                        "level": level,
                        "title": song["title"],
                        "category": "已绑定谱面星级差异",
                        "values": f"曲库 {meta['stars']} / ESE {ref['level']}",
                        "decision": "保留原映射并标注差异；不将星级差异自动解释为同谱或错谱",
                    }
                )
            bound[(sid, level)] = (key, ref)
        catalog = list(db.execute("SELECT key,level,song_ids FROM catalog"))
        if len(catalog) != len(analyses):
            raise ValueError("analysis/catalog row count mismatch")
        for key, level, ids in catalog:
            if set(json.loads(ids)) != {
                sid for (sid, lv), (k, _) in bound.items() if lv == level and k == key
            }:
                raise ValueError(f"catalog reverse binding mismatch: {key}")
    issues = list(integrity)
    source_differences, level_differences, chart_rows = [], [], []
    added_keys = {
        (x["songNo"], x["level"]) for x in identities["eseSupplementalMappings"]
    }
    for sid_text, song in songs.items():
        sid = int(sid_text)
        sr, kr = sakura.get(sid, {}), kinoko.get(sid, {})
        if sr.get("shelf_status") == 0 and song["title"] != sr["song_name"]:
            raise ValueError(f"current CN display mismatch: {sid}")
        for source, names in (
            ("sakura", [sr.get("song_name"), sr.get("song_name_jp")]),
            ("kinoko", list(kr.get("title", {}).values())),
        ):
            for name in names:
                if name and name != "-" and sid not in match_names(aliases, name):
                    raise ValueError(f"unreachable public title: {source}:{sid}:{name}")
        for level_text, meta in song["levels"].items():
            level = int(level_text)
            ss = sr.get(f"level_{level}")
            sn = notes_from_sakura(sr, level)
            ks = next(
                (c.get("stars") for c in kr.get("charts", []) if c["level"] == level),
                None,
            )
            for field, source, value, local in (
                ("物量", "Sakura", sn, meta["totalNotes"]),
                ("星级", "Sakura", ss, meta["stars"]),
                ("星级", "菌菌", ks, meta["stars"]),
            ):
                if positive(value) and positive(local) and value != local:
                    entry = {
                        "id": sid,
                        "level": level,
                        "title": song["title"],
                        "category": f"{source}{field}差异",
                        "values": f"本地 {local} / {source} {value}",
                        "decision": "保留各源值；复核版本、分歧与计数口径，暂不覆盖评级",
                    }
                    source_differences.append(entry)
            if sr and not positive(ss) and positive(ks):
                level_differences.append(
                    {
                        "id": sid,
                        "level": level,
                        "title": song["title"],
                        "category": "难度收录范围差异",
                        "values": f"Sakura 未列出 / 菌菌 {ks}★",
                        "decision": "保留跨区身份；未确认该难度在国服开放，不凭歌曲状态推断",
                    }
                )
            if level not in (4, 5):
                continue
            hit = bound.get((sid, level))
            positions = set()
            if not hit:
                for name in source_names(song):
                    positions.update(
                        title_index.get((name, "oni" if level == 4 else "edit"), set())
                    )
            title_candidates = [index["charts"][p] for p in sorted(positions)]
            exact = exact_candidates(title_candidates, song, level) if not hit else []
            if hit:
                reason = (
                    "已绑定（有星级差异）"
                    if any(i["id"] == sid and i["level"] == level for i in integrity)
                    else "已绑定"
                )
            elif not positive(meta["totalNotes"]):
                reason = "缺少可交叉核对的物量"
            elif len(exact) > 1:
                reason = "同名同物量存在多个源谱"
            elif not title_candidates:
                reason = "无完整源名对应的该难度TJA"
            else:
                reason = "物量或星级不一致，暂缓绑定"
            if len(exact) == 1 and not hit:
                raise ValueError(f"unique safe binding was omitted: {sid}|{level}")
            chart_rows.append(
                {
                    "id": sid,
                    "level": level,
                    "title": song["title"],
                    "titleJa": song["titleJa"],
                    "cnStatus": song["cnStatus"],
                    "stars": meta["stars"],
                    "identityNotes": meta["totalNotes"],
                    "sakuraNotes": sn,
                    "ratingNotes": ratings.get((sid, level), {}).get("totalNotes"),
                    "rated": (sid, level) in ratings,
                    "bound": bool(hit),
                    "status": reason,
                    "cnDifficultyListed": positive(ss),
                    "kinokoStars": ks,
                    "esePath": hit[1]["relativePath"] if hit else None,
                    "eseStars": hit[1]["level"] if hit else None,
                    "fingerprint": hit[1]["fingerprint"] if hit else None,
                    "supplemental": (sid, level) in added_keys,
                    "candidates": [
                        {
                            "path": c["relativePath"],
                            "stars": c["level"],
                            "notes": c["totalNotes"],
                            "fingerprint": c["fingerprint"],
                            "warnings": c.get("warnings", []),
                        }
                        for c in title_candidates
                    ],
                }
            )
    issues.extend(source_differences)
    issues.extend(level_differences)
    for row in report["songs"]:
        row["kinokoId"] = songs[str(row["id"])]["kinokoId"]
        row["sakuraId"] = row["id"] if row["id"] in sakura else None
        local = [c for c in chart_rows if c["id"] == row["id"]]
        row["boundCharts"] = sum(c["bound"] for c in local)
        row["identityCharts"] = len(local)
        row["issues"] = [i["category"] for i in issues if i["id"] == row["id"]]
    report.update(
        {
            "auditDate": "2026-10-15",
            "charts": chart_rows,
            "pending": [c for c in chart_rows if not c["bound"]],
            "issues": issues,
            "liveValidation": audit_scores(read(score_path), songs, aliases)
            if score_path
            else None,
            "libraryBuildId": manifest["buildId"],
            "sourceFiles": {
                name: {"sha256": sha(path)}
                for name, path in (
                    ("sakura", sakura_path),
                    ("kinoko", kinoko_path),
                    ("eseIndex", index_path),
                )
            },
        }
    )
    report["summary"].update(
        {
            "allDifficultyIdentities": sum(len(s["levels"]) for s in songs.values()),
            "mappedCharts": len(bound),
            "unmappedCharts": len(report["pending"]),
            "eseAnalyses": len(analyses),
            "catalogValueDifferences": len(source_differences),
            "difficultyPresenceDifferences": len(level_differences),
            "boundStarDifferences": len(integrity),
            "pendingReasons": dict(Counter(c["status"] for c in report["pending"])),
            "currentCnListedCharts": sum(
                c["cnStatus"] == "current" and c["cnDifficultyListed"]
                for c in chart_rows
            ),
            "currentCnListedBoundCharts": sum(
                c["cnStatus"] == "current" and c["cnDifficultyListed"] and c["bound"]
                for c in chart_rows
            ),
        }
    )
    return report


def render(report):
    template = (ROOT / "scripts/song_mapping_report.html").read_text(encoding="utf-8")
    return template.replace(
        "__REPORT_DATA__",
        json.dumps(report, ensure_ascii=False).replace("<", "\\u003c"),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("sakura", "kinoko", "index", "library"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--score-snapshot", type=Path)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "docs/song-mapping-audit-2026-10-15"
    )
    args = parser.parse_args()
    report = build_report(
        args.sakura, args.kinoko, args.index, args.library, args.score_snapshot
    )
    args.output.with_suffix(".json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.output.with_suffix(".html").write_text(render(report), encoding="utf-8")
    print(
        json.dumps(
            {"summary": report["summary"], "liveValidation": report["liveValidation"]},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
