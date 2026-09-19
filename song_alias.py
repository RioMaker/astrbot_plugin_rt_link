# -*- coding: utf-8 -*-
"""曲名 / 别名的统一索引：国服曲名、日文曲名、罗马字（英文）曲名与常用别名。

同一首歌在不同场合叫法完全不同：
- 国服（菌菌）用「国服曲名」，可能是中文（北埼玉2000）、也可能是英文/罗马字（Dragon Night）；
- 日文资料（wiki / 段位道场）用日文曲名（きたさいたま2000）；
- 玩家口语还会用简称与黑话（北埼玉、六天、罗特、顿卡马…）。

本模块把这些写法收进一张归一化索引里，让「段位曲目查询」「成绩查询」「别名申请」
共用同一套匹配规则，避免同一句查询在不同模块得到不同结果。

归一化规则（`normalize`）：NFKC → 大小写折叠 → 常见繁体/异体字折成简体 →
去掉空白与标点。只保留中日文与字母数字，因此「Re：End of a Dream」与
「re end of a dream」会落到同一个 key。

本模块只依赖标准库；AstrBot 解耦，可独立测试。
"""

from __future__ import annotations

import gzip
import json
import re
import unicodedata
from pathlib import Path

ALIAS_SCHEMA_VERSION = 1

# 常见繁体 / 异体字折算（曲名与段位名都会出现）。
TRADITIONAL_MAP = str.maketrans({
    "級": "级", "達": "达", "國": "国", "臺": "台", "號": "号", "龍": "龙",
    "竜": "龙", "櫻": "樱", "戰": "战", "闇": "暗", "曉": "晓", "黃": "黄",
    "黒": "黑", "樂": "乐", "學": "学", "會": "会", "來": "来", "時": "时",
    "萬": "万", "緣": "缘", "聲": "声", "點": "点", "雙": "双", "終": "终",
    "螢": "萤", "戀": "恋", "愛": "爱", "夢": "梦", "亂": "乱", "闘": "斗",
    "鬥": "斗", "響": "响", "顏": "颜", "彈": "弹", "擊": "击", "劍": "剑",
    "鐵": "铁", "銀": "银", "錢": "钱", "賣": "卖", "買": "买", "豐": "丰",
    "與": "与", "為": "为", "無": "无", "煙": "烟", "熱": "热", "獨": "独",
    "現": "现", "環": "环", "產": "产", "異": "异", "發": "发", "髮": "发",
    "盡": "尽", "監": "监", "盤": "盘", "眾": "众", "稱": "称", "積": "积",
    "種": "种", "穩": "稳", "筆": "笔", "節": "节", "範": "范", "築": "筑",
    "簡": "简", "紅": "红", "給": "给", "統": "统", "綠": "绿", "緊": "紧",
    "線": "线", "練": "练", "總": "总", "績": "绩", "縣": "县", "織": "织",
    "續": "续", "網": "网", "聯": "联", "腦": "脑", "臉": "脸", "臨": "临",
    "舉": "举", "舊": "旧", "華": "华", "葉": "叶", "蓋": "盖", "藝": "艺",
    "處": "处", "蟲": "虫", "衝": "冲", "補": "补", "裝": "装", "見": "见",
    "觀": "观", "計": "计", "記": "记", "設": "设", "評": "评", "詞": "词",
    "試": "试", "詩": "诗", "話": "话", "認": "认", "語": "语", "說": "说",
    "課": "课", "調": "调", "談": "谈", "請": "请", "論": "论", "謝": "谢",
    "議": "议", "護": "护", "讀": "读", "變": "变", "讓": "让", "負": "负",
    "財": "财", "責": "责", "貴": "贵", "費": "费", "資": "资", "賽": "赛",
    "質": "质", "購": "购", "車": "车", "軍": "军", "輕": "轻", "輪": "轮",
    "農": "农", "過": "过", "適": "适", "選": "选", "還": "还", "鄉": "乡",
    "醫": "医", "釋": "释", "鐘": "钟", "長": "长", "門": "门", "開": "开",
    "間": "间", "關": "关", "陽": "阳", "隊": "队", "隨": "随", "隱": "隐",
    "難": "难", "雲": "云", "電": "电", "靜": "静", "頁": "页", "頂": "顶",
    "項": "项", "順": "顺", "須": "须", "預": "预", "頭": "头", "題": "题",
    "願": "愿", "類": "类", "風": "风", "飛": "飞", "餘": "余", "馬": "马",
    "驗": "验", "體": "体", "魚": "鱼", "鳥": "鸟", "黨": "党", "齊": "齐",
    "陸": "陆", "島": "岛", "嶋": "岛", "灣": "湾", "關": "关", "燈": "灯",
    # 日本新字体 ↔ 中文简体（同一首歌的日文写法与国服写法常差在这些字上）
    "観": "观", "顏": "颜", "顔": "颜", "譚": "谭", "剣": "剑", "検": "检",
    "権": "权", "沢": "泽", "択": "择", "訳": "译", "駅": "驿", "浜": "滨",
    "蔵": "藏", "臓": "脏", "醸": "酿", "畳": "叠", "縄": "绳", "焼": "烧",
    "収": "收", "獣": "兽", "舎": "舍", "実": "实", "児": "儿", "歯": "齿",
    "剰": "剩", "経": "经", "県": "县", "険": "险", "蛍": "萤", "齢": "龄",
    "亀": "龟", "遅": "迟", "穂": "穗", "悪": "恶", "圧": "压", "圏": "圈",
    "堅": "坚", "寛": "宽", "対": "对", "帯": "带", "帰": "归", "廃": "废",
    "抜": "拔", "拠": "据", "拡": "扩", "摂": "摄", "断": "断", "昼": "昼",
    "楼": "楼", "欧": "欧", "浄": "净", "済": "济", "絵": "绘", "続": "续",
    "総": "总", "薬": "药", "覧": "览", "証": "证", "読": "读", "誰": "谁",
    "貯": "贮", "賛": "赞", "転": "转", "郷": "乡", "酔": "醉", "鉄": "铁",
    "銭": "钱", "錬": "炼", "雑": "杂", "静": "静", "髪": "发", "黄": "黄",
    # 国服曲名里也常混入日文字形（例如「天体観測」），这些折算让简中输入也能命中
    "測": "测", "戦": "战", "変": "变", "気": "气", "撃": "击", "殺": "杀",
    "桜": "樱", "黒": "黑", "鏡": "镜", "縁": "缘", "芸": "艺", "覚": "觉",
    "説": "说", "単": "单", "団": "团", "広": "广", "応": "应", "壊": "坏",
    "満": "满", "歴": "历", "涙": "泪", "戸": "户", "弐": "贰", "悩": "恼",
    "拝": "拜", "掛": "挂", "採": "采", "斉": "齐", "糸": "丝", "縦": "纵",
    "繋": "系", "罰": "罚", "聴": "听", "腸": "肠", "舗": "铺", "荘": "庄",
    "菓": "果", "講": "讲", "謎": "谜", "販": "贩", "贈": "赠", "軽": "轻",
    "醜": "丑", "録": "录", "陥": "陷", "霊": "灵", "駆": "驱", "鳴": "鸣",
})

