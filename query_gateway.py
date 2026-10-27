"""Allowlisted, composable read queries with one analysis snapshot per batch."""

from __future__ import annotations

import json
import math
from contextvars import ContextVar

if __package__:
    from .dan_query import query_dan_courses_text
else:
    from dan_query import query_dan_courses_text

ANALYSIS_SCOPE: ContextVar[dict | None] = ContextVar(
    "rtlink_query_analysis", default=None
)
MAX_QUERIES = 24
MAX_INPUT_CHARS = 16000
MAX_OUTPUT_CHARS = 32000
LIMITATIONS = [
    "玩家数据来自当前数据源的一次分析快照；可能按现有缓存规则同步成绩。",
    "单曲最佳记录不能证明实际过段、魂槽或连续演奏；公共谱面不能定位玩家失误或预测过关概率。",
    "检索和谱面结果遵循请求的 limit/offset；摘要、推荐及旧查询自身的条数限制仍适用。",
]

# tool -> (service method, required parameters, optional parameters).
# No arbitrary getattr target, credentials, alternate player ID or write operation.
OPERATIONS = {
    "get_player_overview": ("get_ai_overview_text", (), ()),
    "get_player_rating": ("get_rating_text", (), ()),
    "get_player_profile": ("get_profile_text", (), ()),
    "get_rhythm_weakness": ("get_rhythm_weakness_text", (), ()),
    "get_difficulty_stats": ("get_difficulty_stats_text", (), ("level",)),
    "get_rank_distribution": ("get_rank_distribution_text", (), ("level",)),
    "get_genre_strength": ("get_genre_strength_text", (), ()),
    "get_accuracy_summary": ("get_accuracy_summary_text", (), ("level",)),
    "query_taiko_score": ("query_score_text", ("song_name",), ("level",)),
    "query_song_brief": ("get_song_brief_text", ("song_name",), ("level",)),
    "get_song_full": ("get_song_full_text", ("song_name",), ()),
    "get_recent_scores": ("get_recent_scores_text", (), ("days",)),
    "get_growth_trend": ("get_growth_trend_text", (), ("song_name",)),
    "get_improvement_candidates": ("get_improvement_candidates_text", (), ("level",)),
    "find_rank_improvements": (
        "get_rank_improvement_text",
        (),
        ("target_rank", "level"),
    ),
    "recommend_practice": (
        "recommend_practice_text",
        (),
        ("goal", "level", "target_rank", "scope"),
    ),
    "search_scores": (
        "query_scores_text",
        (),
        (
            "query",
            "match_mode",
            "match_fields",
            "scope",
            "level",
            "genre",
            "song_no",
            "constant_min",
            "constant_max",
            "rating_min",
            "rating_max",
            "accuracy_min",
            "accuracy_max",
            "score_min",
            "score_max",
            "notes_min",
            "notes_max",
            "rank_min",
            "rank_max",
            "ok_min",
            "ok_max",
            "ng_min",
            "ng_max",
            "combo",
            "target_rank",
            "reached",
            "gap_max",
            "sort",
            "order",
            "detail",
            "limit",
            "offset",
            "fc_min",
            "dondaful_min",
        ),
    ),
    "get_chart_analysis": (
        "get_chart_analysis_text",
        ("song_name",),
        (
            "level",
            "route",
            "detail",
            "start_measure",
            "end_measure",
            "offset",
            "limit",
        ),
    ),
    "query_dan_course": (
        None,
        (),
        ("year", "region", "rank", "song_name", "song_no"),
    ),
    "evaluate_player_dan": (
        "get_player_dan_capability_text",
        ("year", "rank"),
        ("region",),
    ),
    "get_library_status": ("chart_library_status_text", (), ()),
    "get_source_status": (None, (), ()),
}

INTEGER_ARGS = {
    "days",
    "song_no",
    "year",
    "score_min",
    "score_max",
    "notes_min",
    "notes_max",
    "rank_min",
    "rank_max",
    "ok_min",
    "ok_max",
    "ng_min",
    "ng_max",
    "gap_max",
    "limit",
    "offset",
    "start_measure",
    "end_measure",
    "fc_min",
    "dondaful_min",
}
NUMBER_ARGS = {
    "constant_min",
    "constant_max",
    "rating_min",
    "rating_max",
    "accuracy_min",
    "accuracy_max",
}
LEVEL_STATS = {
    "get_difficulty_stats",
    "get_rank_distribution",
    "get_accuracy_summary",
    "get_improvement_candidates",
    "find_rank_improvements",
    "query_taiko_score",
}


def dumps(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
        sort_keys=True,
    )


