"""Regressions for new Dan identities, wrong aliases and unsafe ID joins."""

import asyncio
import json
from pathlib import Path

import pytest

from dan_query import query_dan_courses_text
from scripts.audit_song_aliases import audit
from scripts.build_dan_courses import _map_songs
from service import MemoryBindingsStore, ScoreService
from song_alias import display_name, load_aliases, match_names, normalize
from storage import load_charts, load_dan_courses

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def data():
    charts = load_charts(ROOT / "resource/charts.v1.json.gz")
    return (
        charts,
        load_aliases(ROOT / "resource/aliases.v1.json.gz"),
        load_dan_courses(ROOT / "resource/dan_courses.v1.json.gz", charts),
    )


@pytest.mark.parametrize(
    "name,sid",
    [
        ("DONKYO Likelihood", 1502),
        ("Donkyou Likelihood", 1502),
        ("鈍響ライクリフド", 1502),
        ("钝响ライクリフド", 1502),
        ("钝响", 1502),
        ("活声Likelihood", 1503),
        ("活声ライクリフド", 1503),
        ("KASSEI Likelihood", 1503),
        ("活声", 1503),
        ("ＫＡＳＳＥＩ　ＬＩＫＥＬＩＨＯＯＤ", 1503),
        ("+♂", 140),
        ("寝ても寝ても", 591),
        ("shime2000", 265),
    ],
)
def test_verified_names_have_the_right_identity(data, name, sid):
    assert match_names(data[1], name) == {sid}


def test_new_dan_is_named_without_inventing_model_features(data):
    charts, aliases, dan = data
    for sid, title, notes in [
        (1502, "DONKYO Likelihood", 1059),
        (1503, "活声Likelihood", 938),
    ]:
        assert (sid, 4) not in charts
        assert display_name(aliases, sid, 4) == title
        assert aliases["songs"][f"{sid}|4"]["metadata"]["rated"] is False
        for region in ("cn", "jp_worldwide"):
            song = next(
                s
                for s in dan["by_key"][(2026, region, "十段")]["songs"]
                if s["song_no"] == sid
            )
            assert song["song_no_candidates"] == [sid]
            assert song["total_notes"] == notes
            assert song["mapping_evidence"] == "title+level+notes"
        text = query_dan_courses_text(
            dan, year=2026, region="cn", song_name=title, alias_data=aliases
        )
        assert title in text and "十段" in text and f"ID {sid}" in text
        assert "当前曲库无此曲" not in text


def test_exact_unplayed_name_never_falls_back_to_a_different_song(data):
    svc = ScoreService(MemoryBindingsStore(), None, charts=data[0], aliases=data[1])
    records = [{"id": 252, "level": 4, "title": "北埼玉200"}]
    assert asyncio.run(svc._resolve_query_to_records(records, "北埼玉2000")) == []
    assert svc._resolve_song("1503")[0]["title"] == "活声Likelihood"
    builtins = asyncio.run(svc._get_alias_map())
    assert "alive" not in builtins


def test_mapping_rejects_same_name_with_wrong_note_count():
    course = {
        "year": 2026,
        "region": "cn",
        "rank": "十段",
        "songs": [{"order": 1, "title": "test", "level": 4, "total_notes": 100}],
    }
    report = _map_songs(
        [course], [{"id": 1, "title": "test", "level": 4, "totalNotes": 101}]
    )
    assert report["unresolved"] == 1
    assert course["songs"][0]["song_no"] is None


def test_every_name_and_collision_is_audited(data):
    report = audit()
    assert report["summary"]["currentCnSongs"] == 1126
    assert len(report["conflicts"]) == report["summary"]["collisionKeys"]
    assert all(c["decision"] for c in report["conflicts"])
    assert len(report["excludedSourceEntries"]) == 143
    assert not any(int(sid) >= 100000 for sid in data[1]["song_index"])
    assert normalize(" ") == ""
    assert "%" not in normalize("+♂")
    payload = json.loads((ROOT / "scripts/data/song_names.json").read_bytes())
    for record in payload["eseSupplementalMappings"]:
        assert record["songNo"] < 100000
        assert record["selected"]["totalNotes"] > 0
