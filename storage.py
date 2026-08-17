# -*- coding: utf-8 -*-
"""rt_link 本地存储层：谱面数据加载 + SQLite 成绩/缓存存储 + 空间计量。

设计目标：
- 关键信息不缺失：每条同步记录 `raw_json` 全量保真落库，同时拆结构化列便于查询。
- 查询高效：SQLite 复合索引 + 聚合结果缓存。
- 空间可监管：单文件数据库可直接计量占用，`dbstat` 出明细与可回收空页。
"""

from __future__ import annotations

import gzip
import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_charts(path) -> dict:
    """加载谱面数据（支持 .gz 与纯 .json），返回 {(song_no, level): chart}。"""
    raw = Path(path).read_bytes()
    if str(path).endswith(".gz"):
        raw = gzip.decompress(raw)
    data = json.loads(raw.decode("utf-8"))
    charts = {}
    for chart in data:
        if not isinstance(chart, dict):
            continue
        charts[(chart.get("id"), chart.get("level"))] = chart
    return charts


_SCHEMA = """
CREATE TABLE IF NOT EXISTS scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id TEXT NOT NULL,
    song_no INTEGER NOT NULL,
    level INTEGER NOT NULL,
    source TEXT NOT NULL,
    good_cnt INTEGER,
    ok_cnt INTEGER,
    ng_cnt INTEGER,
    dondaful_cnt INTEGER,
    high_score INTEGER,
    best_score_rank INTEGER,
    highscore_datetime TEXT,
    update_datetime TEXT,
    raw_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scores_lookup ON scores(player_id, song_no, level);
CREATE INDEX IF NOT EXISTS idx_scores_player ON scores(player_id);

CREATE TABLE IF NOT EXISTS rating_cache (
    player_id TEXT PRIMARY KEY,
    computed_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_state (
    player_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    last_sync_at TEXT NOT NULL,
    last_sync_ok INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value_json TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS song_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    song_no INTEGER NOT NULL,
    alias TEXT NOT NULL,
    song_title TEXT NOT NULL,
    song_title_ja TEXT,
    created_by TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    reviewed_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_alias_name ON song_aliases(alias COLLATE NOCASE);
"""


