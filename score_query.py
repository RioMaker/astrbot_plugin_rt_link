# -*- coding: utf-8 -*-
"""成绩与谱面库的自定义条件检索。

设计原则：
- 只做「匹配 / 筛选 / 排序 / 分页」，返回结构化行；文案与难度／评价名称由 service 层统一输出，
  避免两套命名表分叉。
- 所有条件都是可选的，并且可以自由组合；未提供的条件不参与判断。
- 既能查玩家已有成绩（scope=played），也能查谱面库里没打过的曲目（scope=unplayed），
  或两者一起（scope=all），这样「这首是什么定数 / 有哪些歌我没打过」也能直接回答。
- 另有一类曲目：玩家确实打过，但成绩因为「谱面资料版本不一致」或「精度低于评级阈值」而没进评级。
  它们由 scope=unrated 单独暴露，并且在 unplayed 里被排除 —— 否则会被误报成「没打过」。

数值条件的「未设置」约定：
- `*_min`：<= 0 视为未设置（下限为 0 本身没有筛选意义）。
- `*_max`：< 0 视为未设置。
- 对于 0 不可能是有效约束的物理量上限（定数／Rating／精度／分数／音符数），0 也视为未设置，
  这样沿用「0 = 不限」习惯的调用方不会意外查出空集。
- 但 `ok_max=0`（零「可」）与 `ng_max=0`（零「不可」）是有效条件，不会被忽略。

本模块只依赖标准库与 score_rank，可独立测试。
"""

from __future__ import annotations

import math
import re
import unicodedata

if __package__:
    from . import score_rank as score_rank_mod
else:
    import score_rank as score_rank_mod

MATCH_MODES = ("contains", "exact", "regex", "all", "any")
MATCH_FIELDS = ("any", "title", "titleJa", "genre", "alias")
SCOPES = ("played", "unrated", "unplayed", "all")
COMBO_MODES = ("", "full", "no-fc", "dondaful", "no-miss", "miss")

SORT_KEYS = ("rating", "score", "accuracy", "constant", "notes", "gap", "rank", "updated", "title", "id")
SORT_ALIASES = {
    "rating": "rating", "r": "rating", "评分": "rating", "实力": "rating",
    "score": "score", "highscore": "score", "high_score": "score", "分数": "score", "最高分": "score",
    "accuracy": "accuracy", "acc": "accuracy", "精度": "accuracy",
    "constant": "constant", "const": "constant", "定数": "constant",
    "notes": "notes", "totalnotes": "notes", "note": "notes", "音符": "notes", "音符数": "notes",
    "gap": "gap", "diff": "gap", "缺口": "gap", "差距": "gap",
    "rank": "rank", "scorerank": "rank", "评价": "rank", "评级": "rank",
    "updated": "updated", "update": "updated", "time": "updated", "date": "updated",
    "时间": "updated", "更新时间": "updated",
    "title": "title", "name": "title", "曲名": "title",
    "id": "id", "songno": "id", "song_no": "id", "编号": "id",
}

MAX_LIMIT = 200
DEFAULT_LIMIT = 20


# ---------------------------------------------------------------------------
# 取值与规范化
# ---------------------------------------------------------------------------

