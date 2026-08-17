# -*- coding: utf-8 -*-
"""rt_link 核心服务层：绑定管理、菌菌同步/转义落库、玩家 Rating 画像与查询。

与 AstrBot 解耦，可独立测试。依赖 rating.py（算法）与 storage.py（SQLite 存储）。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections import defaultdict
from datetime import datetime

# 包加载（AstrBot）时用相对导入；本地直接运行 service.py 时回退到绝对导入。
if __package__:
    from . import rating as rating_mod
    from .api_client import KinokoClient, KinokoAPIError
    from .report_image import render_report_image
    from .storage import ScoreDatabase, load_charts
else:
    import rating as rating_mod
    from api_client import KinokoClient, KinokoAPIError
    from report_image import render_report_image
    from storage import ScoreDatabase, load_charts

DIFFICULTY_NAMES = {
    1: "梅（简单）",
    2: "竹（一般）",
    3: "松（困难）",
    4: "鬼（魔王）",
    5: "里鬼（里魔王）",
}


def difficulty_label(level) -> str:
    name = DIFFICULTY_NAMES.get(level)
    return f"难度{level}·{name}" if name else f"难度{level}"


# 评价等级提示（best_score_rank 越高越好，8 为全良/咚大福）
RANK_HINT = {
    8: "全良/咚大福",
    7: "极优秀",
    6: "优秀",
    5: "良好",
    4: "及格",
    3: "通过",
    2: "可",
    1: "不可",
}


def _rank_text(rank) -> str:
    if rank is None:
        return "-"
    hint = RANK_HINT.get(int(rank))
    return f"{rank}" + (f"（{hint}）" if hint else "")


# 难度别名（用户输入 / LLM 传参都归一化到这里）
DIFFICULTY_ALIASES = {
    1: {"1", "梅", "简单", "easy", "かんたん"},
    2: {"2", "竹", "一般", "普通", "normal", "ふつう"},
    3: {"3", "松", "困难", "hard", "むずかしい"},
    4: {"4", "鬼", "魔王", "oni", "mania", "おに"},
    5: {"5", "里", "里鬼", "里魔王", "ura", "うら"},
}

# 组合名前缀（长前缀优先）：如「鬼夏祭」「里夏祭」→ (难度, 曲名关键词)
DIFFICULTY_PREFIXES = [
    ("里魔王", 5), ("里鬼", 5), ("魔王", 4),
    ("里", 5), ("鬼", 4),
    ("困难", 3), ("松", 3),
    ("一般", 2), ("普通", 2), ("竹", 2),
    ("简单", 1), ("梅", 1),
]


def parse_difficulty(text) -> int | None:
    """把难度别名/数字解析为 1-5；0/空/全部/不限 → None（表示不筛选）。"""
    if text is None:
        return None
    s = str(text).strip().lower()
    if s in ("", "0", "全部", "不限", "all"):
        return None
    for level, names in DIFFICULTY_ALIASES.items():
        if s in names:
            return level
    if s.isdigit():
        lvl = int(s)
        return lvl if 1 <= lvl <= 5 else None
    return None


def parse_song_query(text) -> tuple[int | None, str]:
    """从「鬼夏祭」「里夏祭」「夏祭」中拆出 (难度, 曲名关键词)。"""
    t = (text or "").strip()
    if not t:
        return None, ""
    for prefix, level in DIFFICULTY_PREFIXES:
        if t.startswith(prefix):
            rest = t[len(prefix):].strip()
            if rest:
                return level, rest
    return None, t


class BindingsStore:
    """绑定存储抽象接口。"""

    async def load(self) -> dict:
        raise NotImplementedError

    async def save(self, data: dict) -> None:
        raise NotImplementedError


class MemoryBindingsStore(BindingsStore):
    def __init__(self, initial: dict | None = None):
        self._data = dict(initial or {})

    async def load(self) -> dict:
        return dict(self._data)

    async def save(self, data: dict) -> None:
        self._data = dict(data)


class JsonFileBindingsStore(BindingsStore):
    def __init__(self, path: str):
        self.path = path

    async def load(self) -> dict:
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    async def save(self, data: dict) -> None:
        d = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(d, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)


class _NullLogger:
    def warning(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


def _slim_song(row: dict) -> dict:
    """从分析结果 record 中提取最简曲目引用。"""
    return {
        "id": row.get("id"),
        "level": row.get("level"),
        "title": row.get("title"),
        "rating": round(row.get("rating") or 0, 2),
    }


def _slim_result(result: dict) -> dict:
    """把 analyze() 全量结果压缩为可缓存 JSON（去掉 chart/feature 大对象）。"""
    records = []
    for r in result["records"]:
        records.append({
            "id": r.get("id"),
            "level": r.get("level"),
            "title": r.get("title"),
            "titleJa": (r.get("chart") or {}).get("titleJa"),
            "genre": (r.get("chart") or {}).get("genre"),
            "rating": r.get("rating"),
            "accuracy": r.get("accuracy"),
            "constant": r.get("constant"),
            "aiConstant": r.get("aiConstant"),
            "aiConstantRaw": r.get("aiConstantRaw"),
            "highScore": r.get("highScore"),
            "bestScoreRank": r.get("bestScoreRank"),
            "fullComboCount": r.get("fullComboCount"),
            "dondafulComboCount": r.get("dondafulComboCount"),
            "goodCount": r.get("goodCount"),
            "okCount": r.get("okCount"),
            "ngCount": r.get("ngCount"),
            "clearCount": r.get("clearCount"),
            "updatedAt": r.get("updatedAt"),
            "aiV2": r.get("aiV2"),
        })

    def slim_family(f):
        return {
            "key": f["key"],
            "score": round(f["score"], 2),
            "charts": f["charts"],
            "exposure": round(f.get("exposure") or 0, 3),
            "best": [_slim_song(b) for b in f.get("best", [])],
        }

    feature_ability = {
        "families": [slim_family(f) for f in result["featureAbility"]["families"]],
        "strengths": [slim_family(f) for f in result["featureAbility"]["strengths"]],
        "weaknesses": [slim_family(f) for f in result["featureAbility"]["weaknesses"]],
        "matchedCharts": result["featureAbility"]["matchedCharts"],
    }

    def slim_cell(c):
        return {
            "key": c.get("key"), "pattern": c.get("pattern"), "bpmBand": c.get("bpmBand"),
            "score": round(c.get("score") or 0, 2), "charts": c.get("charts"),
            "compoundRatio": round(c.get("compoundRatio") or 0, 3),
            "averageBpm": round(c.get("averageBpm") or 0, 1),
            "best": [_slim_song(b) for b in c.get("best", [])],
        }

    rhythm_ability = {
        "cells": [slim_cell(c) for c in result["rhythmAbility"]["cells"]],
        "weakest": [slim_cell(c) for c in result["rhythmAbility"]["weakest"]],
        "visual": {
            k: slim_cell(v) for k, v in result["rhythmAbility"]["visual"].items()
        },
    }

    return {
        "_ts": time.time(),
        "summary": {k: round(v, 2) for k, v in result["summary"].items()},
        "ourTaikoV1": {
            "summary": {k: round(v, 2) for k, v in result["ourTaikoV1"]["summary"].items()},
            "chartCount": result["ourTaikoV1"]["chartCount"],
        },
        "counts": result["counts"],
        "meta": result["meta"],
        "records": records,
        "featureAbility": feature_ability,
        "rhythmAbility": rhythm_ability,
    }


class ScoreService:
    """rt_link 核心业务逻辑（绑定 + 同步 + 评级画像）。"""

    def __init__(
        self,
        store: BindingsStore,
        client_factory,
        charts: dict | None = None,
        score_db: ScoreDatabase | None = None,
        default_server: str = "cn",
        sync_ttl: int = 300,
        quota_mb: int = 256,
        warn_ratio: float = 0.8,
        report_dir: str | None = None,
        logger=None,
    ):
        self.store = store
        self._client_factory = client_factory
        self.charts = charts or {}
        self.db = score_db
        self.default_server = default_server
        self.sync_ttl = sync_ttl
        self.quota_mb = quota_mb
        self.warn_ratio = warn_ratio
        self.report_dir = report_dir
        self._logger = logger or _NullLogger()

    def _client(self, apikey: str) -> KinokoClient:
        return self._client_factory(apikey)

    # ------------------------------------------------------------------
    # 绑定管理（沿用原逻辑）
    # ------------------------------------------------------------------
    async def bind(self, qq, apikey, player_id, server="") -> tuple[bool, str]:
        if not qq:
            return False, "无法获取你的 QQ 号。"
        if not apikey.startswith("tk_"):
            return False, "apikey 应以 tk_ 开头，请检查后重试。"
        server = server or self.default_server
        try:
            await asyncio.to_thread(
                self._client(apikey).hiroba_recent,
                player_id=player_id,
                server=server,
            )
        except KinokoAPIError as e:
            return False, f"绑定失败：无法用该 apikey 查询玩家 {player_id}（{e}）"

        bindings = await self.store.load()
        bindings[qq] = {"apikey": apikey, "player_id": player_id, "server": server}
        await self.store.save(bindings)
        return True, f"绑定成功：QQ {qq} ↔ 玩家 {player_id}（{server}）。现在可查询成绩。"

    async def unbind(self, qq) -> tuple[bool, str]:
        bindings = await self.store.load()
        if qq in bindings:
            del bindings[qq]
            await self.store.save(bindings)
            return True, "已解绑。"
        return False, "你还没有绑定记录。"

    async def list_bindings(self) -> str:
        bindings = await self.store.load()
        if not bindings:
            return "暂无绑定记录。"
        lines = ["当前绑定："]
        for qq, b in bindings.items():
            lines.append(f"  QQ {qq} → 玩家 {b.get('player_id')}（{b.get('server')}）")
        return "\n".join(lines)

    async def _binding(self, qq) -> dict | None:
        return (await self.store.load()).get(qq)

    # ------------------------------------------------------------------
    # 同步 / 分析
    # ------------------------------------------------------------------
    async def _sync(self, qq) -> tuple[bool, str, dict | None]:
        b = await self._binding(qq)
        if not b:
            return False, "你还没有绑定菌菌账号。请先发送：/rtlink bind <apikey> <player_id> [server]", None
        apikey = b["apikey"]
        player_id = str(b.get("player_id") or "")
        server = b.get("server") or self.default_server
        client = self._client(apikey)

        kinoko, hiroba = await asyncio.gather(
            asyncio.to_thread(client.kinoko, player_id, server),
            asyncio.to_thread(client.hiroba, player_id, server),
            return_exceptions=True,
        )

        errors = {}
        if isinstance(kinoko, BaseException):
            errors["kinoko"] = str(kinoko)
            kinoko = None
        if isinstance(hiroba, BaseException):
            errors["hiroba"] = str(hiroba)
            hiroba = None

        if kinoko is not None:
            try:
                await asyncio.to_thread(self._store_payload, qq, "kinoko", kinoko)
            except Exception:
                kinoko = None
        if hiroba is not None:
            try:
                await asyncio.to_thread(self._store_payload, qq, "hiroba", hiroba)
            except Exception:
                hiroba = None

        payload_for_rating = kinoko if kinoko is not None else hiroba

        if payload_for_rating is None:
            detail = "；".join(f"{k}: {v}" for k, v in errors.items()) or "未知错误"
            return False, f"查询失败：{detail}", None

        try:
            result = await asyncio.to_thread(rating_mod.analyze, payload_for_rating, self.charts)
        except rating_mod.RatingError as e:
            return False, f"评级计算失败：{e}", None

        if not result["records"]:
            return False, "该账号暂无鬼/里（魔王/里魔王）谱面成绩，无法评级。请先在太鼓中游玩鬼级谱面。", None

        slim = _slim_result(result)
        if self.db is not None:
            await asyncio.to_thread(self.db.put_rating_cache, qq, slim)
            await asyncio.to_thread(self.db.set_sync_state, qq, "kinoko" if kinoko is not None else "hiroba", True)

        # 空间告警检查（同步后触发）
        warning = await self.check_storage_warning()
        if warning:
            self._logger.warning(warning)
        return True, "", slim

    def _store_payload(self, player_id: str, source: str, payload: dict) -> int:
        normalized = rating_mod.normalize_scores(payload)
        rows = []
        for r in normalized["rows"]:
            rows.append({
                "id": r["id"],
                "level": r["level"],
                "good_cnt": r["goodCount"],
                "ok_cnt": r["okCount"],
                "ng_cnt": r["ngCount"],
                "dondaful_cnt": r["dondafulComboCount"],
                "high_score": r["highScore"],
                "best_score_rank": r["bestScoreRank"],
                "highscore_datetime": (r.get("raw") or {}).get("highscore_datetime"),
                "update_datetime": r.get("updatedAt"),
                "raw": r.get("raw") or {},
            })
        if self.db is None:
            return len(rows)
        return self.db.replace_scores(player_id, source, rows)

    async def _get_analysis(self, qq) -> tuple[dict | None, str]:
        if not qq:
            return None, "无法识别你的 QQ 号。"
        if not await self._binding(qq):
            return None, "你还没有绑定菌菌账号。请先发送：/rtlink bind <apikey> <player_id> [server]"
        if self.db is not None:
            cache = await asyncio.to_thread(self.db.get_rating_cache, qq)
            if cache and time.time() - float(cache.get("_ts") or 0) < self.sync_ttl:
                return cache, ""
        ok, msg, slim = await self._sync(qq)
        if not ok:
            return None, msg
        return slim, ""

    def _records(self, analysis: dict) -> list:
        return analysis.get("records") or []

    @staticmethod
    def _norm_level(level):
        """0 或 None 表示「全部鬼/里」，其余返回原值（由调用方决定是否合法）。"""
        return None if level in (0, None) else level

    # ------------------------------------------------------------------
    # 空间监管
    # ------------------------------------------------------------------
    async def check_storage_warning(self) -> str | None:
        if self.db is None:
            return None
        stats = await asyncio.to_thread(self.db.storage_stats)
        quota_bytes = self.quota_mb * 1024 * 1024
        ratio = stats["db_bytes"] / quota_bytes if quota_bytes else 0.0
        if ratio >= self.warn_ratio:
            await asyncio.to_thread(self.db.kv_set, "low_space_warning", True)
            return f"rt_link 存储将满：已用 {stats['db_bytes']/1048576:.1f}MiB / 配额 {self.quota_mb}MiB（{ratio*100:.0f}%），请管理员清理。"
        await asyncio.to_thread(self.db.kv_set, "low_space_warning", False)
        return None

    async def storage_status_text(self) -> str:
        if self.db is None:
            return "本地存储未启用。"
        stats = await asyncio.to_thread(self.db.storage_stats)
        quota_bytes = self.quota_mb * 1024 * 1024
        remaining = max(0, quota_bytes - stats["db_bytes"])
        ratio = stats["db_bytes"] / quota_bytes if quota_bytes else 0.0
        by_source = "，".join(f"{k} {v} 条" for k, v in stats["by_source"].items()) or "无"
        by_player = "，".join(f"{k} {v} 条" for k, v in stats["by_player"].items()) or "无"
        warn = "⚠️ 存储将满，建议清理！\n" if ratio >= self.warn_ratio else ""
        lines = [
            warn + f"用量 {stats['db_bytes']/1048576:.1f}MiB / 配额 {self.quota_mb}MiB（剩余 {remaining/1048576:.1f}MiB，{ratio*100:.0f}%）",
            f"成绩记录：{stats['scores_count']} 条（{by_source}）",
            f"评级缓存：{stats['cache_count']} 个玩家",
            f"内容字节：{stats['content_bytes']/1048576:.1f}MiB ｜ 可回收空页：{stats['reclaimable_bytes']/1024:.0f}KiB",
            f"按玩家：{by_player}",
            "清理：/rtlink cleanup 释放数据库空页（VACUUM）。",
        ]
        return "\n".join(lines)

    async def low_space_warning_text(self) -> str:
        """只读检查：接近配额时返回提示文本，否则返回空串。"""
        if self.db is None:
            return ""
        stats = await asyncio.to_thread(self.db.storage_stats)
        quota_bytes = self.quota_mb * 1024 * 1024
        ratio = stats["db_bytes"] / quota_bytes if quota_bytes else 0.0
        if ratio >= self.warn_ratio:
            return f"⚠️ rt_link 存储将满（{ratio*100:.0f}%），请管理员及时清理。\n"
        return ""

    async def cleanup(self) -> str:
        if self.db is None:
            return "本地存储未启用。"
        result = await asyncio.to_thread(self.db.vacuum)
        return f"已执行 VACUUM：{result['before_bytes']/1048576:.2f}MiB → {result['after_bytes']/1048576:.2f}MiB"

    # ------------------------------------------------------------------
    # 查询：单曲（沿用 /rtlink score 语义）
    # ------------------------------------------------------------------
    async def _get_alias_map(self) -> dict:
        if self.db is None:
            return {}
        return await asyncio.to_thread(self.db.get_approved_aliases)

    def _song_index(self) -> dict:
        """{song_no: {title, titleJa, genre}}，来自谱面数据。"""
        idx = {}
        for (song_no, _level), chart in self.charts.items():
            if song_no not in idx:
                idx[song_no] = {
                    "title": chart.get("title"),
                    "titleJa": chart.get("titleJa"),
                    "genre": chart.get("genre"),
                }
        return idx

    def _resolve_song(self, target: str) -> tuple[dict | None, str | None]:
        """按精准 ID 或曲名解析歌曲；返回 (song, 提示)。song 为 None 时提示非空。"""
        idx = self._song_index()
        t = (target or "").strip()
        if t.isdigit():
            song_no = int(t)
            info = idx.get(song_no)
            if info is None:
                return None, f"歌曲 ID {song_no} 不在谱面库中。"
            return {"id": song_no, "title": info.get("title") or f"Song {song_no}", "titleJa": info.get("titleJa")}, None
        q = t.lower()
        matches = []
        for song_no, info in idx.items():
            hay = " | ".join(str(x or "") for x in (info.get("title"), info.get("titleJa"))).lower()
            if q in hay:
                matches.append({"id": song_no, "title": info.get("title") or f"Song {song_no}", "titleJa": info.get("titleJa")})
        if not matches:
            return None, f"未找到与「{target}」匹配的歌曲，请用更精确的名称或歌曲 ID。"
        if len(matches) == 1:
            return matches[0], None
        options = "、".join(f"《{m['title']}》(ID {m['id']})" for m in matches[:8])
        return None, f"「{target}」匹配到多首歌曲：{options}。请用更精确的名称或 ID 重新提交。"

    async def _resolve_query_to_records(self, records: list, query: str) -> list:
        """别名优先，其次按 title/titleJa 模糊匹配。"""
        q = (query or "").strip()
        if not q:
            return []
        alias_map = await self._get_alias_map()
        song_no = alias_map.get(q.lower())
        if song_no is not None:
            return [r for r in records if r.get("id") == song_no]
        return self._match_records(records, q)

    async def query_score_text(self, qq, song_name, level=None) -> str:
        analysis, err = await self._get_analysis(qq)
        if err:
            return err
        prefix_level, clean = parse_song_query(song_name)
        lvl = level if level is not None else prefix_level
        records = self._records(analysis)
        matched = await self._resolve_query_to_records(records, clean)
        if lvl is not None:
            if lvl not in (4, 5):
                return f"{difficulty_label(lvl)} 不在评级范围内（本系统仅评估鬼/里）。"
            matched = [r for r in matched if r.get("level") == lvl]
        if not matched:
            return f"未找到与「{clean or song_name}」匹配的曲目，试试更精确的曲名或别名。"
        return self._format_song_rows(matched)

    @staticmethod
    def _match_records(records: list, query: str) -> list:
        q = (query or "").strip().lower()
        matched = []
        for r in records:
            hay = " | ".join(str(x or "") for x in (r.get("title"), r.get("titleJa"))).lower()
            if q and q in hay:
                matched.append(r)
        return matched

    def _format_song_rows(self, records: list) -> str:
        by_song = defaultdict(list)
        for r in records:
            by_song[r.get("id")].append(r)
        lines = []
        for _, recs in by_song.items():
            recs.sort(key=lambda x: x.get("level", 0))
            title = recs[0].get("title") or str(recs[0].get("id"))
            title_ja = recs[0].get("titleJa")
            head = f"《{title}》"
            if title_ja and title_ja != title:
                head += f"（{title_ja}）"
            lines.append(head)
            for r in recs:
                lines.append(
                    "  {}：Rating {}｜精度 {:.1f}%｜定数 {}｜评价 {}｜最高分 {}｜全连 {}｜咚大福 {}".format(
                        difficulty_label(r.get("level")),
                        round(r.get("rating") or 0, 2),
                        (r.get("accuracy") or 0) * 100,
                        r.get("constant") or r.get("aiConstant"),
                        _rank_text(r.get("bestScoreRank")),
                        r.get("highScore"),
                        r.get("fullComboCount") or 0,
                        r.get("dondafulComboCount") or 0,
                    )
                )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 查询：评级画像（LLM 工具）
    # ------------------------------------------------------------------
    def _dimension_lines(self, summary: dict, names: dict) -> str:
        parts = []
        for key, name in names.items():
            if key in summary:
                parts.append(f"{name} {summary[key]}")
        return "｜".join(parts)

    async def get_rating_text(self, qq) -> str:
        analysis, err = await self._get_analysis(qq)
        if err:
            return err
        summary = analysis["summary"]
        meta = analysis.get("meta") or {}
        records = self._records(analysis)
        oni = sum(1 for r in records if r.get("level") == 4)
        ura = sum(1 for r in records if r.get("level") == 5)
        lines = [
            f"综合 Rating {summary.get('rating', 0)}",
            f"七维能力：" + self._dimension_lines(summary, rating_mod.AI_DIMENSION_NAMES),
            f"覆盖谱面：{len(records)} 张（魔王 {oni} / 里魔王 {ura}）｜玩家 {meta.get('playerId')}（{meta.get('server')}）",
            "说明：本 Rating 仅评估鬼/里（魔王/里魔王）谱面，1–3 难度不参与评级。",
        ]
        return "\n".join(lines)

    async def generate_report_image(self, qq) -> tuple[bool, str]:
        """生成鼓点画像图片，返回 (成功, 图片路径 或 错误信息)。"""
        analysis, err = await self._get_analysis(qq)
        if err:
            return False, err
        out_dir = self.report_dir
        if not out_dir and self.db is not None:
            out_dir = os.path.dirname(os.path.abspath(self.db.db_path))
        if not out_dir:
            out_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(out_dir, f"report_{qq}.png")
        try:
            await asyncio.to_thread(render_report_image, analysis, path)
        except Exception as e:
            self._logger.error(f"生成报告图片失败：{e}")
            return False, f"生成报告图片失败：{e}"
        return True, path

    async def get_profile_text(self, qq) -> str:
        analysis, err = await self._get_analysis(qq)
        if err:
            return err
        summary = analysis["summary"]
        fa = analysis["featureAbility"]
        strengths = "、".join(
            f"{rating_mod.AI_DIMENSION_NAMES.get(f['key'], f['key'])} {f['score']}" for f in fa["strengths"]
        ) or "样本不足"
        weaknesses = "、".join(
            f"{rating_mod.AI_DIMENSION_NAMES.get(f['key'], f['key'])} {f['score']}" for f in fa["weaknesses"]
        ) or "样本不足"
        records = self._records(analysis)
        full_combo = sum(1 for r in records if (r.get("fullComboCount") or 0) > 0)
        dondaful = sum(1 for r in records if (r.get("dondafulComboCount") or 0) > 0)
        lines = [
            f"综合 Rating {summary.get('rating', 0)} ｜ 谱面 {len(records)} 张 ｜ 全连 {full_combo} ｜ 咚大福（全良）{dondaful}",
            f"七维能力：" + self._dimension_lines(summary, rating_mod.AI_DIMENSION_NAMES),
            f"强项：{strengths}",
            f"弱项：{weaknesses}",
        ]
        return "\n".join(lines)

    async def get_rhythm_weakness_text(self, qq) -> str:
        analysis, err = await self._get_analysis(qq)
        if err:
            return err
        ra = analysis["rhythmAbility"]
        weakest = ra["weakest"]
        if not weakest:
            return "节奏画像样本不足（至少 3 张同节奏型谱面才会形成结论）。"
        lines = ["节奏型弱项（按处理 Rating 从低到高，前几项最该练）："]
        for c in weakest[:5]:
            pattern = c.get("pattern")
            bpm = c.get("bpmBand")
            compound = "含复合" if (c.get("compoundRatio") or 0) > 0.5 else ""
            refs = "、".join(f"《{b['title']}》" for b in c.get("best", [])[:3])
            lines.append(
                f"  {pattern} @{bpm}BPM{compound}：处理 Rating {c['score']}（{c['charts']} 张）"
                + (f"｜参考曲目：{refs}" if refs else "")
            )
        return "\n".join(lines)

    def _filter_records(self, records, level=None, query=None, constant_min=None, constant_max=None, rank_min=None):
        result = records
        if level is not None:
            if level not in (4, 5):
                return None  # 仅鬼/里参与评级
            result = [r for r in result if r.get("level") == level]
        if query:
            result = self._match_records(result, query)
        if constant_min is not None:
            result = [r for r in result if (r.get("constant") or 0) >= constant_min]
        if constant_max is not None:
            result = [r for r in result if (r.get("constant") or 0) <= constant_max]
        if rank_min is not None:
            result = [r for r in result if (r.get("bestScoreRank") or 0) >= rank_min]
        return result

    async def get_difficulty_stats_text(self, qq, level=None) -> str:
        level = self._norm_level(level)
        analysis, err = await self._get_analysis(qq)
        if err:
            return err
        records = self._records(analysis)
        if level is not None and level not in (4, 5):
            return f"{difficulty_label(level)} 不在评级范围内（本系统仅评估鬼/里）。"
        filtered = self._filter_records(records, level=level)
        if not filtered:
            return "该难度暂无成绩。"
        total = len(filtered)
        full_combo = sum(1 for r in filtered if (r.get("fullComboCount") or 0) > 0)
        dondaful = sum(1 for r in filtered if (r.get("dondafulComboCount") or 0) > 0)
        avg_rating = sum(r.get("rating") or 0 for r in filtered) / total
        max_constant = max((r.get("constant") or 0 for r in filtered), default=0)
        avg_acc = sum(r.get("accuracy") or 0 for r in filtered) / total
        return (
            f"{difficulty_label(level) if level else '鬼/里'}：{total} 张｜"
            f"全连 {full_combo}（{full_combo/total*100:.0f}%）｜咚大福 {dondaful}｜"
            f"平均 Rating {avg_rating:.2f}｜平均精度 {avg_acc*100:.1f}%｜最高定数 {max_constant}"
        )

    async def get_rank_distribution_text(self, qq, level=None) -> str:
        level = self._norm_level(level)
        analysis, err = await self._get_analysis(qq)
        if err:
            return err
        records = self._records(analysis)
        if level is not None and level not in (4, 5):
            return f"{difficulty_label(level)} 不在评级范围内（本系统仅评估鬼/里）。"
        filtered = self._filter_records(records, level=level)
        if not filtered:
            return "该难度暂无成绩。"
        dist = defaultdict(list)
        for r in filtered:
            dist[r.get("bestScoreRank") or 0].append(r)
        lines = ["评价等级分布："]
        for rank in sorted(dist.keys(), reverse=True):
            items = dist[rank]
            rep = "、".join(f"《{r['title']}》" for r in sorted(items, key=lambda x: -(x.get("rating") or 0))[:3])
            lines.append(f"  评价 {_rank_text(rank)}：{len(items)} 张" + (f"（如 {rep}）" if rep else ""))
        return "\n".join(lines)

    async def get_genre_strength_text(self, qq) -> str:
        analysis, err = await self._get_analysis(qq)
        if err:
            return err
        records = self._records(analysis)
        by_genre = defaultdict(list)
        for r in records:
            by_genre[r.get("genre") or "未知"].append(r)
        lines = ["分区强弱（按平均 Rating）："]
        rows = []
        for genre, items in by_genre.items():
            avg = sum(r.get("rating") or 0 for r in items) / len(items)
            fc = sum(1 for r in items if (r.get("fullComboCount") or 0) > 0)
            rows.append((avg, genre, len(items), fc))
        rows.sort(reverse=True)
        for avg, genre, count, fc in rows:
            lines.append(f"  {genre}：平均 Rating {avg:.2f} ｜ {count} 张 ｜ 全连 {fc}")
        return "\n".join(lines)

    async def get_accuracy_summary_text(self, qq, level=None) -> str:
        level = self._norm_level(level)
        analysis, err = await self._get_analysis(qq)
        if err:
            return err
        records = self._records(analysis)
        if level is not None and level not in (4, 5):
            return f"{difficulty_label(level)} 不在评级范围内（本系统仅评估鬼/里）。"
        filtered = self._filter_records(records, level=level)
        if not filtered:
            return "该难度暂无成绩。"
        accs = sorted((r.get("accuracy") or 0 for r in filtered), reverse=True)
        n = len(accs)
        avg = sum(accs) / n
        low = accs[int(n * 0.25)]
        high = accs[int(n * 0.75)]
        best = sorted(filtered, key=lambda r: -(r.get("accuracy") or 0))[:3]
        worst = sorted(filtered, key=lambda r: (r.get("accuracy") or 0))[:3]
        lines = [
            f"精度概况：平均 {avg*100:.1f}% ｜ 中位段 {low*100:.1f}%~{high*100:.1f}%",
            "精度最高：" + "、".join(f"《{r['title']}》{r['accuracy']*100:.1f}%" for r in best),
            "精度最低：" + "、".join(f"《{r['title']}》{r['accuracy']*100:.1f}%" for r in worst),
        ]
        return "\n".join(lines)

    async def search_scores_text(self, qq, query=None, level=None, constant_min=None, constant_max=None, rank_min=None) -> str:
        level = self._norm_level(level)
        analysis, err = await self._get_analysis(qq)
        if err:
            return err
        if level is not None and level not in (4, 5):
            return f"{difficulty_label(level)} 不在评级范围内（本系统仅评估鬼/里）。"
        records = self._records(analysis)
        # 组合名（如「鬼夏祭」）+ 别名解析
        prefix_level, clean = parse_song_query(query or "")
        eff_level = level if level is not None else prefix_level
        if clean:
            records = await self._resolve_query_to_records(records, clean)
        if eff_level is not None:
            if eff_level not in (4, 5):
                return f"{difficulty_label(eff_level)} 不在评级范围内（本系统仅评估鬼/里）。"
            records = [r for r in records if r.get("level") == eff_level]
        if constant_min is not None:
            records = [r for r in records if (r.get("constant") or 0) >= constant_min]
        if constant_max is not None:
            records = [r for r in records if (r.get("constant") or 0) <= constant_max]
        if rank_min is not None:
            records = [r for r in records if (r.get("bestScoreRank") or 0) >= rank_min]
        if not records:
            return "没有符合条件的结果。"
        records = sorted(records, key=lambda r: -(r.get("rating") or 0))
        if len(records) > 30:
            head = records[:30]
            return self._format_song_rows(head) + f"\n（共 {len(records)} 条，仅显示前 30，可缩小筛选范围）"
        return self._format_song_rows(records)

    async def get_song_full_text(self, qq, song_name) -> str:
        analysis, err = await self._get_analysis(qq)
        if err:
            return err
        prefix_level, clean = parse_song_query(song_name)
        matched = await self._resolve_query_to_records(self._records(analysis), clean)
        if prefix_level is not None:
            matched = [r for r in matched if r.get("level") == prefix_level]
        if not matched:
            return f"未找到与「{clean or song_name}」匹配的曲目。"
        # 取匹配到的全部难度（鬼/里）
        by_id = defaultdict(list)
        for r in matched:
            by_id[r.get("id")].append(r)
        lines = []
        for _, recs in by_id.items():
            recs.sort(key=lambda x: x.get("level"))
            title = recs[0].get("title")
            title_ja = recs[0].get("titleJa")
            head = f"《{title}》" + (f"（{title_ja}）" if title_ja and title_ja != title else "")
            lines.append(head)
            for r in recs:
                ai = r.get("aiV2") or {}
                dims = "｜".join(
                    f"{rating_mod.AI_DIMENSION_NAMES[k]} {round(v, 2)}"
                    for k, v in ai.items() if k in rating_mod.AI_DIMENSION_NAMES
                )
                lines.append(
                    f"  {difficulty_label(r.get('level'))}：Rating {round(r.get('rating') or 0,2)}｜精度 {(r.get('accuracy') or 0)*100:.1f}%｜定数 {r.get('constant')}"
                )
                lines.append(f"      七维：{dims}")
        return "\n".join(lines)

    @staticmethod
    def _updated_ts(record: dict) -> float:
        s = str(record.get("updatedAt") or "").replace(" ", "T")
        try:
            return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").timestamp()
        except Exception:
            return 0.0

    async def get_recent_scores_text(self, qq, days=1) -> str:
        analysis, err = await self._get_analysis(qq)
        if err:
            return err
        records = self._records(analysis)
        if not records:
            return "暂无成绩记录。"
        cutoff = time.time() - int(days or 1) * 86400
        recent = [r for r in records if self._updated_ts(r) >= cutoff]
        if not recent:
            recent = records
        recent = sorted(recent, key=self._updated_ts, reverse=True)[:10]
        return self._format_song_rows(recent)

    async def get_growth_trend_text(self, qq, song_name=None) -> str:
        if self.db is None:
            return "本地存储未启用，无法查询成长趋势。"
        analysis, err = await self._get_analysis(qq)
        if err:
            return err
        matched = self._match_records(self._records(analysis), song_name) if song_name else None
        if song_name and not matched:
            return f"未找到与「{song_name}」匹配的曲目。"
        targets = matched[:1] if matched else sorted(self._records(analysis), key=lambda r: -(r.get("rating") or 0))[:1]
        if not targets:
            return "暂无成绩记录。"
        target = targets[0]
        # 成长趋势优先用 kinoko 全历史；无 kinoko 时回退 hiroba 最新快照。
        history = await asyncio.to_thread(
            self.db.get_player_history, qq, target["id"], target["level"], "kinoko"
        )
        if not history:
            history = await asyncio.to_thread(
                self.db.get_player_history, qq, target["id"], target["level"], "hiroba"
            )
        if len(history) < 2:
            return f"《{target['title']}》只有 {len(history)} 条历史记录，不足以判断趋势。"
        lines = [f"《{target['title']}》成长趋势（共 {len(history)} 条）："]
        for h in history:
            raw = json.loads(h.get("raw_json") or "{}")
            total = (raw.get("good_cnt") or 0) + (raw.get("ok_cnt") or 0) + (raw.get("ng_cnt") or 0)
            acc = (raw.get("good_cnt") or 0) + (raw.get("ok_cnt") or 0) * 0.5
            acc_pct = acc / total * 100 if total else 0
            lines.append(
                f"  {h.get('update_datetime') or h.get('highscore_datetime') or h.get('fetched_at')}："
                f"分 {h.get('high_score')}｜精度 {acc_pct:.1f}%｜评价 {_rank_text(h.get('best_score_rank'))}"
            )
        return "\n".join(lines)

    async def get_improvement_candidates_text(self, qq, level=None) -> str:
        level = self._norm_level(level)
        analysis, err = await self._get_analysis(qq)
        if err:
            return err
        records = self._records(analysis)
        if level is not None and level not in (4, 5):
            return f"{difficulty_label(level)} 不在评级范围内（本系统仅评估鬼/里）。"
        filtered = self._filter_records(records, level=level)
        if not filtered:
            return "该难度暂无成绩。"
        # 「差一点全良」：精度 >= 0.99 但尚无咚大福；「差一点全连」：良/可/不可里不可=0 且无全连
        near_dondaful = [r for r in filtered if (r.get("accuracy") or 0) >= 0.99 and not (r.get("dondafulComboCount") or 0)]
        near_fc = [r for r in filtered if (r.get("ngCount") or 0) == 0 and not (r.get("fullComboCount") or 0)]
        lines = []
        if near_dondaful:
            lines.append("差一点咚大福（精度≥99% 但未全良）：")
            lines.append("  " + "、".join(f"《{r['title']}》" for r in sorted(near_dondaful, key=lambda x: -(x.get('rating') or 0))[:8]))
        if near_fc:
            lines.append("差一点全连（无不可但未达成全连）：")
            lines.append("  " + "、".join(f"《{r['title']}》" for r in sorted(near_fc, key=lambda x: -(x.get('rating') or 0))[:8]))
        if not lines:
            return "当前没有明显「差一点」的谱面，继续保持。"
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 歌曲别名（两步确认 + 管理员审批）
    # ------------------------------------------------------------------
    async def request_alias(self, qq, target, alias) -> str:
        if not qq:
            return "无法识别你的 QQ 号。"
        if not await self._binding(qq):
            return "你还没有绑定菌菌账号。请先发送：/rtlink bind <apikey> <player_id> [server]"
        if self.db is None:
            return "本地存储未启用，无法设置别名。"
        target = (target or "").strip()
        alias = (alias or "").strip()
        if not target or not alias:
            return "用法：/rtlink alias <精准ID或曲名> <别名>"

        song, hint = self._resolve_song(target)
        if song is None:
            return hint or "未找到歌曲。"

        rid = await asyncio.to_thread(
            self.db.add_alias_request,
            song["id"], alias, song["title"], song.get("titleJa"), qq,
        )
        if rid is None:
            return f"别名「{alias}」已被使用（待审或已通过），请换一个。"
        head = f"《{song['title']}》" + (f"（{song['titleJa']}）" if song.get("titleJa") else "")
        return (
            "已收到别名设置请求，待管理员审核：\n"
            f"歌曲：{head}｜ID {song['id']}\n"
            f"别名：{alias}\n"
            "审核通过后即可用该别名查询。"
        )

    async def list_pending_aliases_text(self) -> str:
        if self.db is None:
            return "本地存储未启用。"
        pending = await asyncio.to_thread(self.db.list_pending_aliases)
        if not pending:
            return "当前没有待审批的别名。"
        lines = [f"待审批别名（{len(pending)} 条）："]
        for a in pending:
            head = f"《{a['song_title']}》" + (f"（{a['song_title_ja']}）" if a.get("song_title_ja") else "")
            lines.append(f"  #{a['id']} {head}（ID {a['song_no']}）→ 别名「{a['alias']}」由 {a['created_by']} 提出")
        lines.append("批量通过：/rtlink aliasapprove all  或  /rtlink aliasapprove 1 2 3")
        return "\n".join(lines)

    async def approve_aliases_text(self, args) -> str:
        if self.db is None:
            return "本地存储未启用。"
        arg = (args or "").strip()
        if not arg:
            return "用法：/rtlink aliasapprove all  或  /rtlink aliasapprove <编号> [编号...]"
        if arg.lower() == "all":
            pending = await asyncio.to_thread(self.db.list_pending_aliases)
            ids = [a["id"] for a in pending]
        else:
            ids = []
            for tok in arg.split():
                if tok.isdigit():
                    ids.append(int(tok))
                else:
                    return f"「{tok}」不是有效的审批编号。"
        if not ids:
            return "没有可审批的编号。"
        approved = await asyncio.to_thread(self.db.approve_aliases, ids)
        if not approved:
            return "没有成功通过的条目（可能已处理或编号不存在）。"
        return f"已通过 {len(approved)} 条别名审批（编号：{'、'.join(str(i) for i in approved)}）。现在可用别名查询。"