class ScoreDatabase:
    """SQLite 存储。所有方法为同步实现，由调用方用 asyncio.to_thread 包裹。"""

    def __init__(self, db_path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.commit()
            finally:
                self._conn.close()

    # -- 成绩写入 / 读取 ----------------------------------------------------
    def replace_scores(self, player_id: str, source: str, rows: list, fetched_at: str | None = None) -> int:
        """按快照替换：删除该 (player, source) 旧数据后批量插入，保证幂等。"""
        fetched_at = fetched_at or now_iso()
        with self._lock:
            self._conn.execute("DELETE FROM scores WHERE player_id=? AND source=?", (player_id, source))
            self._conn.executemany(
                """
                INSERT INTO scores
                (player_id, song_no, level, source, good_cnt, ok_cnt, ng_cnt, dondaful_cnt,
                 high_score, best_score_rank, highscore_datetime, update_datetime, raw_json, fetched_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                [
                    (
                        player_id, r["id"], r["level"], source,
                        r.get("good_cnt"), r.get("ok_cnt"), r.get("ng_cnt"), r.get("dondaful_cnt"),
                        r.get("high_score"), r.get("best_score_rank"),
                        r.get("highscore_datetime"), r.get("update_datetime"),
                        json.dumps(r.get("raw") or {}, ensure_ascii=False), fetched_at,
                    )
                    for r in rows
                ],
            )
            self._conn.commit()
            return len(rows)

    def get_scores(self, player_id: str, source: str | None = None) -> list:
        with self._lock:
            if source:
                cur = self._conn.execute(
                    "SELECT * FROM scores WHERE player_id=? AND source=? ORDER BY song_no, level",
                    (player_id, source),
                )
            else:
                cur = self._conn.execute(
                    "SELECT * FROM scores WHERE player_id=? ORDER BY song_no, level", (player_id,)
                )
            return [dict(r) for r in cur.fetchall()]

    def get_player_history(self, player_id: str, song_no: int, level: int, source: str | None = None) -> list:
        """指定谱面的历史记录（按时间升序），用于成长趋势。"""
        with self._lock:
            if source:
                cur = self._conn.execute(
                    "SELECT * FROM scores WHERE player_id=? AND song_no=? AND level=? AND source=? "
                    "ORDER BY COALESCE(update_datetime, highscore_datetime, fetched_at)",
                    (player_id, song_no, level, source),
                )
            else:
                cur = self._conn.execute(
                    "SELECT * FROM scores WHERE player_id=? AND song_no=? AND level=? "
                    "ORDER BY COALESCE(update_datetime, highscore_datetime, fetched_at)",
                    (player_id, song_no, level),
                )
            return [dict(r) for r in cur.fetchall()]

    # -- 聚合缓存 ----------------------------------------------------------
    def put_rating_cache(self, player_id: str, payload: dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO rating_cache (player_id, computed_at, payload_json) VALUES (?,?,?) "
                "ON CONFLICT(player_id) DO UPDATE SET computed_at=excluded.computed_at, "
                "payload_json=excluded.payload_json",
                (player_id, now_iso(), json.dumps(payload, ensure_ascii=False)),
            )
            self._conn.commit()

    def get_rating_cache(self, player_id: str) -> dict | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT payload_json FROM rating_cache WHERE player_id=?", (player_id,)
            )
            row = cur.fetchone()
        if not row:
            return None
        try:
            return json.loads(row["payload_json"])
        except (ValueError, TypeError):
            return None

    # -- 同步状态 ----------------------------------------------------------
    def set_sync_state(self, player_id: str, source: str, ok: bool) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO sync_state (player_id, source, last_sync_at, last_sync_ok) VALUES (?,?,?,?) "
                "ON CONFLICT(player_id) DO UPDATE SET source=excluded.source, "
                "last_sync_at=excluded.last_sync_at, last_sync_ok=excluded.last_sync_ok",
                (player_id, source, now_iso(), 1 if ok else 0),
            )
            self._conn.commit()

    def get_sync_state(self, player_id: str) -> dict | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM sync_state WHERE player_id=?", (player_id,)
            )
            row = cur.fetchone()
        return dict(row) if row else None

    # -- 通用 KV（低空间告警标记等） --------------------------------------
    def kv_get(self, key: str, default=None):
        with self._lock:
            cur = self._conn.execute("SELECT value_json FROM kv WHERE key=?", (key,))
            row = cur.fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value_json"])
        except (ValueError, TypeError):
            return default

    def kv_set(self, key: str, value) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO kv (key, value_json, updated_at) VALUES (?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                (key, json.dumps(value, ensure_ascii=False), now_iso()),
            )
            self._conn.commit()

    # -- 歌曲别名（两步确认 + 管理员审批） ---------------------------------
    def add_alias_request(self, song_no: int, alias: str, song_title: str, song_title_ja: str | None, created_by: str) -> int | None:
        """插入待审批别名；别名已存在（pending/approved，大小写不敏感）时返回 None。"""
        alias = (alias or "").strip()
        with self._lock:
            exists = self._conn.execute(
                "SELECT id FROM song_aliases WHERE alias=? COLLATE NOCASE", (alias,)
            ).fetchone()
            if exists:
                return None
            try:
                cur = self._conn.execute(
                    "INSERT INTO song_aliases "
                    "(song_no, alias, song_title, song_title_ja, created_by, status, created_at) "
                    "VALUES (?,?,?,?,?, 'pending', ?)",
                    (song_no, alias, song_title, song_title_ja, created_by, now_iso()),
                )
                self._conn.commit()
                return cur.lastrowid
            except sqlite3.IntegrityError:
                return None

    def list_pending_aliases(self) -> list:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM song_aliases WHERE status='pending' ORDER BY id"
            )
            return [dict(r) for r in cur.fetchall()]

    def approve_aliases(self, ids: list[int]) -> list[int]:
        """批量通过审批，返回实际通过的 id 列表。"""
        approved = []
        with self._lock:
            for i in ids:
                cur = self._conn.execute(
                    "UPDATE song_aliases SET status='approved', reviewed_at=? "
                    "WHERE id=? AND status='pending'",
                    (now_iso(), i),
                )
                if cur.rowcount:
                    approved.append(i)
            self._conn.commit()
        return approved

    def get_approved_aliases(self) -> dict:
        """返回 {alias_lower: song_no}，用于查询时别名解析。"""
        with self._lock:
            cur = self._conn.execute(
                "SELECT alias, song_no FROM song_aliases WHERE status='approved'"
            )
            return {r["alias"].strip().lower(): r["song_no"] for r in cur.fetchall()}

    # -- 空间计量 ----------------------------------------------------------
    def storage_stats(self) -> dict:
        with self._lock:
            page_size = self._conn.execute("PRAGMA page_size").fetchone()[0]
            page_count = self._conn.execute("PRAGMA page_count").fetchone()[0]
            freelist = self._conn.execute("PRAGMA freelist_count").fetchone()[0]
            scores_count = self._conn.execute("SELECT COUNT(*) FROM scores").fetchone()[0]
            cache_count = self._conn.execute("SELECT COUNT(*) FROM rating_cache").fetchone()[0]
            kv_count = self._conn.execute("SELECT COUNT(*) FROM kv").fetchone()[0]
            content_bytes = self._conn.execute(
                "SELECT COALESCE(SUM(LENGTH(raw_json)),0) FROM scores"
            ).fetchone()[0]
            by_source = {
                r["source"]: r["n"]
                for r in self._conn.execute(
                    "SELECT source, COUNT(*) AS n FROM scores GROUP BY source"
                ).fetchall()
            }
            by_player = {
                r["player_id"]: r["n"]
                for r in self._conn.execute(
                    "SELECT player_id, COUNT(*) AS n FROM scores GROUP BY player_id"
                ).fetchall()
            }
        db_bytes = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
        return {
            "db_bytes": db_bytes,
            "page_size": page_size,
            "page_count": page_count,
            "reclaimable_bytes": freelist * page_size,
            "scores_count": scores_count,
            "cache_count": cache_count,
            "kv_count": kv_count,
            "content_bytes": content_bytes,
            "by_source": by_source,
            "by_player": by_player,
        }

    def vacuum(self) -> dict:
        """回收空页，返回回收前后文件大小。"""
        before = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
        with self._lock:
            self._conn.execute("VACUUM")
        after = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
        return {"before_bytes": before, "after_bytes": after}