def _num(value):
    """把参数转成 float；空值/无法解析返回 None。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("%", "").replace("，", "").replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _limit_min(value):
    """下限：<= 0 视为未设置。"""
    number = _num(value)
    return number if number is not None and number > 0 else None


def _limit_max(value):
    """上限：< 0 视为未设置；0 是有效条件。"""
    number = _num(value)
    return number if number is not None and number >= 0 else None


def _rank_max(value):
    """评价上限：评价从 1 起算，因此 < 1 一律视为未设置。"""
    number = _limit_max(value)
    return number if number is not None and number >= 1 else None


def _limit_max_positive(value):
    """物理量上限（定数／Rating／精度／分数／音符数）：0 不可能是有效约束，按未设置处理。

    这样即使调用方沿用旧习惯传 0 表示「不限」，也不会意外查出空集。
    """
    number = _limit_max(value)
    return number if number is not None and number > 0 else None


def _ratio(value):
    """精度：支持 0~1 与 0~100 两种写法，统一成 0~1。"""
    number = _num(value)
    if number is None:
        return None
    if number > 1:
        number /= 100.0
    return number


def normalize_text(value) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).casefold()


def normalize_sort(value) -> str:
    key = normalize_text(value).strip()
    if not key:
        return "rating"
    return SORT_ALIASES.get(key, key if key in SORT_KEYS else "rating")


def parse_song_no(value) -> int | None:
    number = _num(value)
    if number is None or number <= 0 or number != int(number):
        return None
    return int(number)


# ---------------------------------------------------------------------------
# 自定义匹配
# ---------------------------------------------------------------------------

def _alias_values(row, alias_index) -> list:
    aliases = alias_index.get(row.get("id")) if alias_index else None
    return [normalize_text(item) for item in (aliases or [])]


def make_matcher(query, mode: str = "contains", fields: str = "any", alias_index=None):
    """构造 (predicate, note)。predicate(row) -> bool；query 为空时返回 (None, "")。"""
    text = str(query or "").strip()
    if not text:
        return None, ""

    mode = normalize_text(mode).strip() or "contains"
    if mode not in MATCH_MODES:
        mode = "contains"
    fields = normalize_text(fields).strip() or "any"
    if fields not in MATCH_FIELDS:
        fields = "any"

    needle = normalize_text(text)
    tokens = [token for token in re.split(r"[\s,、;；]+", needle) if token]
    note = ""
    pattern = None
    if mode == "regex":
        try:
            pattern = re.compile(text, re.IGNORECASE)
        except re.error as error:
            mode = "contains"
            note = f"正则表达式无效（{error}），已按「包含」处理。"

    def values(row):
        collected = []
        if fields in ("any", "title"):
            collected.append(normalize_text(row.get("title")))
        if fields in ("any", "titleJa"):
            collected.append(normalize_text(row.get("titleJa")))
        if fields in ("any", "genre"):
            collected.append(normalize_text(row.get("genre")))
        if fields in ("any", "alias"):
            collected.extend(_alias_values(row, alias_index))
        return [item for item in collected if item]

    def predicate(row) -> bool:
        haystack = values(row)
        if not haystack:
            return False
        if mode == "exact":
            return any(item == needle for item in haystack)
        if mode == "regex":
            return any(pattern.search(item) for item in haystack)
        if mode == "all":
            return all(any(token in item for item in haystack) for token in tokens)
        if mode == "any":
            return any(any(token in item for item in haystack) for token in tokens)
        return any(needle in item for item in haystack)

    return predicate, note


# ---------------------------------------------------------------------------
# 行构造
# ---------------------------------------------------------------------------

def _chart_constant(chart: dict) -> float | None:
    public = chart.get("public") or {}
    value = public.get("constant")
    if value is None:
        value = (chart.get("feature") or {}).get("aiConstant")
    return _num(value)


def played_row(record: dict, chart: dict) -> dict:
    """把 analyze 的 record（或缓存里的精简记录）转成统一的行结构。"""
    level = record.get("level")
    return {
        "id": record.get("id"),
        "level": level,
        "title": record.get("title") or f"Song {record.get('id')}",
        "titleJa": record.get("titleJa"),
        "genre": chart.get("genre") or "未知",
        "totalNotes": int(chart.get("totalNotes") or 0),
        "constant": _num(record.get("constant")) if record.get("constant") is not None else _chart_constant(chart),
        "aiConstant": _num(record.get("aiConstant")),
        "aiConstantRaw": _num(record.get("aiConstantRaw")),
        "rating": _num(record.get("rating")),
        "accuracy": _num(record.get("accuracy")),
        "highScore": int(record.get("highScore") or 0),
        "bestScoreRank": int(record.get("bestScoreRank") or 0),
        "goodCount": int(record.get("goodCount") or 0),
        "okCount": int(record.get("okCount") or 0),
        "ngCount": int(record.get("ngCount") or 0),
        "poundCount": int(record.get("poundCount") or 0),
        "fullComboCount": int(record.get("fullComboCount") or 0),
        "dondafulComboCount": int(record.get("dondafulComboCount") or 0),
        "clearCount": int(record.get("clearCount") or 0),
        "updatedAt": record.get("updatedAt") or "",
        "played": True,
        "rated": True,
    }


def unplayed_row(chart: dict) -> dict:
    return {
        "id": chart.get("id"),
        "level": chart.get("level"),
        "title": chart.get("title") or f"Song {chart.get('id')}",
        "titleJa": chart.get("titleJa"),
        "genre": chart.get("genre") or "未知",
        "totalNotes": int(chart.get("totalNotes") or 0),
        "constant": _chart_constant(chart),
        "aiConstant": _num((chart.get("feature") or {}).get("aiConstant")),
        "aiConstantRaw": _num((chart.get("feature") or {}).get("aiConstant")),
        "rating": None,
        "accuracy": None,
        "highScore": None,
        "bestScoreRank": 0,
        "goodCount": None,
        "okCount": None,
        "ngCount": None,
        "poundCount": None,
        "fullComboCount": None,
        "dondafulComboCount": None,
        "clearCount": None,
        "updatedAt": "",
        "played": False,
        "rated": False,
    }


def unrated_row(chart: dict, diagnostic: dict | None = None) -> dict:
    """玩家确实打过、但没能进入评级的曲目（谱面资料版本不一致 / 精度低于阈值）。"""
    diagnostic = diagnostic or {}
    row = unplayed_row(chart)
    row["played"] = True
    row["unratedCode"] = diagnostic.get("code") or ""
    row["unratedReason"] = diagnostic.get("reason") or ""
    return row


# ---------------------------------------------------------------------------
# 筛选
# ---------------------------------------------------------------------------

def _passes_numbers(row: dict, spec: dict) -> bool:
    checks = (
        ("constant", spec["constant_min"], spec["constant_max"]),
        ("rating", spec["rating_min"], spec["rating_max"]),
        ("accuracy", spec["accuracy_min"], spec["accuracy_max"]),
        ("highScore", spec["score_min"], spec["score_max"]),
        ("totalNotes", spec["notes_min"], spec["notes_max"]),
    )
    for key, low, high in checks:
        if low is None and high is None:
            continue
        value = row.get(key)
        if value is None:
            return False
        if low is not None and value < low:
            return False
        if high is not None and value > high:
            return False
    return True


def _passes_rank(row: dict, spec: dict) -> bool:
    low, high = spec["rank_min"], spec["rank_max"]
    if low is None and high is None:
        return True
    rank = int(row.get("bestScoreRank") or 0)
    if rank <= 0:
        return False
    if low is not None and rank < low:
        return False
    if high is not None and rank > high:
        return False
    return True


def _passes_counts(row: dict, spec: dict) -> bool:
    for key, low, high in (
        ("okCount", spec["ok_min"], spec["ok_max"]),
        ("ngCount", spec["ng_min"], spec["ng_max"]),
        ("fullComboCount", spec["fc_min"], None),
        ("dondafulComboCount", spec["dondaful_min"], None),
    ):
        if low is None and high is None:
            continue
        value = row.get(key)
        if value is None:
            return False
        if low is not None and value < low:
            return False
        if high is not None and value > high:
            return False
    return True


def _passes_combo(row: dict, mode: str) -> bool:
    if not mode:
        return True
    fc = row.get("fullComboCount")
    dondaful = row.get("dondafulComboCount")
    ng = row.get("ngCount")
    if mode == "full":
        return bool(fc)
    if mode == "no-fc":
        return fc is not None and fc == 0
    if mode == "dondaful":
        return bool(dondaful)
    if mode == "no-miss":
        return ng is not None and ng == 0
    if mode == "miss":
        return ng is not None and ng > 0
    return True


def _passes_level(row: dict, levels) -> bool:
    if not levels:
        return True
    return row.get("level") in levels


def _passes_genre(row: dict, genre: str) -> bool:
    if not genre:
        return True
    return normalize_text(genre) in normalize_text(row.get("genre"))


def _passes_song_no(row: dict, song_no) -> bool:
    if song_no is None:
        return True
    return int(row.get("id") or 0) == song_no


# ---------------------------------------------------------------------------
# 目标评价差距
# ---------------------------------------------------------------------------

def annotate_target(row: dict, charts: dict, rank_data: dict, target_rank) -> None:
    """就地补上目标评价、门槛分数、缺口、所需良数与所需连打数。"""
    if not target_rank:
        return
    song_no = row.get("id")
    level = row.get("level")
    chart = charts.get((song_no, level))
    if not chart:
        return
    song = (rank_data.get("songs") or {}).get(f"{song_no}|{level}")
    threshold = score_rank_mod.rank_threshold(song, int(chart.get("totalNotes") or 0), target_rank)
    target_score = threshold["score"]
    if not target_score:
        return
    row["targetRank"] = target_rank
    row["targetName"] = score_rank_mod.score_rank_name(target_rank)
    row["targetScore"] = target_score
    row["targetExact"] = bool(threshold["exact"])
    row["targetRequiresAllGood"] = bool(threshold.get("requiresAllGood"))
    row["targetRolls"] = threshold.get("rolls") or 0

    current = row.get("highScore")
    if current is None:
        row["gap"] = None
        row["reached"] = False
        return
    # 游戏返回的 best_score_rank 是权威评价；本地门槛只用于推算还差多少分。
    api_rank = int(row.get("bestScoreRank") or 0)
    row["reached"] = api_rank >= target_rank or current >= target_score
    row["gap"] = max(0, target_score - current)
    if row["reached"]:
        return
    unit = threshold["unit"] or 1
    if row["targetRequiresAllGood"]:
        row["okToGood"] = row.get("okCount") or 0
        row["ngToGood"] = row.get("ngCount") or 0
        row["rollsNeeded"] = row["targetRolls"]
        row["rollsAlternative"] = False
    else:
        ok_to_good = int(math.ceil(2 * row["gap"] / unit)) if unit else 0
        row["okToGood"] = ok_to_good
        row["ngToGood"] = 0
        if ok_to_good > (row.get("okCount") or 0):
            remainder = row["gap"] - (row.get("okCount") or 0) * (unit / 2.0)
            row["ngToGood"] = int(math.ceil(remainder / unit)) if unit else 0
        row["rollsNeeded"] = int(math.ceil(row["gap"] / score_rank_mod.ROLL_UNIT))
        row["rollsAlternative"] = True


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def normalize_filters(raw: dict | None) -> dict:
    """把外部传入的参数整理成统一的内部条件字典。"""
    raw = raw or {}
    scope = normalize_text(raw.get("scope")).strip() or "played"
    if scope not in SCOPES:
        scope = "played"
    combo = normalize_text(raw.get("combo")).strip()
    if combo not in COMBO_MODES:
        combo = ""
    levels = raw.get("levels")
    if levels:
        levels = tuple(int(item) for item in levels)
    else:
        levels = None
    reached = normalize_text(raw.get("reached")).strip()
    if reached not in ("", "yes", "no", "all"):
        reached = ""
    gap_max = _limit_max(raw.get("gap_max"))
    # 「缺口上限」只对还没达到目标的曲目有意义：省略 reached 时按「未达成」处理，
    # 否则已达成（缺口 0）的行会混进结果并排在前面。
    if gap_max is not None and reached in ("", "all"):
        reached = "no"
    return {
        "query": raw.get("query") or "",
        "match_mode": raw.get("match_mode") or "contains",
        "match_fields": raw.get("match_fields") or "any",
        "scope": scope,
        "levels": levels,
        "genre": raw.get("genre") or "",
        "song_no": parse_song_no(raw.get("song_no")),
        "combo": combo,
        "constant_min": _limit_min(raw.get("constant_min")),
        "constant_max": _limit_max_positive(raw.get("constant_max")),
        "rating_min": _limit_min(raw.get("rating_min")),
        "rating_max": _limit_max_positive(raw.get("rating_max")),
        "accuracy_min": _ratio(raw.get("accuracy_min")) if _num(raw.get("accuracy_min")) else None,
        "accuracy_max": _ratio(raw.get("accuracy_max")) if _limit_max_positive(raw.get("accuracy_max")) is not None else None,
        "score_min": _limit_min(raw.get("score_min")),
        "score_max": _limit_max_positive(raw.get("score_max")),
        "notes_min": _limit_min(raw.get("notes_min")),
        "notes_max": _limit_max_positive(raw.get("notes_max")),
        "rank_min": _limit_min(raw.get("rank_min")),
        "rank_max": _rank_max(raw.get("rank_max")),
        "ok_min": _limit_min(raw.get("ok_min")),
        "ok_max": _limit_max(raw.get("ok_max")),
        "ng_min": _limit_min(raw.get("ng_min")),
        "ng_max": _limit_max(raw.get("ng_max")),
        "fc_min": _limit_min(raw.get("fc_min")),
        "dondaful_min": _limit_min(raw.get("dondaful_min")),
        "target_rank": score_rank_mod.parse_score_rank(raw.get("target_rank")) if raw.get("target_rank") else None,
        "reached": reached,
        "gap_max": gap_max,
        "sort": normalize_sort(raw.get("sort")),
        "order": "asc" if normalize_text(raw.get("order")).strip() == "asc" else "desc",
        "limit": int(_num(raw.get("limit")) or DEFAULT_LIMIT),
        "offset": int(_num(raw.get("offset")) or 0),
    }


def describe_filters(spec: dict) -> list:
    """把已生效的条件翻译成人类可读短语，便于模型确认自己查了什么。"""
    parts = []
    if spec["query"]:
        mode_label = {"contains": "包含", "exact": "精确等于", "regex": "正则匹配",
                      "all": "同时包含", "any": "任一包含"}.get(spec["match_mode"], "包含")
        parts.append(f"关键词{mode_label}「{spec['query']}」")
    if spec["genre"]:
        parts.append(f"分区含「{spec['genre']}」")
    if spec["levels"]:
        parts.append("难度 " + "/".join(str(item) for item in spec["levels"]))
    if spec["song_no"]:
        parts.append(f"曲目 ID {spec['song_no']}")
    if spec["scope"] == "unplayed":
        parts.append("只看未游玩")
    elif spec["scope"] == "unrated":
        parts.append("只看已游玩但未参与评级")
    elif spec["scope"] == "all":
        parts.append("含未游玩")
    for label, low, high in (
        ("定数", spec["constant_min"], spec["constant_max"]),
        ("Rating", spec["rating_min"], spec["rating_max"]),
        ("音符数", spec["notes_min"], spec["notes_max"]),
        ("分数", spec["score_min"], spec["score_max"]),
    ):
        if low is not None or high is not None:
            parts.append(f"{label} {low if low is not None else '-'}~{high if high is not None else '-'}")
    if spec["accuracy_min"] is not None or spec["accuracy_max"] is not None:
        low = f"{spec['accuracy_min']*100:.2f}%" if spec["accuracy_min"] is not None else "-"
        high = f"{spec['accuracy_max']*100:.2f}%" if spec["accuracy_max"] is not None else "-"
        parts.append(f"精度 {low}~{high}")
    if spec["rank_min"] is not None or spec["rank_max"] is not None:
        low = score_rank_mod.score_rank_name(int(spec["rank_min"])) if spec["rank_min"] is not None else "-"
        high = score_rank_mod.score_rank_name(int(spec["rank_max"])) if spec["rank_max"] is not None else "-"
        parts.append(f"评价 {low}~{high}")
    for label, low, high in (("可", spec["ok_min"], spec["ok_max"]), ("不可", spec["ng_min"], spec["ng_max"])):
        if low is not None or high is not None:
            parts.append(f"{label} {low if low is not None else '-'}~{high if high is not None else '-'}")
    if spec["fc_min"]:
        parts.append(f"全连次数 ≥{spec['fc_min']}")
    if spec["dondaful_min"]:
        parts.append(f"全良次数 ≥{spec['dondaful_min']}")
    combo_label = {"full": "已全连", "no-fc": "未全连", "dondaful": "已全良",
                   "no-miss": "零不可", "miss": "有不可"}.get(spec["combo"])
    if combo_label:
        parts.append(combo_label)
    if spec["target_rank"]:
        parts.append(f"目标评价「{score_rank_mod.score_rank_name(spec['target_rank'])}」")
    if spec["reached"] == "yes":
        parts.append("已达成目标")
    elif spec["reached"] == "no":
        parts.append("未达成目标")
    if spec["gap_max"] is not None:
        parts.append(f"缺口 ≤{int(spec['gap_max'])}")
    return parts


def select(
    records: list,
    charts: dict,
    rank_data: dict,
    alias_index: dict | None = None,
    unrated: list | None = None,
    **raw_filters,
) -> dict:
    """按条件检索成绩／谱面，返回 {total, rows, filters, notes, ...}。

    records: analyze() 得到的 records（可为空列表）。
    charts:  {(song_no, level): chart}
    alias_index: {song_no: [别名, ...]}，用于 match_fields 含 alias 时匹配。
    unrated: 玩家打过但未进入评级的曲目 [{id, level, code, reason}, ...]；
             这些键会被排除出 unplayed，避免把打过的歌报成「没打过」。
    """
    spec = normalize_filters(raw_filters)
    notes = []

    predicate, note = make_matcher(
        spec["query"], spec["match_mode"], spec["match_fields"], alias_index
    )
    if note:
        notes.append(note)

    rated_rows = []
    for record in records:
        chart = charts.get((record.get("id"), record.get("level")))
        if chart:
            rated_rows.append(played_row(record, chart))
    rated_keys = {(row["id"], row["level"]) for row in rated_rows}

    unrated_rows = []
    for item in unrated or []:
        if isinstance(item, dict):
            song_no, level, diagnostic = item.get("id"), item.get("level"), item
        else:
            song_no, level, diagnostic = item[0], item[1], {}
        key = (song_no, level)
        chart = charts.get(key)
        if not chart or key in rated_keys:
            continue
        unrated_rows.append(unrated_row(chart, diagnostic))
    unrated_keys = {(row["id"], row["level"]) for row in unrated_rows}
    known_keys = rated_keys | unrated_keys

    rows = []
    if spec["scope"] in ("played", "all"):
        rows.extend(rated_rows)
    if spec["scope"] in ("unrated", "all"):
        rows.extend(unrated_rows)
    if spec["scope"] in ("unplayed", "all"):
        for key, chart in charts.items():
            if key in known_keys:
                continue
            rows.append(unplayed_row(chart))

    filtered = []
    for row in rows:
        if not _passes_level(row, spec["levels"]):
            continue
        if not _passes_genre(row, spec["genre"]):
            continue
        if not _passes_song_no(row, spec["song_no"]):
            continue
        if not _passes_numbers(row, spec):
            continue
        if not _passes_rank(row, spec):
            continue
        if not _passes_counts(row, spec):
            continue
        if not _passes_combo(row, spec["combo"]):
            continue
        if predicate is not None and not predicate(row):
            continue
        filtered.append(row)

    if spec["target_rank"]:
        for row in filtered:
            annotate_target(row, charts, rank_data, spec["target_rank"])
        if spec["reached"] in ("yes", "no"):
            want = spec["reached"] == "yes"
            filtered = [row for row in filtered if bool(row.get("reached")) is want]
        if spec["gap_max"] is not None:
            before = len(filtered)
            filtered = [
                row for row in filtered
                if row.get("gap") is not None and row["gap"] <= spec["gap_max"]
            ]
            if before != len(filtered):
                notes.append(f"按缺口 ≤{int(spec['gap_max'])} 过滤掉 {before - len(filtered)} 条。")

    total = len(filtered)
    reverse = spec["order"] == "desc"
    sort_key = spec["sort"]

    # 缺失值（例如未游玩曲目的 Rating／分数）不参与排序方向，始终排在最后。
    present = [row for row in filtered if row.get(sort_key) is not None]
    missing = [row for row in filtered if row.get(sort_key) is None]
    if sort_key in ("title", "updated"):
        present.sort(key=lambda row: str(row.get(sort_key)), reverse=reverse)
    else:
        present.sort(key=lambda row: float(row.get(sort_key)), reverse=reverse)
    missing.sort(key=lambda row: (int(row.get("id") or 0), int(row.get("level") or 0)))
    filtered = present + missing

    offset = max(0, spec["offset"])
    limit = max(1, min(int(spec["limit"]), MAX_LIMIT))
    page = filtered[offset:offset + limit]

    return {
        "total": total,
        "shown": len(page),
        "offset": offset,
        "limit": limit,
        "rows": page,
        "filters": spec,
        "filterText": describe_filters(spec),
        "notes": notes,
        "sort": sort_key,
        "order": spec["order"],
    }
