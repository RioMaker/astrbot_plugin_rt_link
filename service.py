# -*- coding: utf-8 -*-
"""rt_link 核心服务层：绑定管理、菌菌同步/转义落库、玩家 Rating 画像与查询。

与 AstrBot 解耦，可独立测试。依赖 rating.py（算法）与 storage.py（SQLite 存储）。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# 包加载（AstrBot）时用相对导入；本地直接运行 service.py 时回退到绝对导入。
if __package__:
    from . import improve_text as improve_text_mod
    from . import rating as rating_mod
    from . import score_query as score_query_mod
    from . import score_rank as score_rank_mod
    from . import song_alias as song_alias_mod
    from .api_client import KinokoClient, KinokoAPIError
    from .dan_query import evaluate_player_dan_text
    from .help_image import render_help_image
    from .improve_image import render_improve_image
    from .profile_image import render_profile_image, render_configuration_image
    from .profile_data import (load_configuration_catalog, configuration_scores,
                               unique_score_rows, configuration_history_payload,
                               archive_configuration_resources, CONFIGURATION_ALGORITHM)
    from .report_image import render_report_image
    from .weakness_image import render_weakness_image
    from .storage import ScoreDatabase, load_charts
else:
    import improve_text as improve_text_mod
    import rating as rating_mod
    import score_query as score_query_mod
    import score_rank as score_rank_mod
    import song_alias as song_alias_mod
    from api_client import KinokoClient, KinokoAPIError
    from dan_query import evaluate_player_dan_text
    from help_image import render_help_image
    from improve_image import render_improve_image
    from profile_image import render_profile_image, render_configuration_image
    from profile_data import (load_configuration_catalog, configuration_scores,
                              unique_score_rows, configuration_history_payload,
                              archive_configuration_resources, CONFIGURATION_ALGORITHM)
    from report_image import render_report_image
    from weakness_image import render_weakness_image
    from storage import ScoreDatabase, load_charts

DIFFICULTY_NAMES = {
    1: "梅（简单）",
    2: "竹（一般）",
    3: "松（困难）",
    4: "鬼（魔王）",
    5: "里鬼（里魔王）",
}

# 精简画像缓存的数据契约版本。字段新增后提升版本，避免继续读取旧缓存
# 中缺少图片证据字段或节奏配置常见度分组。
RATING_CACHE_SCHEMA = 6
RATING_HISTORY_SCHEMA = 2
RATING_ALGORITHM_VERSION = "taiko-signal-rhythm-v2-r1"
SCORE_STORAGE_SCHEMA = 2


def _catalog_identity() -> tuple[str, int | None]:
    """读取随插件发布的谱面模型标识，失败时保留明确的 unknown。"""
    manifest_path = Path(__file__).resolve().parent / "resource" / "charts.manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return str(manifest.get("modelId") or "unknown"), manifest.get("schemaVersion")
    except (OSError, ValueError, TypeError):
        return "unknown", None


CATALOG_VERSION, CATALOG_SCHEMA_VERSION = _catalog_identity()


def difficulty_label(level) -> str:
    name = DIFFICULTY_NAMES.get(level)
    return f"难度{level}·{name}" if name else f"难度{level}"


# 评价等级名称统一取自 score_rank 模块（依据 wiki 配点与極スコア表实测反推），
# 避免同一套档位在两处各写一份而分叉。
SCORE_RANK_NAMES = score_rank_mod.SCORE_RANK_NAMES


def _rank_text(rank) -> str:
    if rank is None:
        return "-"
    number = int(rank)
    name = SCORE_RANK_NAMES.get(number) if score_rank_mod.SCORE_RANK_MIN <= number <= score_rank_mod.SCORE_RANK_MAX else None
    return f"{number}" + (f"（{name}）" if name else "")


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
        "accuracy": row.get("accuracy"),
        "constant": row.get("constant"),
        "aiConstant": row.get("aiConstant"),
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
            "poundCount": r.get("poundCount"),
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
            "exposure": round(c.get("exposure") or 0, 3),
            "compoundRatio": round(c.get("compoundRatio") or 0, 3),
            "averageBpm": round(c.get("averageBpm") or 0, 1),
            "catalogCharts": c.get("catalogCharts"),
            "catalogCoverage": round(c.get("catalogCoverage"), 6) if c.get("catalogCoverage") is not None else None,
            "rarity": c.get("rarity") or "common",
            "best": [_slim_song(b) for b in c.get("best", [])],
        }

    rhythm_ability = {
        "cells": [slim_cell(c) for c in result["rhythmAbility"]["cells"]],
        "best": [slim_cell(c) for c in result["rhythmAbility"]["best"]],
        "weakest": [slim_cell(c) for c in result["rhythmAbility"]["weakest"]],
        "rareWeakest": [slim_cell(c) for c in result["rhythmAbility"].get("rareWeakest", [])],
        "catalogCharts": result["rhythmAbility"].get("catalogCharts"),
        "rareCatalogCoverageThreshold": result["rhythmAbility"].get("rareCatalogCoverageThreshold"),
        "visual": {
            k: slim_cell(v) for k, v in result["rhythmAbility"]["visual"].items()
        },
    }

    # analyze() 会丢弃「谱面资料版本不一致」或「精度低于阈值」的成绩。这些曲目玩家其实打过，
    # 必须单独记下来：否则检索时会把它们误报成「未游玩」。
    rated_keys = {(item["id"], item["level"]) for item in records}
    unrated = []
    for diagnostic in result.get("diagnostics") or []:
        song_no, level = diagnostic.get("id"), diagnostic.get("level")
        if song_no is None or level is None or (song_no, level) in rated_keys:
            continue
        unrated.append({
            "id": song_no,
            "level": level,
            "code": diagnostic.get("code") or "",
            "reason": diagnostic.get("message") or "",
        })

    return {
        "_cacheSchema": RATING_CACHE_SCHEMA,
        "_ts": time.time(),
        "summary": {k: round(v, 2) for k, v in result["summary"].items()},
        "ourTaikoV1": {
            "summary": {k: round(v, 2) for k, v in result["ourTaikoV1"]["summary"].items()},
            "chartCount": result["ourTaikoV1"]["chartCount"],
        },
        "counts": result["counts"],
        "meta": result["meta"],
        "records": records,
        "unrated": unrated,
        "featureAbility": feature_ability,
        "rhythmAbility": rhythm_ability,
    }


def _history_snapshot(analysis: dict) -> dict:
    """提取可长期保存的成长曲线数据，不重复存储谱面明细。"""
    rhythm = analysis.get("rhythmAbility") or {}
    features = analysis.get("featureAbility") or {}
    return {
        "schema": RATING_HISTORY_SCHEMA,
        "algorithmVersion": RATING_ALGORITHM_VERSION,
        "catalogVersion": CATALOG_VERSION,
        "catalogSchemaVersion": CATALOG_SCHEMA_VERSION,
        "meta": dict(analysis.get("meta") or {}),
        "summary": dict(analysis.get("summary") or {}),
        "counts": dict(analysis.get("counts") or {}),
        "families": [
            {
                "key": item.get("key"),
                "score": item.get("score"),
                "charts": item.get("charts"),
                "exposure": item.get("exposure"),
            }
            for item in features.get("families") or []
        ],
        "rhythmCells": [
            {
                "key": item.get("key"),
                "pattern": item.get("pattern"),
                "bpmBand": item.get("bpmBand"),
                "score": item.get("score"),
                "charts": item.get("charts"),
                "catalogCharts": item.get("catalogCharts"),
                "catalogCoverage": item.get("catalogCoverage"),
                "rarity": item.get("rarity") or "common",
            }
            for item in rhythm.get("cells") or []
        ],
        "rareCatalogCoverageThreshold": rhythm.get("rareCatalogCoverageThreshold"),
    }


class ScoreService:
    """rt_link 核心业务逻辑（绑定 + 同步 + 评级画像）。"""

    def __init__(
        self,
        store: BindingsStore,
        client_factory,
        charts: dict | None = None,
        score_db: ScoreDatabase | None = None,
        score_rank: dict | None = None,
        rolls: dict | None = None,
        aliases: dict | None = None,
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
        self.configuration_catalog = load_configuration_catalog(self.charts)
        self.db = score_db
        self.score_rank = score_rank or score_rank_mod.empty_score_rank()
        # 连打资料（黄色連打秒数 / 風船）：用来把「还差几打连打」换算成秒速。
        self.rolls = rolls or score_rank_mod.empty_rolls()
        # 曲名别名索引（国服名 / 日文名 / 罗马字 / 常用别名）：段位查询与成绩检索共用。
        self.aliases = aliases or song_alias_mod.empty_aliases()
        self._builtin_alias_map = None
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
        if self.db is not None:
            await asyncio.to_thread(self.db.reset_current_player, qq)
        return True, (
            f"绑定成功：QQ {qq} ↔ 玩家 {player_id}（{server}）。"
            "请发送 /rtlink 自动同步，或发送 /rtlink update 手动强制同步全部成绩。"
        )

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

    @staticmethod
    def _sync_required_message(detail: str = "") -> str:
        prefix = (detail.strip() + "\n") if detail else ""
        return prefix + (
            "检测到插件更新后的全难度成绩数据尚未同步。请重新发送 /rtlink 自动同步，"
            "或发送 /rtlink update 手动强制同步；/rtlink score <曲名>、"
            "/rtlink rating、/rtlink profile、/rtlink weakness 也会按需自动同步。"
        )

    async def _score_storage_ready(self, qq, binding: dict | None = None) -> bool:
        if self.db is None:
            return False
        binding = binding or await self._binding(qq)
        if not binding:
            return False
        state = await asyncio.to_thread(
            self.db.kv_get, f"score_storage_schema:{qq}", {}
        )
        if not isinstance(state, dict) or state.get("schema") != SCORE_STORAGE_SCHEMA:
            return False
        if str(state.get("playerId") or "") != str(binding.get("player_id") or ""):
            return False
        stored_server = str(state.get("server") or "")
        return not stored_server or stored_server == str(binding.get("server") or self.default_server)

    async def score_sync_reminder_text(self, qq) -> str:
        binding = await self._binding(qq)
        if not binding or await self._score_storage_ready(qq, binding):
            return ""
        return self._sync_required_message()

    # ------------------------------------------------------------------
    # 同步 / 分析
    # ------------------------------------------------------------------
    async def _sync(self, qq) -> tuple[bool, str, dict | None]:
        b = await self._binding(qq)
        if not b:
            return False, "你还没有绑定菌菌账号。请先私聊可可子发送：/rtlink bind <apikey> <player_id> [server]", None
        apikey = b["apikey"]
        player_id = str(b.get("player_id") or "")
        server = b.get("server") or self.default_server
        client = self._client(apikey)

        kinoko, hiroba = await asyncio.gather(
            asyncio.to_thread(client.kinoko, player_id, server),
            asyncio.to_thread(client.hiroba, player_id, server),
            return_exceptions=True,
        )

        if await self._binding(qq) != b:
            return False, "绑定在同步期间发生变化，请重新发送 /rtlink。", None

        errors = {}
        if isinstance(kinoko, BaseException):
            errors["kinoko"] = str(kinoko)
            kinoko = None
        if isinstance(hiroba, BaseException):
            errors["hiroba"] = str(hiroba)
            hiroba = None

        if kinoko is not None:
            try:
                await asyncio.to_thread(
                    self._store_payload, qq, "kinoko", kinoko, player_id, server
                )
            except Exception:
                kinoko = None
        if hiroba is not None:
            try:
                await asyncio.to_thread(
                    self._store_payload, qq, "hiroba", hiroba, player_id, server
                )
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
        source = "kinoko" if kinoko is not None else "hiroba"
        # Freeze identity from the binding used by this sync, not optional API metadata.
        slim['meta'] = {**slim['meta'], 'playerId':player_id, 'server':server}
        fields = ('id','level','highScore','bestScoreRank','clearCount','fullComboCount','dondafulComboCount')
        normalized = rating_mod.normalize_scores(payload_for_rating, rated_only=False)
        slim['profileScoreRows'] = unique_score_rows([{key:row.get(key) for key in fields} for row in normalized['rows']])
        for row in slim['records']:
            row['title'] = self.charts.get((row['id'], row['level']), {}).get('title') or row['title']
        slim['profileConfigurations'] = await asyncio.to_thread(configuration_scores, result['records'], self.configuration_catalog)
        target = self._default_target_rank(result['records'])
        improvement = await asyncio.to_thread(
            score_rank_mod.analyze_rank_improvements, result['records'], self.charts,
            self.score_rank, target, per_genre=3, rolls_data=self.rolls
        )
        improvement['items'] = improvement['items'][:8]
        for item in improvement['items']:
            item['title'] = self.charts.get((item['id'], item['level']), {}).get('title') or item.get('title')
        slim['profileImprovement'] = improvement
        slim['profileSyncedAt'] = datetime.now(timezone.utc).isoformat()
        slim['profileRating'] = result['summary']['rating']
        slim['profileSource'] = source
        if await self._binding(qq) != b:
            return False, "绑定在同步期间发生变化，请重新发送 /rtlink。", None
        slim['_historySaved'] = await self._record_rating_snapshot(qq, slim, 'sync')
        if self.db is not None:
            if slim['profileConfigurations']['available']:
                try:
                    await asyncio.to_thread(archive_configuration_resources, Path(self.db.db_path).parent, slim['profileConfigurations'])
                    await asyncio.to_thread(self.db.add_configuration_snapshot, qq, configuration_history_payload(slim), slim['profileSyncedAt'])
                except Exception as error:
                    self._logger.error(f"记录配置历史失败：{error}")
                    slim['_historySaved'] = False
            await asyncio.to_thread(self.db.put_rating_cache, qq, slim)
            await asyncio.to_thread(self.db.set_sync_state, qq, source, True)

        # 空间告警检查（同步后触发）
        warning = await self.check_storage_warning()
        if warning:
            self._logger.warning(warning)
        return True, "", slim

    def _store_payload(
        self, player_id: str, source: str, payload: dict,
        expected_game_player_id: str | None = None, expected_server: str | None = None,
    ) -> int:
        normalized = rating_mod.normalize_scores(payload, rated_only=False)
        rows = []
        for r in normalized["rows"]:
            rows.append({
                "id": r["id"],
                "level": r["level"],
                "good_cnt": r["goodCount"],
                "ok_cnt": r["okCount"],
                "ng_cnt": r["ngCount"],
                "dondaful_cnt": r["dondafulComboCount"],
                "pound_cnt": r.get("poundCount"),
                "combo_cnt": r.get("comboCount"),
                "stage_cnt": r.get("stageCount"),
                "clear_cnt": r.get("clearCount"),
                "full_combo_cnt": r.get("fullComboCount"),
                "high_score": r["highScore"],
                "best_score_rank": r["bestScoreRank"],
                "highscore_datetime": (r.get("raw") or {}).get("highscore_datetime"),
                "update_datetime": r.get("updatedAt"),
                "raw": r.get("raw") or {},
            })
        if self.db is None:
            return len(rows)
        game_player_id = normalized["meta"].get("playerId") or expected_game_player_id
        server = normalized["meta"].get("server") or expected_server
        count = self.db.replace_scores(
            player_id,
            source,
            rows,
            game_player_id=game_player_id or None,
            server=server or None,
        )
        self.db.kv_set(f"score_storage_schema:{player_id}", {
            "schema": SCORE_STORAGE_SCHEMA,
            "playerId": str(game_player_id or ""),
            "server": str(server or ""),
        })
        return count

    async def get_player_dan_capability_text(
        self, qq, catalog: dict, year: int, region: str, rank: str
    ) -> str:
        """同步后将玩家最佳单曲记录与指定段位的可计算条件对照。"""
        binding = await self._binding(qq)
        if not binding:
            return "你还没有绑定菌菌账号。请先私聊可可子发送：/rtlink bind <apikey> <player_id> [server]"
        if self.db is None:
            return "本地成绩存储未启用，无法评估段位课题曲。"

        _, error = await self._get_analysis(qq)
        if not await self._score_storage_ready(qq, binding):
            return error or self._sync_required_message()

        effective_region = region or ("cn" if binding.get("server") == "cn" else "jp")
        rows = await asyncio.to_thread(self.db.get_scores, str(qq))
        rows = [
            row for row in rows
            if str(row.get("game_player_id") or "") == str(binding.get("player_id") or "")
            and (not row.get("server") or row.get("server") == binding.get("server"))
        ]
        if not rows:
            return error or "同步完成，但没有可用于段位评估的成绩。"
        return evaluate_player_dan_text(
            catalog, rows, year=year, region=effective_region, rank=rank,
            alias_data=self.aliases,
        )

    async def _get_analysis(self, qq) -> tuple[dict | None, str]:
        if not qq:
            return None, "无法识别你的 QQ 号。"
        if not await self._binding(qq):
            return None, "你还没有绑定菌菌账号。请先私聊可可子发送：/rtlink bind <apikey> <player_id> [server]"
        if self.db is not None:
            cache = await asyncio.to_thread(self.db.get_rating_cache, qq)
            storage_ready = await self._score_storage_ready(qq)
            if (
                cache
                and cache.get("_cacheSchema") == RATING_CACHE_SCHEMA
                and (cache.get('profileConfigurations') or {}).get('resourceHash') == self.configuration_catalog.get('hash')
                and (not self.configuration_catalog.get('available') or (cache.get('profileConfigurations') or {}).get('algorithmVersion') == CONFIGURATION_ALGORITHM)
                and storage_ready
                and time.time() - float(cache.get("_ts") or 0) < self.sync_ttl
            ):
                return cache, ""
        ok, msg, slim = await self._sync(qq)
        if not ok:
            if self.db is not None and not await self._score_storage_ready(qq):
                msg = self._sync_required_message(msg)
            return None, msg
        return slim, ""

    async def _record_rating_snapshot(self, qq, analysis: dict, trigger: str) -> bool:
        if self.db is None:
            return False
        try:
            snapshot = _history_snapshot(analysis)
            evidence = {**snapshot, 'source':analysis.get('profileSource'),
                        'inputs':[{k:r.get(k) for k in ('id','level','rating','goodCount','okCount','ngCount','dondafulComboCount')} for r in analysis.get('records') or []]}
            digest = hashlib.sha256(json.dumps(evidence, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            key = f'rating_history_last:{qq}'
            if await asyncio.to_thread(self.db.kv_get, key) == digest:
                return True
            await asyncio.to_thread(self.db.add_rating_snapshot, qq, trigger, snapshot)
            await asyncio.to_thread(self.db.kv_set, key, digest)
            return True
        except Exception as error:
            self._logger.error(f"记录 Rating 历史快照失败：{error}")
            return False

    async def force_update(self, qq) -> tuple[bool, str]:
        """跳过缓存，从菌菌重新拉取成绩、计算 Rating 并记录快照。"""
        ok, message, analysis = await self._sync(qq)
        if not ok or analysis is None:
            if self.db is not None and not await self._score_storage_ready(qq):
                message = self._sync_required_message(message)
            return False, message
        recorded = analysis.get('_historySaved', False)
        rating = float((analysis.get("summary") or {}).get("rating") or 0)
        chart_count = len(analysis.get("records") or [])
        suffix = "历史已保存（相同成绩不会重复记点）。" if recorded else "成绩已更新，但历史快照未保存，请检查日志。"
        return True, f"更新完成：已从菌菌拉取 {chart_count} 张有效成绩，综合 Rating {rating:.2f}；{suffix}"

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
            f"成绩历史：{stats['score_history_count']} 个变化状态 ｜ 同步批次：{stats['score_sync_count']} 次",
            f"评级缓存：{stats['cache_count']} 个玩家",
            f"Rating 历史：{stats['snapshot_count']} 份快照",
            f"配置历史：{stats['configuration_snapshot_count']} 份，压缩内容 {stats['configuration_content_bytes'] / 1024:.1f} KiB",
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
        """{别名(小写): song_no}：内置别名打底，用户提交并通过审核的别名优先。"""
        if self._builtin_alias_map is None:
            index = {}
            for song_no, names in (self.aliases.get("song_index") or {}).items():
                for name in names:
                    key = str(name).strip().lower()
                    if key:
                        index.setdefault(key, int(song_no))
            self._builtin_alias_map = index
        index = dict(self._builtin_alias_map)
        if self.db is not None:
            approved = await asyncio.to_thread(self.db.get_approved_aliases)
            for alias, song_no in (approved or {}).items():
                key = str(alias or "").strip().lower()
                if key:
                    index[key] = int(song_no)
        return index

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

    def _alias_names(self, song_no) -> list:
        """该曲目的所有写法（国服名 / 日文名 / 罗马字 / 别名）。"""
        return list((self.aliases.get("song_index") or {}).get(str(song_no)) or [])

    def _song_summary(self, song_no: int) -> dict:
        info = self._song_index().get(song_no) or {}
        return {
            "id": song_no,
            "title": info.get("title") or f"Song {song_no}",
            "titleJa": info.get("titleJa"),
        }

    def _resolve_song(self, target: str) -> tuple[dict | None, str | None]:
        """按精准 ID、曲名或别名解析歌曲；返回 (song, 提示)。song 为 None 时提示非空。"""
        idx = self._song_index()
        text = (target or "").strip()
        if text.isdigit():
            song_no = int(text)
            info = idx.get(song_no)
            if info is None:
                return None, f"歌曲 ID {song_no} 不在谱面库中。"
            return self._song_summary(song_no), None

        # 1) 精确别名优先（含罗马字/日文名/常用简称），避免「北埼玉」这类查询被拆成多首。
        exact = song_alias_mod.match_names(self.aliases, text)
        if len(exact) == 1:
            return self._song_summary(next(iter(exact))), None
        if len(exact) > 1:
            options = "、".join(
                f"《{self._song_summary(value)['title']}》(ID {value})" for value in sorted(exact)[:8]
            )
            return None, f"「{target}」匹配到多首歌曲：{options}。请用更精确的名称或 ID 重新提交。"

        # 2) 前缀 / 包含匹配（别名索引里带派生写法）
        hits = song_alias_mod.resolve(self.aliases, text, limit=8)
        if len(hits) == 1:
            return self._song_summary(hits[0]["song_no"]), None
        if len(hits) > 1:
            options = "、".join(
                f"《{self._song_summary(hit['song_no'])['title']}》(ID {hit['song_no']})"
                for hit in hits[:8]
            )
            return None, f"「{target}」匹配到多首歌曲：{options}。请用更精确的名称或 ID 重新提交。"

        # 3) 退回谱面库原本的曲名匹配
        query = text.lower()
        matches = []
        for song_no, info in idx.items():
            hay = " | ".join(str(x or "") for x in (info.get("title"), info.get("titleJa"))).lower()
            if query in hay:
                matches.append(self._song_summary(song_no))
        if not matches:
            return None, f"未找到与「{target}」匹配的歌曲，请用更精确的名称或歌曲 ID。"
        if len(matches) == 1:
            return matches[0], None
        options = "、".join(f"《{m['title']}》(ID {m['id']})" for m in matches[:8])
        return None, f"「{target}」匹配到多首歌曲：{options}。请用更精确的名称或 ID 重新提交。"

    async def _resolve_query_to_records(self, records: list, query: str) -> list:
        """别名（内置 + 已审核）优先，其次按 title/titleJa/罗马字模糊匹配。"""
        q = (query or "").strip()
        if not q:
            return []
        normalized = song_alias_mod.normalize(q)
        matched_ids = set()
        for song_no, names in (self.aliases.get("song_index") or {}).items():
            if any(song_alias_mod.normalize(name) == normalized for name in names):
                matched_ids.add(int(song_no))
        alias_map = await self._get_alias_map()
        song_no = alias_map.get(q.lower())
        if song_no is not None:
            matched_ids.add(int(song_no))
        if matched_ids:
            found = [r for r in records if r.get("id") in matched_ids]
            if found:
                return found
        hits = song_alias_mod.resolve(self.aliases, q, limit=12)
        if hits:
            found = [r for r in records if r.get("id") in {hit["song_no"] for hit in hits}]
            if found:
                return found
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
            return self._no_score_message(clean or song_name, lvl, records)
        return self._format_song_rows(matched)

    def _no_score_message(self, query: str, level, records: list) -> str:
        """没查到成绩时区分「没这首歌」和「有这首歌但你还没打」。"""
        hits = [hit for hit in song_alias_mod.resolve(self.aliases, query, limit=5)
                if level is None or hit["level"] == level]
        if hits:
            names = "、".join(
                f"《{self._song_summary(hit['song_no'])['title']}》(ID {hit['song_no']})" for hit in hits[:3]
            )
            return (
                f"{names} 暂无你的成绩记录（同步的鬼/里成绩里没有这张谱）。"
                "可用 /rtlink update 重新同步，或换一首已打过的曲目。"
            )
        hint = "，试试更精确的曲名或别名" if not query else ""
        return f"未找到与「{query}」匹配的曲目{hint}。可用 /rtlink alias 提交常用别名。"

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
        return await self._generate_analysis_image(
            qq, "report", render_report_image, "报告"
        )

    async def generate_help_image(self, qq) -> tuple[bool, str]:
        """生成包含绑定实图和完整说明的帮助长图。"""
        out_dir = self.report_dir
        if not out_dir and self.db is not None:
            out_dir = os.path.dirname(os.path.abspath(self.db.db_path))
        if not out_dir:
            out_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(out_dir, f"help_{qq}_{time.time_ns()}.png")
        try:
            await asyncio.to_thread(render_help_image, path)
            await asyncio.to_thread(self._prune_analysis_images, out_dir, "help", qq, path)
        except Exception as error:
            self._logger.error(f"生成帮助图片失败：{error}")
            return False, f"生成帮助图片失败：{error}"
        return True, path

    async def _generate_analysis_image(
        self, qq, prefix, renderer, label
    ) -> tuple[bool, str]:
        """使用新文件名渲染分析图片，避免 AstrBot/QQ 复用旧图缓存。"""
        analysis, err = await self._get_analysis(qq)
        if err:
            return False, err
        if prefix == 'progress' and self.db is not None and (analysis.get('profileConfigurations') or {}).get('available'):
            history = await asyncio.to_thread(self.db.get_configuration_snapshots, qq, configuration_history_payload(analysis))
            analysis = {**analysis, 'configurationHistory':history}
        out_dir = self.report_dir
        if not out_dir and self.db is not None:
            out_dir = os.path.dirname(os.path.abspath(self.db.db_path))
        if not out_dir:
            out_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(out_dir, f"{prefix}_{qq}_{time.time_ns()}.png")
        try:
            await asyncio.to_thread(renderer, analysis, path)
            await asyncio.to_thread(self._prune_analysis_images, out_dir, prefix, qq, path)
        except Exception as e:
            self._logger.error(f"生成{label}图片失败：{e}")
            return False, f"生成{label}图片失败：{e}"
        return True, path

    def _prune_analysis_images(self, out_dir, prefix, qq, keep_path, retain=3) -> None:
        """仅回收同用户同类型的旧临时图片，保留最近若干张供消息发送。"""
        directory = Path(out_dir).resolve()
        keep = Path(keep_path).resolve()
        if keep.parent != directory or not directory.is_dir():
            return
        name_prefix = f"{prefix}_{qq}_"
        try:
            candidates = sorted(
                (
                    path for path in directory.iterdir()
                    if path.is_file() and path.resolve() != keep
                    and path.name.startswith(name_prefix) and path.suffix.lower() == ".png"
                ),
                key=lambda path: path.stat().st_mtime_ns,
                reverse=True,
            )
        except OSError as error:
            self._logger.warning(f"扫描旧{prefix}图片失败：{error}")
            return
        for old_path in candidates[max(int(retain) - 1, 0):]:
            try:
                old_path.unlink()
            except OSError as error:
                self._logger.warning(f"回收旧{prefix}图片失败：{error}")

    async def generate_profile_image(self, qq) -> tuple[bool, str]:
        """生成玩家 profile 图片。"""
        return await self._generate_analysis_image(qq, "profile", render_profile_image, "玩家画像")

    async def generate_configuration_image(self, qq) -> tuple[bool, str]:
        return await self._generate_analysis_image(qq, 'progress', render_configuration_image, '配置评分')

    async def generate_weakness_image(self, qq) -> tuple[bool, str]:
        """生成节奏弱项图片，冷门配置在图中独立展示。"""
        return await self._generate_analysis_image(qq, "weakness", render_weakness_image, "节奏弱项")

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
        weakest = ra.get("weakest") or []
        rare = ra.get("rareWeakest") or []
        if not weakest and not rare:
            return "节奏画像样本不足（至少 3 张同节奏型谱面才会形成结论）。"
        lines = ["常见节奏型弱项（按处理 Rating 从低到高，前几项最该练）："]
        for c in weakest[:5]:
            pattern = c.get("pattern")
            bpm = c.get("bpmBand")
            compound = "含复合" if (c.get("compoundRatio") or 0) > 0.5 else ""
            refs = "、".join(f"《{b['title']}》" for b in c.get("best", [])[:3])
            lines.append(
                f"  {pattern} @{bpm}BPM{compound}：处理 Rating {c['score']}（{c['charts']} 张）"
                + (f"｜参考曲目：{refs}" if refs else "")
            )
        if rare:
            threshold = float(ra.get("rareCatalogCoverageThreshold") or 0.03) * 100
            lines.append(f"冷门配置观察（全库覆盖低于 {threshold:.0f}%，不计入核心弱项排行）：")
            for c in rare[:5]:
                coverage = float(c.get("catalogCoverage") or 0) * 100
                lines.append(
                    f"  {c.get('pattern')} @{c.get('bpmBand')}BPM：处理 Rating {c.get('score')}"
                    f"（个人 {c.get('charts')} 张｜全库 {coverage:.2f}%）"
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

    # ------------------------------------------------------------------
    # 自定义条件检索（成绩 / 谱面库）
    # ------------------------------------------------------------------
    SORT_LABELS = {
        "rating": "Rating", "score": "分数", "accuracy": "精度", "constant": "定数",
        "notes": "音符数", "gap": "距目标缺口", "rank": "评价", "updated": "更新时间",
        "title": "曲名", "id": "曲目 ID",
    }

    async def _alias_index(self) -> dict:
        """{song_no: [别名, ...]}，供检索时按别名匹配（内置别名 + 已审核别名）。"""
        approved = {}
        if self.db is not None:
            approved = await asyncio.to_thread(self.db.get_approved_aliases)
        return song_alias_mod.build_alias_index(self.aliases, approved)

    async def query_scores(self, qq, **filters) -> tuple[dict | None, str]:
        """按自定义条件检索成绩／谱面库，返回 (结构化结果, 错误信息)。"""
        analysis, error = await self._get_analysis(qq)
        if error:
            return None, error
        result = score_query_mod.select(
            self._records(analysis),
            self.charts,
            self.score_rank,
            alias_index=await self._alias_index(),
            unrated=analysis.get("unrated") or [],
            rolls_data=self.rolls,
            **filters,
        )
        return result, ""

    def _format_query_row(self, row: dict, detail: str = "brief") -> str:
        title = row.get("title") or f"曲目 {row.get('id')}"
        title_ja = row.get("titleJa")
        head = f"《{title}》"
        if title_ja and title_ja != title:
            head += f"（{title_ja}）"
        head += f"{difficulty_label(row.get('level'))}"

        if not row.get("played"):
            bits = [head, f"定数 {row.get('constant') if row.get('constant') is not None else '-'}"]
            if row.get("totalNotes"):
                bits.append(f"音符 {row['totalNotes']}")
            bits.append(f"分区 {row.get('genre')}")
            bits.append("未游玩")
            return "  " + "｜".join(bits)

        if not row.get("rated"):
            # 有成绩但没进评级：谱面资料版本不一致，或精度低于评级阈值。
            bits = [
                head,
                f"定数 {row.get('constant') if row.get('constant') is not None else '-'}",
                f"音符 {row.get('totalNotes')}",
                f"分区 {row.get('genre')}",
                "有成绩但未参与评级",
            ]
            if row.get("unratedReason"):
                bits.append(row["unratedReason"])
            return "  " + "｜".join(bits)

        bits = [
            head,
            f"Rating {round(row.get('rating') or 0, 2)}",
            f"分数 {row.get('highScore')}",
            f"评价 {_rank_text(row.get('bestScoreRank'))}",
            f"精度 {(row.get('accuracy') or 0) * 100:.2f}%",
            f"定数 {row.get('constant') if row.get('constant') is not None else '-'}",
        ]
        if detail == "full":
            bits.append(f"分区 {row.get('genre')}")
            bits.append(
                f"良 {row.get('goodCount')}／可 {row.get('okCount')}／不可 {row.get('ngCount')}／连打 {row.get('poundCount')}"
            )
            bits.append(f"全连 {row.get('fullComboCount') or 0}／全良 {row.get('dondafulComboCount') or 0}")
            if row.get("updatedAt"):
                bits.append(f"更新 {row['updatedAt']}")
        lines = ["  " + "｜".join(bits)]
        if row.get("targetRank") and row.get("targetScore"):
            if row.get("reached"):
                lines.append(f"      已达成「{row['targetName']}」")
            else:
                gap_text = f"距「{row['targetName']}」门槛 {row['targetScore']} 还差 {row['gap']}"
                if not row.get("targetExact"):
                    gap_text += "（门槛为估算值）"
                lines.append(f"      {gap_text}")
                lines.extend(f"      {text}" for text in improve_text_mod.gap_route_lines(row))
        return "\n".join(lines)

    def format_query_result(self, result: dict, detail: str = "brief") -> str:
        spec = result["filters"]
        lines = []
        if result["filterText"]:
            lines.append("筛选条件：" + "；".join(result["filterText"]))
        sort_label = self.SORT_LABELS.get(result["sort"], result["sort"])
        order_label = "降序" if result["order"] == "desc" else "升序"
        if result["shown"]:
            span = f"第 {result['offset'] + 1}-{result['offset'] + result['shown']} 条"
            lines.append(f"命中 {result['total']} 条，显示{span}（按 {sort_label} {order_label}）")
        else:
            lines.append(f"命中 {result['total']} 条")
        for note in result["notes"]:
            lines.append(f"提示：{note}")
        if not result["rows"]:
            lines.append("没有符合条件的结果，可放宽条件或换用 match_mode=any/all。")
            return "\n".join(lines)
        for row in result["rows"]:
            lines.append(self._format_query_row(row, detail))
        remaining = result["total"] - result["offset"] - result["shown"]
        if remaining > 0:
            lines.append(f"（还有 {remaining} 条：可调大 limit、用 offset 翻页，或收紧条件）")
        if spec["scope"] == "unplayed":
            lines.append("说明：这些曲目当前没有你的成绩记录，只列出谱面信息。")
        return "\n".join(lines)

    async def query_scores_text(self, qq, detail: str = "brief", **filters) -> str:
        result, error = await self.query_scores(qq, **filters)
        if error:
            return error
        return self.format_query_result(result, detail)

    async def search_scores_text(self, qq, query=None, level=None, constant_min=None,
                                 constant_max=None, rank_min=None, **extra) -> str:
        """兼容旧签名：把位置参数翻译成新筛选条件。"""
        filters = dict(extra)
        if query:
            filters["query"] = query
        if level is not None:
            filters["levels"] = (level,)
        if constant_min:
            filters["constant_min"] = constant_min
        if constant_max:
            filters["constant_max"] = constant_max
        if rank_min:
            filters["rank_min"] = rank_min
        return await self.query_scores_text(qq, **filters)

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
    # スコアランク（成绩评价）提升候选
    # ------------------------------------------------------------------
    def _default_target_rank(self, records) -> int:
        """默认目标 = 玩家最常拿到的评价的上一档（「提升一档」）。"""
        counts = defaultdict(int)
        for record in records:
            rank = int(record.get("bestScoreRank") or 0)
            if score_rank_mod.SCORE_RANK_MIN <= rank <= score_rank_mod.SCORE_RANK_MAX:
                counts[rank] += 1
        if not counts:
            return 4
        mode = max(counts.items(), key=lambda item: (item[1], item[0]))[0]
        return min(mode + 1, score_rank_mod.SCORE_RANK_MAX)

    async def get_rank_improvement(
        self, qq, target_rank=None, level=None, per_genre: int = 4, gap_limit_ratio: float = 0.0
    ) -> tuple[dict | None, str, str]:
        """返回 (分析结果, 错误信息, 默认目标说明)。"""
        analysis, error = await self._get_analysis(qq)
        if error:
            return None, error, ""
        records = self._records(analysis)
        if not records:
            return None, "暂无鬼/里成绩，无法分析评价提升空间。", ""

        note = ""
        if target_rank is None:
            target_rank = self._default_target_rank(records)
            counts = defaultdict(int)
            for record in records:
                counts[int(record.get("bestScoreRank") or 0)] += 1
            mode = max(counts.items(), key=lambda item: (item[1], item[0]))[0]
            note = (
                f"（未指定目标评价：取你最常拿到的「{score_rank_mod.score_rank_name(mode)}」"
                f"的上一档）"
            )

        levels = (level,) if level in (4, 5) else (4, 5)
        result = score_rank_mod.analyze_rank_improvements(
            records,
            self.charts,
            self.score_rank,
            target_rank,
            levels=levels,
            per_genre=per_genre,
            gap_limit_ratio=gap_limit_ratio,
            rolls_data=self.rolls,
        )
        result["meta"] = analysis.get("meta") or {}
        return result, "", note

    @staticmethod
    def _improve_item_text(item: dict) -> str:
        title = item.get("titleJa") or item.get("title")
        head = (
            f"《{title}》{difficulty_label(item['level'])}｜"
            f"{item['currentScore']}（{item['currentRankName']}）→ {item['targetScore']}｜"
            f"差 {item['gap']}"
        )
        # 判定提升与连打补足是两条并行的路；没有黄条 / 打不满时如实说明。
        lines = [head]
        lines.extend(f"      {text}" for text in improve_text_mod.gap_route_lines(item))
        return "\n".join(lines)

    def format_rank_improvement_text(self, result: dict, note: str = "") -> str:
        label = score_rank_mod.score_rank_label(result["targetRank"])
        if not result["scanned"]:
            return "没有可用于评价提升分析的成绩。"
        lines = [f"目标评价：{label}{note}"]
        if not result["candidateCount"]:
            lines.append(
                f"已扫描 {result['scanned']} 张已有成绩的谱面，全部达到该评价，暂时没有可提升的曲目。"
            )
            return "\n".join(lines)

        lines.append(
            f"已扫描 {result['scanned']} 张成绩：{result['alreadyAtTarget']} 张已达该评价，"
            f"{result['candidateCount']} 张可提升"
            f"（{result['exactCount']} 张使用 wiki 实测天井スコア，其余为估算门槛）。"
        )
        hints = []
        if result.get("noRollCount"):
            hints.append(f"{result['noRollCount']} 张没有黄条（只能靠判定）")
        if result.get("allGoodRequiredCount"):
            hints.append(f"{result['allGoodRequiredCount']} 张必须全良")
        if result.get("unreachableCount"):
            hints.append(f"{result['unreachableCount']} 张即使全良也达不到")
        if result.get("rollUnknownCount"):
            hints.append(f"{result['rollUnknownCount']} 张缺少连打秒数资料")
        if hints:
            lines.append("其中：" + "；".join(hints) + "。")
        lines.append("下列按分区列出「离目标最近」的谱面，差距越小越容易达成：")
        for row in result["genres"]:
            lines.append("")
            lines.append(f"■ {row['genre']}（{row['count']} 张待提升，中位差距 {row['gapMedian']}）")
            for item in row["closest"]:
                lines.append("  " + self._improve_item_text(item))
        lines.append("")
        lines.append(
            "算法：スコア = 良×基本点 + 可×⌊基本点/2⌋ + 黄色連打×100，"
            "基本点 = 天井スコア ÷ 总音符数；"
            "评价门槛 = 该谱極スコア × 50/60/70/80/90/95/100%"
            "（白粹 50% / 铜粹 60% / 银粹 70% / 金雅 80% / 粉雅 90% / 紫雅 95% / 极 100%）。"
            "「极」只看分数，不要求全良 —— 黄条每打固定 100 分，判定留下的「可」可以用连打补。"
        )
        lines.append(
            "连打：秒速 = 黄色連打打数 ÷ 合计黄色連打秒数（60 ÷ BPM起点 × (拍数 − 1/12)，风船不计入）；"
            "上限为该谱連打理論値 Σ⌈(秒数+0.001)×60⌉。"
        )
        lines.append(
            "提示：可加目标评价与难度，例如 /rtlink improve 金雅、/rtlink improve 紫雅 鬼。"
        )
        return "\n".join(lines)

    async def get_rank_improvement_text(self, qq, target_rank=None, level=None) -> str:
        result, error, note = await self.get_rank_improvement(qq, target_rank, level)
        if error:
            return error
        return self.format_rank_improvement_text(result, note)

    async def generate_rank_improve_image(
        self, qq, target_rank=None, level=None, per_genre: int = 4
    ) -> tuple[bool, str]:
        """生成「提升评价」候选曲目图片。"""
        result, error, note = await self.get_rank_improvement(
            qq, target_rank, level, per_genre=per_genre
        )
        if error:
            return False, error
        result["note"] = note

        out_dir = self.report_dir
        if not out_dir and self.db is not None:
            out_dir = os.path.dirname(os.path.abspath(self.db.db_path))
        if not out_dir:
            out_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(out_dir, f"improve_{qq}_{time.time_ns()}.png")
        try:
            await asyncio.to_thread(render_improve_image, result, path)
            await asyncio.to_thread(self._prune_analysis_images, out_dir, "improve", qq, path)
        except Exception as error:  # noqa: BLE001 - 渲染失败直接回报用户
            self._logger.error(f"生成评价提升图片失败：{error}")
            return False, f"生成评价提升图片失败：{error}"
        return True, path

    # ------------------------------------------------------------------
    # 歌曲别名（两步确认 + 管理员审批）
    # ------------------------------------------------------------------
    async def request_alias(self, qq, target, alias) -> str:
        if not qq:
            return "无法识别你的 QQ 号。"
        if not await self._binding(qq):
            return "你还没有绑定菌菌账号。请先私聊可可子发送：/rtlink bind <apikey> <player_id> [server]"
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

