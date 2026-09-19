# -*- coding: utf-8 -*-
"""曲名别名（国服名 / 日文名 / 罗马字 / 常用别名）索引的单元测试。

覆盖：归一化规则、资源加载与校验、解析优先级（完全相等 > 前缀 > 包含）、
难度偏好、以及内置别名资源对已知曲目的解析结果。
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parent.parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

import song_alias as sa  # noqa: E402

RESOURCE = PLUGIN_DIR / "resource" / "aliases.v1.json.gz"


# ---------------------------------------------------------------------------
# 归一化
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("left,right", [
    ("Re：End of a Dream", "Re:End of a Dream"),
    ("きたさいたま2000", "きたさいたま 2000"),
    ("Rotter Tarmination", "rottertarmination"),
    ("黄ダルマ2000", "黃ダルマ2000"),
    ("双竜ノ乱", "雙龍ノ亂"),
    ("てんぢく2000", "てんぢく２０００"),
    ("ドンカマ2000", "どんかま2000"),
])
def test_normalize_folds_case_punctuation_and_traditional(left, right):
    assert sa.normalize(left) == sa.normalize(right)


def test_normalize_keeps_kanji_and_folds_kana():
    assert sa.normalize("天狗囃子") == "天狗囃子"
    assert sa.normalize("ラビットホール") == sa.normalize("らびっとほーる")


# ---------------------------------------------------------------------------
# 资源加载
# ---------------------------------------------------------------------------

def _write_resource(tmp_path, payload) -> Path:
    path = tmp_path / "aliases.v1.json.gz"
    path.write_bytes(gzip.compress(json.dumps(payload, ensure_ascii=False).encode("utf-8")))
    return path


def _payload(songs: dict) -> dict:
    return {"schema_version": 1, "data_version": "test", "sources": {}, "songs": songs}


def test_load_aliases_builds_index(tmp_path):
    path = _write_resource(tmp_path, _payload({
        "1|4": {"names": ["天竺2000", "てんぢく2000"], "aliases": ["天竺", "Tenjiku 2000"]},
        "2|4": {"names": ["Dragon Night"], "aliases": []},
    }))
    data = sa.load_aliases(path)
    assert data["data_version"] == "test"
    assert set(data["songs"]) == {"1|4", "2|4"}
    # 归一化后的 key 能命中所有写法
    assert data["index"]["てんぢく2000"] == ["1|4"]
    assert data["index"]["tenjiku2000"] == ["1|4"]
    assert data["index"]["dragonnight"] == ["2|4"]


def test_load_aliases_rejects_wrong_schema(tmp_path):
    path = _write_resource(tmp_path, {"schema_version": 99, "songs": {}})
    with pytest.raises(ValueError):
        sa.load_aliases(path)


def test_load_aliases_rejects_invalid_key(tmp_path):
    path = _write_resource(tmp_path, _payload({"bad-key": {"names": ["x"], "aliases": []}}))
    with pytest.raises(ValueError):
        sa.load_aliases(path)


def test_load_aliases_marks_ambiguous_names(tmp_path):
    path = _write_resource(tmp_path, _payload({
        "1|4": {"names": ["同名曲"], "aliases": []},
        "2|4": {"names": ["同名曲"], "aliases": []},
    }))
    data = sa.load_aliases(path)
    assert sa.normalize("同名曲") in data["ambiguous"]
    assert len(sa.resolve(data, "同名曲")) == 2


# ---------------------------------------------------------------------------
# 解析优先级
# ---------------------------------------------------------------------------

def _handmade(songs: dict) -> dict:
    """手工构造一份最小别名表（不走文件加载），用于验证解析优先级。"""
    index, song_index = {}, {}
    for key, item in songs.items():
        song_no = key.partition("|")[0]
        for value in list(item.get("names") or []) + list(item.get("aliases") or []):
            norm = sa.normalize(value)
            if norm:
                index.setdefault(norm, []).append(key)
                song_index.setdefault(song_no, []).append(value)
    return {"songs": songs, "index": index, "song_index": song_index, "ambiguous": {}}


def test_resolve_prefers_exact_then_prefix_then_contains():
    data = _handmade({
        "1|4": {"names": ["北埼玉2000"], "aliases": []},
        "2|4": {"names": ["北埼玉00"], "aliases": []},
        "3|4": {"names": ["みんなの北埼玉"], "aliases": []},
    })
    hits = sa.resolve(data, "北埼玉")
    assert [hit["song_no"] for hit in hits] == [1, 2, 3]
    assert [hit["quality"] for hit in hits] == ["prefix", "prefix", "contains"]
    # 完整写法优先命中完全相等的条目
    assert sa.resolve(data, "北埼玉2000")[0]["quality"] == "exact"
    assert sa.resolve(data, "北埼玉2000")[0]["song_no"] == 1


def test_resolve_prefers_requested_level():
    data = _handmade({
        "5|4": {"names": ["同名曲"], "aliases": []},
        "5|5": {"names": ["同名曲"], "aliases": []},
    })
    assert sa.resolve(data, "同名曲", level=5)[0]["level"] == 5
    assert sa.resolve(data, "同名曲", level=4)[0]["level"] == 4


def test_resolve_returns_empty_for_blank_or_unknown():
    data = sa.load_aliases(RESOURCE)
    assert sa.resolve(data, "") == []
    assert sa.resolve(data, "这个曲名一定不存在zzz") == []


def test_match_names_is_exact_only():
    data = sa.load_aliases(RESOURCE)
    # 「北埼玉」是构建时从「北埼玉2000」派生的写法，200 系列两首都会命中
    assert sa.match_names(data, "北埼玉") == {252, 338}
    assert sa.match_names(data, "北埼玉2000") == {338}
    assert 338 not in sa.match_names(data, "埼玉")


def test_build_alias_index_merges_user_aliases():
    data = sa.load_aliases(RESOURCE)
    index = sa.build_alias_index(data, {"我的爱称": 1, "きたさいたま": 338})
    assert 338 in index and "きたさいたま" in index[338]
    assert index[1][-1] == "我的爱称"


# ---------------------------------------------------------------------------
# 内置资源
# ---------------------------------------------------------------------------

def test_bundled_alias_resource_covers_every_chart():
    charts = {}
    with gzip.open(PLUGIN_DIR / "resource" / "charts.v1.json.gz", "rb") as handle:
        for chart in json.loads(handle.read().decode("utf-8")):
            charts[(chart["id"], chart["level"])] = chart
    data = sa.load_aliases(RESOURCE, charts)
    assert len(data["songs"]) == len(charts)
    # 每张谱面都要有国服曲名；日文名与国服名相同的曲目（英文曲名）除外
    assert all(item["names"] for item in data["songs"].values())
    assert all(f"{song_no}|{level}" in data["songs"] for song_no, level in charts)
    # 平均每张谱面至少 2 种写法（国服名/日文名/罗马字/派生写法）
    assert len(data["index"]) > len(charts)


@pytest.mark.parametrize("query,song_no", [
    ("きたさいたま2000", 338),
    ("Tenjiku 2000", 1),
    ("てんぢく2000", 1),
    ("六天", 765),
    ("第六天魔王", 765),
    ("罗特", 402),
    ("Rotter Tarmination", 402),
    ("顿卡马", 120),
    ("ドンカマ2000", 120),
    ("幽玄", 463),
    ("无畏", 845),
    ("Dreadnought", 845),
    ("わら得る2000", 890),
    ("reendofadream", 1197),
])
def test_bundled_alias_resource_resolves_known_names(query, song_no):
    data = sa.load_aliases(RESOURCE)
    hits = sa.resolve(data, query, limit=5)
    assert hits, f"{query} 没有解析出任何曲目"
    assert song_no in [hit["song_no"] for hit in hits], f"{query} 没有命中 {song_no}：{hits}"


def test_bundled_alias_resource_resolves_short_names_to_the_series():
    """简称是前缀匹配：北埼玉 系列（北埼玉200 / 北埼玉2000）都要能被找到。"""
    data = sa.load_aliases(RESOURCE)
    hits = sa.resolve(data, "北埼玉", limit=5)
    assert {338} <= {hit["song_no"] for hit in hits}
    assert sa.resolve(data, "北埼玉2000")[0]["song_no"] == 338


def test_theoretical_alias_for_dan_only_song_still_works():
    """段位资料用的是日文写法，玩家按国服名提问也要能命中。"""
    data = sa.load_aliases(RESOURCE)
    names = sa.names_of(data, 615, 4)
    assert any("天狗" in name for name in names)