def validate_queries(queries):
    """Validate the envelope before budget use; validate each item independently."""
    if not isinstance(queries, list) or not 1 <= len(queries) <= MAX_QUERIES:
        raise ValueError(f"queries 必须是包含 1–{MAX_QUERIES} 项的数组。")
    try:
        encoded = dumps(queries)
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError("queries 必须是有效 JSON 数据，数字必须有限。") from error
    if len(encoded) > MAX_INPUT_CHARS:
        raise ValueError(f"查询参数总长度不能超过 {MAX_INPUT_CHARS} 字符。")
    # Return an owned, JSON-safe copy; callers cannot mutate a running batch.
    return json.loads(encoded)


def item_arguments(item, parse_level, parse_rank):
    if not isinstance(item, dict) or set(item) - {"tool", "args"}:
        raise ValueError("每项格式为 {tool: 工具名, args: 参数对象}。")
    tool = item.get("tool")
    if not isinstance(tool, str) or tool not in OPERATIONS:
        raise ValueError("未知或非只读入口。可用：" + "、".join(OPERATIONS))
    args = item.get("args", {})
    if not isinstance(args, dict):
        raise ValueError("args 必须是参数对象。")  # noqa: TRY004 -- one public validation error type
    _, required, optional = OPERATIONS[tool]
    unknown = set(args) - set(required) - set(optional)
    if unknown:
        raise ValueError("不支持参数：" + "、".join(sorted(unknown)))
    missing = [key for key in required if key not in args or args[key] in (None, "")]
    if missing:
        raise ValueError("缺少参数：" + "、".join(missing))
    args = dict(args)
    for key, value in args.items():
        if key in INTEGER_ARGS:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{key} 必须是整数。")
        elif key in NUMBER_ARGS:
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(f"{key} 必须是有限数字。")
        elif key in ("level", "target_rank"):
            if isinstance(value, bool) or not isinstance(value, (str, int)):
                raise ValueError(f"{key} 必须是名称或整数编号。")
            args[key] = str(value)
        elif not isinstance(value, str) or len(value) > 200:
            raise ValueError(f"{key} 必须是至多 200 字符的字符串。")
    if "song_name" in required and not args["song_name"].strip():
        raise ValueError("song_name 不能为空。")
    if tool == "get_recent_scores" and not 1 <= args.get("days", 1) <= 3650:
        raise ValueError("days 必须为 1–3650。")
    if "offset" in args and not 0 <= args["offset"] <= 100000:
        raise ValueError("offset 必须为 0–100000。")
    if "limit" in args:
        maximum = 20 if tool == "get_chart_analysis" else 200
        if not 1 <= args["limit"] <= maximum:
            raise ValueError(f"limit 必须为 1–{maximum}。")
    if "year" in args and args["year"] not in (0, 2022, 2023, 2024, 2025, 2026):
        raise ValueError("year 为 2022–2026，公开查询可用 0 表示不限。")
    if tool == "evaluate_player_dan" and not args["year"]:
        raise ValueError("段位评估需要指定年份。")
    if args.get("target_rank"):
        rank = parse_rank(args["target_rank"])
        if rank is None:
            raise ValueError("target_rank 无法识别。")
        if tool == "find_rank_improvements":
            args["target_rank"] = rank
    if "level" in args:
        value = args["level"]
        if tool == "search_scores":
            tokens = value.replace("，", ",").replace("/", ",").split(",")
            levels = [parse_level(token.strip()) for token in tokens if token.strip()]
            if any(level not in (4, 5) for level in levels):
                raise ValueError("检索难度仅支持鬼/里（4/5），多个用逗号分隔。")
            args.pop("level")
            args["levels"] = tuple(levels) or None
        elif value not in ("", "0"):
            level = parse_level(value)
            allowed = (1, 2, 3, 4, 5) if tool == "query_taiko_score" else (4, 5)
            if level not in allowed:
                raise ValueError("难度参数无法识别或不在该查询支持范围内。")
            args["level"] = level if tool in LEVEL_STATS else str(level)
        elif tool in LEVEL_STATS:
            args["level"] = None
        else:
            args["level"] = ""
    if tool == "search_scores":
        enums = {
            "scope": {"played", "unrated", "unplayed", "all"},
            "match_mode": {"contains", "exact", "regex", "all", "any"},
            "match_fields": {"any", "title", "titleJa", "genre", "alias"},
            "combo": {"", "full", "no-fc", "dondaful", "no-miss", "miss"},
            "reached": {"", "yes", "no"},
            "order": {"asc", "desc"},
            "detail": {"brief", "full"},
        }
        for key, values in enums.items():
            if key in args and args[key] not in values:
                raise ValueError(f"{key} 可用：{'、'.join(sorted(values))}")
    return tool, args


