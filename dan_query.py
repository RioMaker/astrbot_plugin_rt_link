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
