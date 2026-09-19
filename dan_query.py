# -*- coding: utf-8 -*-
"""段位道场资料的只读查询与 LLM 友好文本格式化。

曲名匹配走 `song_alias`：段位资料里存的多是日文写法，而玩家通常按国服曲名或常用别名提问
（「北埼玉」「六天」「罗特」…）。这里把「段位曲名 + 谱面库曲名 + 别名」合成一张写法集合后
再匹配，并在结果里同时给出国服曲名、日文曲名与 RTLink 曲目 ID。
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
import sys

if __package__:
    from . import song_alias as song_alias_mod
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import song_alias as song_alias_mod


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

# 谱面难度写法（段位资料里的 difficulty 是「普通/玄人/达人」分支，不能用它判断难度）。
LEVEL_WORDS = {
    "1": 1, "梅": 1, "easy": 1,
    "2": 2, "竹": 2, "normal": 2,
    "3": 3, "松": 3, "hard": 3,
    "4": 4, "鬼": 4, "魔王": 4, "oni": 4, "mania": 4,
    "5": 5, "里": 5, "里鬼": 5, "里魔王": 5, "ura": 5,
}
LEVEL_LABELS = {1: "梅", 2: "竹", 3: "松", 4: "鬼", 5: "里"}
# 分歧谱的三个分支写法；与难度同名时（非分歧谱）不重复展示。
BRANCH_LABELS = ("普通", "玄人", "达人")


def _difficulty_text(song: dict) -> str:
    level_label = LEVEL_LABELS.get(song.get("level"), str(song.get("level")))
    text = f"{level_label}★{song.get('stars')}"
    difficulty = str(song.get("difficulty") or "").strip()
    if difficulty in BRANCH_LABELS and difficulty != level_label:
        text += f"·{difficulty}"
    return text


def _norm(value: str) -> str:
    return song_alias_mod.normalize(value)


def split_level(text: str) -> tuple[int | None, str]:
    """从曲名里剥出难度前缀（鬼/里/松/竹/梅/数字），返回 (level, 剩余曲名)。"""
    raw = unicodedata.normalize("NFKC", str(text or "")).strip()
    if not raw:
        return None, ""
    match = re.match(r"^(梅|竹|松|鬼|里鬼|里魔王|里|魔王|easy|normal|hard|oni|mania|ura|[1-5])\s*[：:·\-—\s]+(.+)$",
                     raw, re.IGNORECASE)
    if not match:
        return None, raw
    level = LEVEL_WORDS.get(match.group(1).lower())
    if level is None:
        return None, raw
    return level, match.group(2).strip()


def _region(value: str) -> str | None:
    return match_region(value)


def match_region(value: str) -> str | None:
    """把区域写法解析成 cn / jp_worldwide；无法识别返回 None。"""
    if not value:
        return None
    return REGION_ALIASES.get(_norm(value))


# 段位名称（五级…一级、初段…十段、玄人/名人/超人/达人）。
RANK_WORDS = (
    "五级", "四级", "三级", "二级", "一级",
    "初段", "一段", "二段", "三段", "四段", "五段", "六段", "七段", "八段", "九段", "十段",
    "玄人", "名人", "超人", "达人",
)
_RANK_KEYS = {_norm(word): word for word in RANK_WORDS}


def match_rank(value: str) -> str:
    """把段位写法解析成资料里的标准段位名；无法识别返回空串。"""
    return _RANK_KEYS.get(_norm(value), "")


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


def _song_labels(song: dict, alias_data: dict | None) -> tuple[str, str, int | None]:
    """返回 (展示曲名, 备注, 当前曲库 ID)。

    展示曲名优先用别名资源里的国服/日文写法（段位资料本身多为日文），
    再退回段位资料里的写法；解析不到当前曲库时给出提示。
    """
    title = str(song.get("title") or "").strip()
    level = song.get("level")
    resolved = None
    for song_no in song.get("song_no_candidates") or []:
        if alias_data and f"{song_no}|{level}" in (alias_data.get("songs") or {}):
            resolved = song_no
            break
    if resolved is None:
        for song_no in song.get("song_no_candidates") or []:
            if alias_data and song_no in (alias_data.get("song_index") or {}):
                resolved = song_no
                break
    if resolved is None:
        return title, "（当前曲库无此曲）", None
    # 展示用「国服名（日文名）」：只看规范曲名，不拿简称/黑话当第二名字。
    item = ((alias_data or {}).get("songs") or {}).get(f"{resolved}|{level}") or {}
    canonical = [name for name in (item.get("names") or []) if name]
    display = canonical[0] if canonical else title
    other = next((name for name in canonical[1:] if name != display), "")
    label = f"《{display}》"
    if other:
        label += f"（{other}）"
    return label, "", resolved


def _format_course(catalog: dict, course: dict, alias_data: dict | None = None) -> str:
    region = REGION_LABELS.get(course["region"], course["region"])
    closes = course.get("closes_at") or "未记录"
    lines = [
        f"{course['year']} {region} {course['rank']}",
        f"开放：{course.get('opens_at') or '未记录'}；结束：{closes}",
        "课题曲：",
    ]
    for song in course["songs"]:
        label, note, song_no = _song_labels(song, alias_data)
        id_text = f"ID {song_no}" if song_no else "、".join(
            str(value) for value in (song.get("song_no_candidates") or [])
        ) or "无 ID"
        lines.append(
            f"{song['order']}. {label}{note} · {_difficulty_text(song)}"
            f"｜{song['total_notes']} 音符｜{id_text}"
        )
    lines.append("合格条件（普通 / 金）：")
    lines.extend(_condition_text(condition) for condition in course["conditions"])
    lines.append("来源：")
    for source_id in course.get("source_ids", []):
        lines.append(f"- {source_id}: {catalog['sources'][source_id]}")
    return "\n".join(lines)


def _match_song(song: dict, title_key: str, song_ids: set, alias_data: dict | None,
                level: int | None) -> bool:
    """判断段位课题曲是否命中查询：难度前缀 → ID 直配 → 段位曲名 → 该曲任一别名。"""
    if level is not None and song.get("level") != level:
        return False
    candidates = set(song.get("song_no_candidates") or [])
    if song_ids and candidates & song_ids:
        return True
    if not title_key:
        return False
    if title_key in _norm(song.get("title")):
        return True
    for song_no in candidates:
        for name in song_alias_mod.names_of(alias_data, song_no, song.get("level")):
            key = _norm(name)
            if key and (title_key in key or key in title_key):
                return True
    return False


def query_dan_courses_text(
    catalog: dict,
    year: int = 0,
    region: str = "",
    rank: str = "",
    song_name: str = "",
    song_no: int = 0,
    alias_data: dict | None = None,
) -> str:
    """按条件查询段位课程，返回适合模型直接引用的紧凑文本。

    song_name / song_no 支持国服曲名、日文曲名、罗马字与常用别名（见 `song_alias`），
    也可以写成「鬼 天竺2000」这样带难度前缀的形式。
    """
    courses = catalog.get("courses", [])
    if not courses:
        return "段位道场资料当前不可用。"

    region_key = _region(region)
    if region and region_key is None:
        return "区域参数无法识别。可用：cn/国服/中国大陆，jp/日版/国际版。"

    level_filter, clean_name = split_level(song_name)
    title_key = _norm(clean_name)
    song_ids: set = set()
    if song_no:
        song_ids.add(int(song_no))
    elif title_key:
        for hit in song_alias_mod.resolve(alias_data, clean_name, limit=12):
            song_ids.add(int(hit["song_no"]))

    filters_used = bool(year or region or rank or title_key or song_no)
    if not filters_used:
        years = sorted({course["year"] for course in courses})
        ranks = sorted({course["rank"] for course in courses},
                       key=lambda value: min(course["rank_order"] for course in courses
                                             if course["rank"] == value))
        return (
            f"{_header(catalog)}\n"
            f"可查询年份：{', '.join(map(str, years))}\n"
            "区域：cn（中国大陆版）、jp_worldwide（日版/国际版）\n"
            f"段位：{'、'.join(ranks)}。\n"
            "请按年份+区域+段位查询完整课题曲与条件；也可用 song_name 或 song_no 反查段位。\n"
            "曲名支持国服名、日文名、罗马字与常用别名（例如「北埼玉」「六天」「罗特」），"
            "也可以写「鬼 天竺2000」指定难度。"
        )

    rank_key = _norm(rank)
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
            if (title_key or song_no) and not _match_song(
                song, title_key, song_ids, alias_data, level_filter
            ):
                continue
            song_matches.append(song)
        if (title_key or song_no) and not song_matches:
            continue
        matched.append((course, song_matches))

    if not matched:
        return _no_match_text(catalog, title_key or song_name, song_ids, level_filter)

    exact_course_query = bool(rank_key) and len(matched) <= 2 and not (title_key or song_no)
    if exact_course_query:
        return _header(catalog) + "\n\n" + "\n\n".join(
            _format_course(catalog, course, alias_data) for course, _ in matched
        ) + "\n\n说明：单曲历史成绩只能作为段位能力参考，不能据此断言玩家已通过段位。"

    if title_key or song_no:
        matched.sort(key=lambda item: (-item[0]["year"], item[0]["region"], item[0]["rank_order"]))
        total = sum(len(songs) for _, songs in matched)
        lines = [_header(catalog), f"找到 {total} 条段位出现记录（按年份倒序）："]
        shown = 0
        for course, songs in matched:
            region_label = REGION_LABELS.get(course["region"], course["region"])
            for song in songs:
                if shown >= 30:
                    break
                label, note, resolved = _song_labels(song, alias_data)
                id_text = f"｜ID {resolved}" if resolved else ""
                lines.append(
                    f"- {course['year']} {region_label} {course['rank']} 第{song['order']}曲："
                    f"{label}{note} · {_difficulty_text(song)}"
                    f"｜{song['total_notes']} 音符{id_text}"
                )
                shown += 1
        if total > shown:
            lines.append(f"结果较多，仅显示前 {shown} 条；请增加年份、区域或段位筛选。")
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


def _no_match_text(catalog: dict, query: str, song_ids: set, level: int | None) -> str:
    """没匹配上时给出可用的写法提示，而不是一句「没找到」。"""
    lines = [f"{_header(catalog)}", f"没有找到符合条件的段位资料（查询：{query}）。"]
    if song_ids:
        lines.append(
            f"其中 {', '.join(str(value) for value in sorted(song_ids))} 号曲目在当前段位资料里没有出现记录。"
        )
    if level is not None:
        lines.append(f"已按 {LEVEL_LABELS.get(level, level)} 难度筛选；去掉难度前缀可以查全部难度。")
    lines.append("提示：曲名支持国服名、日文名、罗马字与常用别名；也可以直接用 song_no。"
                 "若确认该曲名没被收录，可用 /rtlink alias <曲名或ID> <别名> 提交补充。")
    return "\n".join(lines)


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
    alias_data: dict | None = None,
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
        label, _note, _resolved = _song_labels(song, alias_data)
        if best is None:
            reason = "当前段位曲库无可关联 ID" if not candidates else "尚无同步成绩"
            lines.append(
                f"{song['order']}. {label}（{_difficulty_text(song)}）：{reason}"
            )
            continue
        lines.append(
            f"{song['order']}. {label}（{_difficulty_text(song)}）："
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