async def run_queries(service, qq, queries, catalog, parse_level, parse_rank):
    """Run sequentially under the router's user lock, sharing even failed syncs."""
    existing = ANALYSIS_SCOPE.get()
    scope = {} if existing is None else existing
    token = ANALYSIS_SCOPE.set(scope)
    results, seen = [], {}
    try:
        for index, item in enumerate(queries, 1):
            result = {"index": index}
            try:
                tool, args = item_arguments(item, parse_level, parse_rank)
            except ValueError as error:
                result.update(status="invalid_argument", message=str(error))
                results.append(result)
                continue
            result.update(tool=tool, args=args)
            try:
                key = dumps([tool, args])
                if key in seen:
                    result.update(status="reused", same_as=seen[key])
                else:
                    data = await _execute(service, qq, tool, args, catalog)
                    result.update(status="completed", data=data)
                    seen[key] = index
            except Exception as error:  # noqa: BLE001 -- isolate backend failures, never echo secrets
                service._logger.warning(
                    f"统一查询子项失败：index={index} type={type(error).__name__}"
                )
                result.update(
                    status="error",
                    message="该子查询执行失败，其他查询继续；请检查插件日志。",
                )
            results.append(result)
        provenance = None
        for analysis, _ in scope.values():
            if analysis:
                provenance = {
                    "synced_at": analysis.get("profileSyncedAt"),
                    "server": (analysis.get("meta") or {}).get("server"),
                }
                break
        return {
            "source": service.provider_label,
            "snapshot": provenance,
            "results": results,
            "complete": True,
            "limitations": LIMITATIONS,
        }
    finally:
        ANALYSIS_SCOPE.reset(token)


async def _execute(service, qq, tool, args, catalog):
    if tool == "query_dan_course":
        return query_dan_courses_text(catalog, alias_data=service.aliases, **args)
    if tool == "evaluate_player_dan":
        return await service.get_player_dan_capability_text(
            qq,
            catalog,
            args["year"],
            args.get("region", ""),
            args["rank"],
        )
    if tool == "get_source_status":
        binding = await service._binding(qq)
        return {
            "source": service.provider_label,
            "bound": bool(binding),
            "server": binding.get("server") if binding else None,
        }
    method = getattr(service, OPERATIONS[tool][0])
    if tool == "get_chart_analysis":
        data = await method(**args)
        return json.loads(data)
    if tool == "get_library_status":
        return json.loads(await method())
    return await method(qq, **args)


def render_result(batch, attachment=None):
    """Keep every query represented and explicitly label incomplete previews."""
    full = dumps(batch)
    if len(full) <= MAX_OUTPUT_CHARS:
        return full
    preview = {**batch, "complete": False, "attachment": attachment or "not_sent"}
    preview["limitations"] = [
        *LIMITATIONS,
        "文本仅为摘要；完整结果见附件，附件未送达时不得声称已提供完整数据。",
    ]
    preview["results"] = []
    for item in batch["results"]:
        row = {key: value for key, value in item.items() if key != "data"}
        if "data" in item:
            row.update(complete=False, preview="")
        preview["results"].append(row)
    base_length = len(dumps(preview))
    data_count = sum("data" in item for item in batch["results"])
    allowance = max(0, (MAX_OUTPUT_CHARS - base_length - 512) // max(1, data_count))
    for item, row in zip(batch["results"], preview["results"]):
        if "data" not in item:
            continue
        data = item["data"]
        value = data if isinstance(data, str) else dumps(data)
        if len(dumps(data)) <= allowance:
            row.pop("preview")
            row.update(data=data, complete=True)
        else:
            low, high = 0, len(value)
            while low < high:
                middle = (low + high + 1) // 2
                excerpt = (
                    value[: middle // 2]
                    + "\n…材料省略…\n"
                    + value[len(value) - (middle + 1) // 2 :]
                )
                if len(dumps(excerpt)) <= allowance:
                    low = middle
                else:
                    high = middle - 1
            row["preview"] = (
                value[: low // 2]
                + "\n…材料省略…\n"
                + value[len(value) - (low + 1) // 2 :]
            )
    rendered = dumps(preview)
    # JSON escaping can expand previews; reduce only previews, never query identity.
    while len(rendered) > MAX_OUTPUT_CHARS:
        largest = max(preview["results"], key=lambda row: len(row.get("preview", "")))
        value = largest.get("preview", "")
        if not value:
            raise ValueError("查询结果元数据超过文本容量。")
        largest["preview"] = value[: len(value) // 2]
        rendered = dumps(preview)
    return rendered