_PUNCT_RE = re.compile(r"[^0-9a-z一-龥ぁ-んァ-ヶ]+")


def _fold_kana(text: str) -> str:
    """片假名折成平假名：让「ドンカマ2000」与「どんかま2000」落到同一个 key。"""
    return "".join(
        chr(ord(char) - 0x60) if "ァ" <= char <= "ヶ" else char
        for char in text
    )


def normalize(value) -> str:
    """曲名归一化 key：NFKC、大小写折叠、片假名折平假名、繁简折算、去空白与标点。"""
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = _fold_kana(text)
    text = text.translate(TRADITIONAL_MAP)
    return _PUNCT_RE.sub("", text)


def empty_aliases() -> dict:
    """别名资源不可用时的空表；此时只按谱面库原本的曲名匹配。"""
    return {
        "schema_version": ALIAS_SCHEMA_VERSION,
        "data_version": "unavailable",
        "sources": {},
        "songs": {},
        "index": {},
        "song_index": {},
        "ambiguous": {},
    }


def load_aliases(path, charts: dict | None = None) -> dict:
    """加载并校验 resource/aliases.v1.json.gz，并建立归一化索引。

    每个谱面条目：
        names    规范曲名（国服 / 日文 / 罗马字），用于展示
        aliases  额外别名（简称、黑话、段位资料里的写法）
        sources  每个名字的来源，便于排查

    返回 {"songs": {...}, "index": {归一化key: [chart key]}, "song_index": {song_no: [names]}}。
    """
    raw = Path(path).read_bytes()
    if str(path).endswith(".gz"):
        raw = gzip.decompress(raw)
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("别名资源根节点必须是对象")
    if payload.get("schema_version") != ALIAS_SCHEMA_VERSION:
        raise ValueError(f"不支持的别名资源版本：{payload.get('schema_version')}")
    songs = payload.get("songs")
    if not isinstance(songs, dict):
        raise ValueError("别名资源缺少 songs")

    cleaned: dict[str, dict] = {}
    for key, value in songs.items():
        if not isinstance(value, dict):
            raise ValueError(f"别名条目必须是对象：{key}")
        song_no_text, _, level_text = str(key).partition("|")
        if not song_no_text.isdigit() or not level_text.isdigit():
            raise ValueError(f"别名条目的键格式无效：{key}")
        names = [str(item) for item in (value.get("names") or []) if str(item or "").strip()]
        aliases = [str(item) for item in (value.get("aliases") or []) if str(item or "").strip()]
        if not names and not aliases:
            continue
        cleaned[key] = {"names": names, "aliases": aliases}

    index: dict[str, list[str]] = {}
    song_index: dict[str, list[str]] = {}
    ambiguous: dict[str, list[str]] = {}
    for key, item in cleaned.items():
        song_no = key.partition("|")[0]
        seen = set()
        for value in item["names"] + item["aliases"]:
            norm = normalize(value)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            index.setdefault(norm, [])
            if key not in index[norm]:
                index[norm].append(key)
            names = song_index.setdefault(song_no, [])
            if value not in names:
                names.append(value)
    for norm, keys in index.items():
        if len({key.partition("|")[0] for key in keys}) > 1:
            ambiguous[norm] = keys

    return {
        "schema_version": payload.get("schema_version"),
        "data_version": payload.get("data_version") or "unknown",
        "sources": payload.get("sources") or {},
        "songs": cleaned,
        "index": index,
        "song_index": song_index,
        "ambiguous": ambiguous,
        "catalog_charts": len(charts) if charts else 0,
    }


