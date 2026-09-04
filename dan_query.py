# -*- coding: utf-8 -*-
"""段位道场资料的只读查询与 LLM 友好文本格式化。"""

from __future__ import annotations

import re
import unicodedata


REGION_LABELS = {"jp_worldwide": "日版/国际版", "cn": "中国大陆版"}
REGION_ALIASES = {
    "jp": "jp_worldwide", "japan": "jp_worldwide", "world": "jp_worldwide",
    "jpworldwide": "jp_worldwide",
    "worldwide": "jp_worldwide", "日版": "jp_worldwide", "国际版": "jp_worldwide",
    "國際版": "jp_worldwide", "日本": "jp_worldwide",
    "cn": "cn", "china": "cn", "国服": "cn", "國服": "cn",
    "中国": "cn", "中國": "cn", "中国大陆": "cn", "中國大陸": "cn",
}
METRIC_LABELS = {
    "soul_gauge": "魂槽", "hit_count": "叩击数", "good_count": "良",
    "ok_count": "可", "bad_count": "不可", "drumroll_count": "连打",
}
SCOPE_LABELS = {"course": "三曲合计", "per_song": "逐曲"}
UNIT_SUFFIXES = {"percent": "%", "count": ""}


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    value = value.translate(str.maketrans({"級": "级", "達": "达", "國": "国"}))
    return re.sub(r"[^0-9a-z一-龥ぁ-んァ-ヶ]+", "", value)


def _region(value: str) -> str | None:
    if not value:
        return None
    return REGION_ALIASES.get(_norm(value))


def _value_text(value, unit: str) -> str:
    suffix = UNIT_SUFFIXES.get(unit, "")
    if isinstance(value, list):
        return " / ".join(f"{item}{suffix}" for item in value)
    return f"{value}{suffix}"


def _condition_text(condition: dict) -> str:
    label = METRIC_LABELS.get(condition.get("metric"), condition.get("metric", "条件"))
    scope = SCOPE_LABELS.get(condition.get("scope"), condition.get("scope", ""))
    operator = "≥" if condition.get("operator") == ">=" else "<"
    unit = condition.get("unit", "count")
    normal = _value_text(condition.get("normal"), unit)
    gold = _value_text(condition.get("gold"), unit)
    return f"- {label}（{scope}）：普通 {operator}{normal}；金 {operator}{gold}"


def _header(catalog: dict) -> str:
    return f"段位道场资料版本：{catalog.get('data_version', 'unknown')}"


def _format_course(catalog: dict, course: dict) -> str:
    region = REGION_LABELS.get(course["region"], course["region"])
    closes = course.get("closes_at") or "未记录"
    lines = [
        f"{course['year']} {region} {course['rank']}",
        f"开放：{course.get('opens_at') or '未记录'}；结束：{closes}",
        "课题曲：",
    ]
    for song in course["songs"]:
        ids = song.get("song_no_candidates") or []
        id_text = ",".join(str(value) for value in ids) if ids else "当前曲库无 ID"
        lines.append(
            f"{song['order']}. {song['title']}（{song['difficulty']}★{song['stars']}，"
            f"{song['total_notes']} 音符，song_no={id_text}）"
        )
    lines.append("合格条件（普通 / 金）：")
    lines.extend(_condition_text(condition) for condition in course["conditions"])
    lines.append("来源：")
    for source_id in course.get("source_ids", []):
        lines.append(f"- {source_id}: {catalog['sources'][source_id]}")
    return "\n".join(lines)


