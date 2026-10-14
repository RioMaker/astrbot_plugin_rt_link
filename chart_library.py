"""Read-only, indexed public TJA references shared by all players.

Only a requested chart is decompressed. An eight-chart LRU is bounded, version
changes invalidate it, and synchronous IO is called through asyncio.to_thread.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import sqlite3
import threading
import zlib
from collections import OrderedDict
from pathlib import Path

if __package__:
    from .song_alias import normalize
else:
    from song_alias import normalize


def _file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ChartLibrary:
    def __init__(self, root, charts_hash=None):
        self.root = Path(root)
        self.charts_hash = charts_hash
        self._build_id = None
        self._manifest = {}
        self._cache = OrderedDict()
        self._lock = threading.RLock()
        self._db_path = None

    def invalidate(self):
        """Recheck an installed/repaired generation on the next read."""
        with self._lock:
            self._build_id = None
            self._cache.clear()

    def _refresh(self):
        pointer = self.root / "current.json"
        if not pointer.is_file():
            raise ValueError(
                "谱面分析库尚未安装；管理员需导入 chart_library 数据目录。"
            )
        build_id = json.loads(pointer.read_bytes()).get("buildId", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", build_id):
            raise ValueError("谱面分析库版本指针无效。")
        if build_id != self._build_id:
            directory = (self.root / "versions" / build_id).resolve()
            if not directory.is_relative_to(self.root.resolve()):
                raise ValueError("谱面分析库路径无效。")
            manifest = json.loads((directory / "manifest.json").read_bytes())
            if (
                manifest.get("schemaVersion") != 1
                or manifest.get("buildId") != build_id
            ):
                raise ValueError("不支持的谱面分析库版本。")
            if self.charts_hash and manifest.get("chartsSha256") != self.charts_hash:
                raise ValueError("谱面分析库与当前歌曲目录版本不一致，请重建分析库。")
            db_path = directory / "analysis.sqlite3"
            if (
                not db_path.is_file()
                or db_path.stat().st_size
                != manifest["files"]["analysis.sqlite3"]["bytes"]
            ):
                raise ValueError("谱面分析库文件缺失或大小不符。")
            # Verify once per generation, never scan the library per query.
            if _file_sha256(db_path) != manifest["files"]["analysis.sqlite3"]["sha256"]:
                raise ValueError("谱面分析库校验失败。")
            self._manifest, self._db_path, self._build_id = manifest, db_path, build_id
            self._cache.clear()

    @staticmethod
    def _candidate(row):
        return {
            "chartKey": "ese:" + row[0],
            "title": row[1],
            "titleJa": row[2],
            "level": row[3],
            "songIds": json.loads(row[4]),
            "variant": row[5],
        }

    def _resolve(self, db, song, level):
        fields = "c.key,c.title,c.title_ja,c.level,c.song_ids,c.relative_path"
        if song.startswith("ese:"):
            if not re.fullmatch(r"ese:[0-9a-f]{24}", song):
                raise ValueError("无效的 chartKey。")
            rows = db.execute(
                f"SELECT {fields} FROM catalog c WHERE c.key=?", (song[4:],)
            ).fetchall()
        elif song.isdigit():
            if not 0 < int(song) < 2**63:
                raise ValueError("歌曲 ID 超出有效范围。")
            rows = db.execute(
                f"SELECT {fields} FROM bindings b JOIN catalog c ON c.key=b.key WHERE b.song_id=?",
                (int(song),),
            ).fetchall()
        else:
            norm = normalize(song)
            if not norm:
                raise ValueError("请提供曲名、别名、歌曲 ID 或返回的 chartKey。")
            rows = db.execute(
                f"SELECT DISTINCT {fields},n.priority FROM names n JOIN catalog c ON c.key=n.key WHERE n.name=? AND (?=0 OR c.level=?) ORDER BY n.priority DESC,c.key",
                (norm, level, level),
            ).fetchall()
            if rows:
                priorities = {
                    difficulty: max(r[-1] for r in rows if r[3] == difficulty)
                    for difficulty in {r[3] for r in rows}
                }
                rows = [r[:-1] for r in rows if r[-1] == priorities[r[3]]]
            else:
                # Names contain only normalized letters/numbers; LIKE wildcard
                # input cannot expand beyond literal substring matching.
                rows = db.execute(
                    f"SELECT DISTINCT {fields} FROM names n JOIN catalog c ON c.key=n.key WHERE n.name LIKE ? AND (?=0 OR c.level=?) ORDER BY c.key LIMIT 9",
                    ("%" + norm + "%", level, level),
                ).fetchall()
        return [self._candidate(row) for row in rows if not level or row[3] == level]

    def _load(self, db, key):
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        row = db.execute("SELECT payload FROM charts WHERE key=?", (key,)).fetchone()
        if not row:
            raise ValueError("谱面索引对应的分析结果缺失。")
        data = json.loads(gzip.decompress(row[0]))
        if data.get("schemaVersion") != 1 or data.get("chartKey") != key:
            raise ValueError("谱面分析结果身份校验失败。")
        self._cache[key] = data
        while len(self._cache) > 8:
            self._cache.popitem(last=False)
        return data

    def query(
        self,
        song,
        level=0,
        route="",
        detail="summary",
        start_measure=0,
        end_measure=0,
        offset=0,
        limit=8,
    ):
        """Return a bounded JSON-ready result without accessing player data."""
        try:
            if not isinstance(song, str) or len(song) > 200 or not song.strip():
                raise ValueError("曲名必须为 1–200 字符。")
            for name, value in (
                ("level", level),
                ("start_measure", start_measure),
                ("end_measure", end_measure),
                ("offset", offset),
                ("limit", limit),
            ):
                if isinstance(value, bool) or not isinstance(value, int):
                    raise TypeError(f"{name} 必须是整数。")
            if level not in (0, 4, 5) or detail not in (
                "summary",
                "segments",
                "features",
            ):
                raise ValueError(
                    "仅支持鬼/里（4/5）；detail 为 summary、segments 或 features。"
                )
            if (
                offset < 0
                or offset > 100000
                or not 1 <= limit <= 20
                or start_measure < 0
                or end_measure < 0
                or (end_measure and end_measure < start_measure)
            ):
                raise ValueError("分页或小节范围无效；limit 为 1–20，小节从 1 开始。")
            route = route.strip().upper() if isinstance(route, str) else "invalid"
            route = {"普通": "N", "玄人": "E", "达人": "M", "SINGLE": "single"}.get(
                route, route
            )
            if route not in ("", "N", "E", "M", "single"):
                raise ValueError("route 为 N、E、M 或 single。")
            with self._lock:
                self._refresh()
                db = sqlite3.connect(self._db_path.as_uri() + "?mode=ro", uri=True)
                try:
                    candidates = self._resolve(db, song.strip(), level)
                    if len(candidates) != 1:
                        return {
                            "status": "ambiguous" if candidates else "not_found",
                            "candidates": candidates[:8],
                            "message": "请指定难度或使用候选 chartKey；不自动混用同名变体。"
                            if candidates
                            else "暂无匹配的鬼/里谱面分析。",
                        }
                    candidate = candidates[0]
                    data = self._load(db, candidate["chartKey"][4:])
                finally:
                    db.close()
                selected_route = route or data["featureRoute"]
                if selected_route not in data["routes"]:
                    return {
                        "status": "invalid_route",
                        "availableRoutes": list(data["routes"]),
                    }
                selected = data["routes"][selected_route]
                result = {
                    "status": "ok",
                    **candidate,
                    "buildId": self._build_id,
                    "eseRevision": self._manifest["eseRevision"],
                    "algorithm": data["algorithm"],
                    "source": data["source"],
                    "route": selected_route,
                    "availableRoutes": list(data["routes"]),
                    "timeOrigin": data["timeOrigin"],
                    "timeReliable": selected["timeReliable"],
                    "warnings": sorted(set(data["warnings"] + selected["warnings"])),
                    "limitations": [
                        "公共谱面参数，不是玩家实测或过关概率。",
                        "密度/配色突出小节不等同于完整难度排名；整曲特征仅对应 featureRoute。",
                    ],
                    "featureRoute": data["featureRoute"],
                    "definitions": {
                        "time": "seconds from #START; not audio time",
                        "density": "tap notes only; yellow rolls/balloons excluded",
                        "peak2s": "maximum count in a half-open 2s window / 2",
                        "continuousRun": "consecutive hits with gaps <= 0.25 seconds",
                        "triplets": "d=don, k=ka, b=dual; overlapping adjacent triples",
                        "segments": "one measure each; runs may continue across measure boundaries",
                    },
                    "mapping": "verified"
                    if candidate["songIds"]
                    else "ESE-only; not verified against the game catalog",
                }
                if detail == "summary":
                    result["summary"] = selected["summary"]
                    result["measureCount"] = len(selected["measures"])
                    result["hotspots"] = selected["hotspots"]
                    wanted = {
                        n for values in selected["hotspots"].values() for n in values
                    }
                    result["segments"] = [
                        m for m in selected["measures"] if m["measure"] in wanted
                    ][:limit]
                elif detail == "segments":
                    measures = [
                        m
                        for m in selected["measures"]
                        if m["measure"] >= (start_measure or 1)
                        and (not end_measure or m["measure"] <= end_measure)
                    ]
                    result.update(
                        segments=measures[offset : offset + limit],
                        total=len(measures),
                        nextOffset=offset + limit
                        if offset + limit < len(measures)
                        else None,
                    )
                else:
                    if selected_route != data["featureRoute"]:
                        raise ValueError(
                            "整曲特征仅对应 featureRoute；其他路线请查询 segments。"
                        )
                    pairs = sorted(data["features"].items())
                    result.update(
                        features=dict(pairs[offset : offset + limit]),
                        total=len(pairs),
                        nextOffset=offset + limit
                        if offset + limit < len(pairs)
                        else None,
                    )
                return result
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            sqlite3.Error,
            EOFError,
            zlib.error,
        ) as error:
            return {"status": "unavailable", "message": str(error)}

    def status(self):
        with self._lock:
            try:
                self._refresh()
                return {
                    "available": True,
                    "buildId": self._build_id,
                    "analyses": self._manifest["analyses"],
                    "tjaFiles": self._manifest["tjaFiles"],
                    "bytes": sum(v["bytes"] for v in self._manifest["files"].values()),
                }
            except (OSError, ValueError, KeyError, TypeError):
                return {"available": False}