def names_of(alias_data: dict | None, song_no, level=None) -> list:
    """取某首歌的规范名 + 别名；指定 level 时优先该难度的写法。"""
    if not alias_data:
        return []
    songs = alias_data.get("songs") or {}
    if level is not None:
        item = songs.get(f"{song_no}|{level}")
        if item:
            return list(item["names"]) + list(item["aliases"])
    names: list[str] = []
    for key, item in songs.items():
        if key.partition("|")[0] == str(song_no):
            for value in item["names"] + item["aliases"]:
                if value not in names:
                    names.append(value)
    return names


def display_name(alias_data: dict | None, song_no, level=None, fallback: str = "") -> str:
    """展示用曲名：优先别名资源里的规范名（国服名 → 日文名 → 罗马字）。"""
    names = names_of(alias_data, song_no, level) or names_of(alias_data, song_no)
    return names[0] if names else (fallback or f"Song {song_no}")


def resolve(
    alias_data: dict | None,
    text,
    level=None,
    limit: int = 8,
) -> list:
    """按曲名 / 别名解析曲目，返回 [{song_no, level, name, quality}]。

    匹配优先级：完全相等 > 前缀 > 包含。`level` 给定时，该难度的条目排前面；
    同一首歌的多个难度会合并成一条（保留命中难度的 key）。
    """
    query = normalize(text)
    if not query:
        return []
    index = (alias_data or {}).get("index") or {}
    if not index:
        return []

    hits: list[tuple[int, str]] = []   # (quality, chart key)
    for key, values in index.items():
        if key == query:
            quality = 0
        elif key.startswith(query) or query.startswith(key):
            quality = 1
        elif query in key:
            quality = 2
        else:
            continue
        for chart_key in values:
            hits.append((quality, chart_key))

    # 同一首歌命中多个难度时只保留一条：优先匹配请求的难度，其次更低难度。
    best: dict[str, tuple] = {}
    for quality, chart_key in hits:
        song_no, _, chart_level = chart_key.partition("|")
        level_penalty = 0 if (level is not None and int(chart_level) == int(level)) else 1
        score = (quality, level_penalty, int(chart_level), int(song_no))
        current = best.get(song_no)
        if current is None or score < current[0]:
            best[song_no] = (score, chart_key)

    ordered = sorted(best.values(), key=lambda item: item[0])
    results = []
    for score, chart_key in ordered[: max(1, int(limit))]:
        song_no, _, chart_level = chart_key.partition("|")
        item = (alias_data.get("songs") or {}).get(chart_key) or {}
        names = list(item.get("names") or []) + list(item.get("aliases") or [])
        results.append({
            "song_no": int(song_no),
            "level": int(chart_level),
            "name": names[0] if names else "",
            "names": names,
            "quality": ("exact", "prefix", "contains")[score[0]],
        })
    return results


def match_names(alias_data: dict | None, text) -> set:
    """返回文本精确命中的 song_no 集合（给别名表用）。"""
    query = normalize(text)
    if not query:
        return set()
    index = (alias_data or {}).get("index") or {}
    return {int(key.partition("|")[0]) for key in index.get(query, [])}


def build_alias_index(alias_data: dict | None, extra: dict | None = None) -> dict:
    """给检索层用的 {song_no: [别名...]}：内置别名 + 用户提交的已审别名。"""
    index: dict[int, list[str]] = {}
    for song_no, names in ((alias_data or {}).get("song_index") or {}).items():
        index.setdefault(int(song_no), [])
        for name in names:
            if name not in index[int(song_no)]:
                index[int(song_no)].append(name)
    for alias, song_no in (extra or {}).items():
        try:
            key = int(song_no)
        except (TypeError, ValueError):
            continue
        index.setdefault(key, [])
        if alias not in index[key]:
            index[key].append(alias)
    return index