def query_dan_courses_text(
    catalog: dict,
    year: int = 0,
    region: str = "",
    rank: str = "",
    song_name: str = "",
    song_no: int = 0,
) -> str:
    """按条件查询段位课程，返回适合模型直接引用的紧凑文本。"""
    courses = catalog.get("courses", [])
    if not courses:
        return "段位道场资料当前不可用。"

    region_key = _region(region)
    if region and region_key is None:
        return "区域参数无法识别。可用：cn/国服/中国大陆，jp/日版/国际版。"

    filters_used = bool(year or region or rank or song_name or song_no)
    if not filters_used:
        years = sorted({course["year"] for course in courses})
        return (
            f"{_header(catalog)}\n"
            f"可查询年份：{', '.join(map(str, years))}\n"
            "区域：cn（中国大陆版）、jp_worldwide（日版/国际版）\n"
            "段位：五级、四级、三级、二级、一级、初段至十段、玄人、名人、超人、达人。\n"
            "请按年份+区域+段位查询完整课题曲与条件；也可用 song_name 或 song_no 反查段位。"
        )

    rank_key = _norm(rank)
    title_key = _norm(song_name)
    matched = []
    for course in courses:
        if year and course["year"] != year:
            continue
        if region_key and course["region"] != region_key:
            continue
        if rank_key and _norm(course["rank"]) != rank_key:
            continue
        song_matches = []
        for song in course["songs"]:
            title_match = title_key and title_key in _norm(song["title"])
            id_match = song_no and song_no in song.get("song_no_candidates", [])
            if title_match or id_match:
                song_matches.append(song)
        if (title_key or song_no) and not song_matches:
            continue
        matched.append((course, song_matches))

    if not matched:
        return f"{_header(catalog)}\n没有找到符合条件的段位资料。"

    exact_course_query = bool(rank_key) and len(matched) <= 2 and not (title_key or song_no)
    if exact_course_query:
        return _header(catalog) + "\n\n" + "\n\n".join(
            _format_course(catalog, course) for course, _ in matched
        ) + "\n\n说明：单曲历史成绩只能作为段位能力参考，不能据此断言玩家已通过段位。"

    if title_key or song_no:
        lines = [_header(catalog), f"找到 {len(matched)} 条段位出现记录："]
        for course, songs in matched[:30]:
            region_label = REGION_LABELS.get(course["region"], course["region"])
            for song in songs:
                lines.append(
                    f"- {course['year']} {region_label} {course['rank']} 第{song['order']}曲："
                    f"{song['title']}（{song['difficulty']}★{song['stars']}，{song['total_notes']} 音符）"
                )
        if len(matched) > 30:
            lines.append("结果较多，仅显示前 30 条；请增加年份、区域或段位筛选。")
        return "\n".join(lines)

    years = sorted({course["year"] for course, _ in matched})
    regions = sorted({REGION_LABELS.get(course["region"], course["region"]) for course, _ in matched})
    ranks = sorted({course["rank"] for course, _ in matched}, key=lambda value: next(
        course["rank_order"] for course, _ in matched if course["rank"] == value
    ))
    return (
        f"{_header(catalog)}\n"
        f"匹配课程：{len(matched)} 个；年份：{', '.join(map(str, years))}；"
        f"区域：{', '.join(regions)}\n"
        f"可用段位：{', '.join(ranks)}\n"
        "请补充 rank 获取完整三曲、合格条件与来源。"
    )


def _best_score(rows: list[dict]) -> dict | None:
    if not rows:
        return None
    return max(rows, key=lambda row: (
        int(row.get("high_score") or 0),
        int(row.get("best_score_rank") or 0),
        -int(row.get("ng_cnt") or 0),
        -int(row.get("ok_cnt") or 0),
        str(row.get("update_datetime") or row.get("highscore_datetime") or ""),
    ))


def _score_metric(row: dict, metric: str) -> int | None:
    field = {
        "good_count": "good_cnt", "ok_count": "ok_cnt", "bad_count": "ng_cnt",
        "drumroll_count": "pound_cnt",
    }.get(metric)
    if field:
        value = row.get(field)
        return int(value) if value is not None else None
    if metric == "hit_count":
        fields = ("good_cnt", "ok_cnt", "ng_cnt", "pound_cnt")
        if any(row.get(field_name) is None for field_name in fields):
            return None
        return sum(int(row[field_name]) for field_name in fields)
    return None


def _passes(actual: int, target: int, operator: str) -> bool:
    return actual >= target if operator == ">=" else actual < target


def _evaluation_line(condition: dict, score_rows: list[dict | None]) -> tuple[str, bool | None, bool | None]:
    metric = condition["metric"]
    label = METRIC_LABELS.get(metric, metric)
    scope = SCOPE_LABELS.get(condition.get("scope"), condition.get("scope", ""))
    if metric == "soul_gauge":
        return f"- {label}（{scope}）：普通单曲成绩不包含魂槽，无法核对", None, None
    if any(row is None for row in score_rows):
        return f"- {label}（{scope}）：三曲成绩不完整，无法核对", None, None

    values = [_score_metric(row, metric) for row in score_rows]
    if any(value is None for value in values):
        return f"- {label}（{scope}）：同步数据缺少所需字段，无法核对", None, None
    if condition.get("scope") == "course":
        actual = sum(values)
        actual_text = str(actual)
        normal_ok = _passes(actual, int(condition["normal"]), condition["operator"])
        gold_ok = _passes(actual, int(condition["gold"]), condition["operator"])
    else:
        actual = values
        actual_text = " / ".join(map(str, actual))
        normal_ok = all(
            _passes(value, int(target), condition["operator"])
            for value, target in zip(actual, condition["normal"])
        )
        gold_ok = all(
            _passes(value, int(target), condition["operator"])
            for value, target in zip(actual, condition["gold"])
        )
    target_normal = _value_text(condition["normal"], condition.get("unit", "count"))
    target_gold = _value_text(condition["gold"], condition.get("unit", "count"))
    operator = "≥" if condition["operator"] == ">=" else "<"
    return (
        f"- {label}（{scope}）：实际 {actual_text}；"
        f"普通要求 {operator}{target_normal} [{'满足' if normal_ok else '未满足'}]；"
        f"金要求 {operator}{target_gold} [{'满足' if gold_ok else '未满足'}]",
        normal_ok,
        gold_ok,
    )


def evaluate_player_dan_text(
    catalog: dict,
    score_rows: list[dict],
    year: int,
    region: str,
    rank: str,
) -> str:
    """用玩家各课题谱面的当前最佳记录核对可计算的段位条件。"""
    region_key = _region(region)
    if not year or region_key is None or not rank:
        return "评估过段能力需要明确 year、region 和 rank。"
    course = next((
        item for item in catalog.get("courses", [])
        if item.get("year") == int(year)
        and item.get("region") == region_key
        and _norm(item.get("rank", "")) == _norm(rank)
    ), None)
    if course is None:
        return f"未找到 {year} {region} {rank} 的段位资料。"

    selected = []
    lines = [
        f"玩家段位能力参考｜{course['year']} {REGION_LABELS[course['region']]} {course['rank']}",
        "课题曲当前最佳记录：",
    ]
    for song in course["songs"]:
        candidates = set(song.get("song_no_candidates") or [])
        matches = [
            row for row in score_rows
            if row.get("song_no") in candidates and row.get("level") == song["level"]
        ]
        best = _best_score(matches)
        selected.append(best)
        if best is None:
            reason = "当前段位曲库无可关联 ID" if not candidates else "尚无同步成绩"
            lines.append(
                f"{song['order']}. {song['title']}（{song['difficulty']}★{song['stars']}）：{reason}"
            )
            continue
        lines.append(
            f"{song['order']}. {song['title']}（{song['difficulty']}★{song['stars']}）："
            f"良 {best.get('good_cnt')} / 可 {best.get('ok_cnt')} / 不可 {best.get('ng_cnt')} / "
            f"连打 {best.get('pound_cnt')} / 最高连击 {best.get('combo_cnt')} / "
            f"分数 {best.get('high_score')}（{best.get('source')}，"
            f"{best.get('update_datetime') or best.get('highscore_datetime') or '时间未知'}）"
        )

    lines.append("条件核对：")
    normal_results = []
    gold_results = []
    missing_evaluable_data = False
    for condition in course["conditions"]:
        text, normal_ok, gold_ok = _evaluation_line(condition, selected)
        lines.append(text)
        if condition.get("metric") != "soul_gauge" and normal_ok is None:
            missing_evaluable_data = True
        if normal_ok is not None:
            normal_results.append(normal_ok)
        if gold_ok is not None:
            gold_results.append(gold_ok)

    complete = all(row is not None for row in selected)
    if not complete:
        conclusion = "成绩不完整，暂时无法评估可计算条件。请先 /rtlink update 同步全部难度成绩。"
    elif missing_evaluable_data:
        conclusion = "部分良/可/不可或连打字段缺失，暂时无法完整评估可计算条件。"
    elif normal_results and not all(normal_results):
        conclusion = "各曲最佳记录中仍有普通合格条件未满足。"
    elif gold_results and all(gold_results):
        conclusion = "各曲最佳记录满足目前可计算的金合格条件。"
    else:
        conclusion = "各曲最佳记录满足目前可计算的普通合格条件。"
    lines.extend([
        f"参考结论：{conclusion}",
        "重要限制：这些是三首歌各自的最佳单曲记录，不是同一次段位道场连续演奏；普通成绩接口也不提供段位魂槽，因此不能据此断言已经过段。",
    ])
    return "\n".join(lines)
