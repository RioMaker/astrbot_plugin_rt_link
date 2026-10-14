"""Offline public reference tests, with small explicit TJA fixtures."""

import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from chart_library import ChartLibrary
from scripts import build_chart_library as builder
from scripts.chart_metrics import peak_density, summarize_route
from scripts.tja_timeline import parse_timelines
from service import MemoryBindingsStore, ScoreService


def tja(tmp_path, body, header=""):
    path = tmp_path / "sample.tja"
    path.write_text(
        "TITLE:Sample\nBPM:120\nOFFSET:-2\nCOURSE:Oni\nLEVEL:5\n"
        + header
        + "\n#START\n"
        + body
        + "\n#END\n",
        encoding="utf-8",
    )
    return path


def test_timing_mid_measure_bpm_delay_and_rest(tmp_path):
    path = tja(tmp_path, "10\n#BPMCHANGE 240\n10,\n#DELAY 1\n0000,\n#MEASURE 3/4\n111,")
    parsed = parse_timelines(path)[0]
    timeline = parsed["routes"]["single"]
    assert parsed["offset"] == -2
    assert [t["time"] for t in timeline["taps"]] == pytest.approx([0, 1, 3.5, 3.75, 4])
    result = summarize_route(timeline)
    assert result["summary"]["notes"] == 5
    assert result["summary"]["durationSeconds"] == 4.25
    assert result["measures"][1]["notes"] == 0
    assert result["measures"][1]["notesPerSecond"] == 0
    assert result["measures"][1]["minGapSeconds"] is None


def test_branches_are_separate_and_missing_route_is_warned(tmp_path):
    path = tja(
        tmp_path, "#BRANCHSTART p,50,90\n#N\n1000,\n#E\n1100,\n#M\n1111,\n#BRANCHEND"
    )
    routes = parse_timelines(path)[0]["routes"]
    assert {k: len(v["taps"]) for k, v in routes.items()} == {"N": 1, "E": 2, "M": 4}
    path = tja(tmp_path, "#BRANCHSTART p,50,90\n#M\n1111,\n#BRANCHEND")
    routes = parse_timelines(path)[0]["routes"]
    assert "branch-fallback-m" in routes["N"]["warnings"]


def test_roll_balloon_and_unsupported_visual_command(tmp_path):
    path = tja(tmp_path, "1000,\n5008,\n7008,\n#SUDDEN 1 1\n1000,", "BALLOON:10")
    result = summarize_route(parse_timelines(path)[0]["routes"]["single"])
    assert result["summary"]["notes"] == 2
    assert result["summary"]["yellowRollSeconds"] == 1.5
    assert result["summary"]["balloons"] == [
        {"start": 4, "end": 5.5, "requiredHits": 10}
    ]
    assert "unsupported-sudden" in result["warnings"]


def test_duplicate_course_blocks_are_not_overwritten(tmp_path):
    path = tja(tmp_path, "1000,")
    with path.open("a", encoding="utf-8") as f:
        f.write("COURSE:Oni\nLEVEL:1\n#START\n1100,\n#END\n")
    parsed = parse_timelines(path)
    assert [r["courseOccurrence"] for r in parsed] == [1, 2]
    assert [len(r["routes"]["single"]["taps"]) for r in parsed] == [1, 2]


def test_negative_delay_is_not_presented_as_reliable_time(tmp_path):
    result = summarize_route(
        parse_timelines(tja(tmp_path, "1111,\n#DELAY -1\n1111,"))[0]["routes"]["single"]
    )
    assert result["timeReliable"] is False
    assert result["summary"]["notes"] == 8
    assert result["summary"]["notesPerSecond"] is None
    assert result["measures"][0]["startSeconds"] is None
    assert all(not values for values in result["hotspots"].values())


def test_density_uses_half_open_windows():
    assert peak_density([0, 0.5, 1, 1.5, 2], 2) == 2


def test_direction_rest_and_delay_metrics(tmp_path):
    result = summarize_route(
        parse_timelines(
            tja(tmp_path, "#SCROLL -1\n1111,\n#SCROLL 0\n0000,\n#DELAY 1\n1000,")
        )[0]["routes"]["single"]
    )
    assert result["summary"]["reverseSeconds"] == 2
    assert result["summary"]["delaySeconds"] == 1
    assert result["measures"][1]["maxTapFreeSeconds"] == 2
    assert result["measures"][1]["preceding10sNotes"] == 4
    assert result["hotspots"]["colorSwitches"] == []


def build_fixture(tmp_path, monkeypatch):
    ese = tmp_path / "ese"
    ese.mkdir()
    path = tja(ese, "1212,\n1111,\n0000,")
    row = {
        "relativePath": path.name,
        "course": "oni",
        "fingerprint": "test-fingerprint",
        "title": "Sample",
        "titleJa": "样本曲",
        "level": 5,
        "totalNotes": 8,
        "features": {"test_feature": 2},
        "rhythmProfile": {},
        "warnings": [],
    }
    index, mapping = tmp_path / "index.json", tmp_path / "mapping.json"
    index.write_text(
        json.dumps(
            {
                "eseRevision": "fixture-revision",
                "parserId": "v5",
                "charts": [row],
                "errors": [],
            }
        ),
        encoding="utf-8",
    )
    mapping.write_text(
        json.dumps({"eseRevision": "fixture-revision", "mappings": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        builder.subprocess,
        "check_output",
        lambda args, **kwargs: "fixture-revision" if "rev-parse" in args else "",
    )
    root = tmp_path / "library"
    manifest = builder.build(ese, index, mapping, root)
    return root, manifest, ese, index, mapping


def test_builder_query_pagination_incremental_and_backup(tmp_path, monkeypatch):
    root, manifest, ese, index, mapping = build_fixture(tmp_path, monkeypatch)
    library = ChartLibrary(root)
    summary = library.query("样本曲", 4)
    assert summary["status"] == "ok"
    assert summary["summary"]["notes"] == 8
    assert summary["mapping"].startswith("ESE-only")
    result = library.query(
        summary["chartKey"], detail="segments", start_measure=2, limit=1
    )
    assert result["total"] == 2 and result["nextOffset"] == 1
    assert result["segments"][0]["measure"] == 2
    second = library.query(
        "Sample", detail="segments", start_measure=2, offset=1, limit=1
    )
    assert second["segments"][0]["notes"] == 0 and second["nextOffset"] is None
    assert library.query("Sample", detail="features")["features"] == {"test_feature": 2}
    rebuilt = builder.build(ese, index, mapping, root)
    assert rebuilt["reused"] == 1 and rebuilt["built"] == 0
    assert (root / "versions" / manifest["buildId"] / "tja.zip").exists()
    assert library.query("Sample")["buildId"] == rebuilt["buildId"]
    assert len(library._cache) == 1
    # Changed source invalidates reuse; a note mismatch leaves current intact.
    (ese / "sample.tja").write_text(
        "TITLE:Sample\nBPM:120\nCOURSE:Oni\n#START\n1,\n#END", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="note count mismatch"):
        builder.build(ese, index, mapping, root)
    assert (
        json.loads((root / "current.json").read_bytes())["buildId"]
        == rebuilt["buildId"]
    )
    assert library.query("Sample")["summary"]["notes"] == 8


def test_query_validation_missing_corrupt_and_version_mismatch(tmp_path, monkeypatch):
    root, manifest, *_ = build_fixture(tmp_path, monkeypatch)
    assert ChartLibrary(tmp_path / "missing").query("Sample")["status"] == "unavailable"
    library = ChartLibrary(root)
    for params in (
        {"level": 3},
        {"limit": 100},
        {"offset": -1},
        {"start_measure": 2, "end_measure": 1},
        {"limit": 2.5},
        {"route": "unknown"},
    ):
        assert library.query("Sample", **params)["status"] == "unavailable"
    assert library.query("../../")["status"] == "unavailable"
    assert library.query("9" * 100)["status"] == "unavailable"
    assert library.query("does not exist")["status"] == "not_found"
    assert (
        ChartLibrary(root, "mismatched-hash").query("Sample")["status"] == "unavailable"
    )
    pointer = root / "current.json"
    pointer.write_text('{"buildId":"../../outside"}')
    assert library.query("Sample")["status"] == "unavailable"
    pointer.write_text(json.dumps({"buildId": manifest["buildId"]}))
    db = root / "versions" / manifest["buildId"] / "analysis.sqlite3"
    content = bytearray(db.read_bytes())
    content[-10] ^= 1
    db.write_bytes(content)
    assert "校验失败" in ChartLibrary(root).query("Sample")["message"]


def test_multiple_difficulties_and_unmapped_variants_remain_explicit(
    tmp_path, monkeypatch
):
    root, _, ese, index, mapping = build_fixture(tmp_path, monkeypatch)
    path = ese / "sample.tja"
    with path.open("a", encoding="utf-8") as f:
        f.write("COURSE:Edit\nLEVEL:9\n#START\n1111,\n#END\n")
    data = json.loads(index.read_text("utf-8"))
    data["charts"].append(
        {
            **data["charts"][0],
            "course": "edit",
            "totalNotes": 4,
            "fingerprint": "edit-fingerprint",
        }
    )
    index.write_text(json.dumps(data), encoding="utf-8")
    # Oni has an official binding while Edit is only an ESE entry. Omitting
    # difficulty must still return both, rather than silently choose Oni.
    monkeypatch.setattr(
        builder, "load_charts", lambda _: {(1, 4): {"title": "Sample", "totalNotes": 8}}
    )
    monkeypatch.setattr(builder, "load_aliases", lambda *args: {"songs": {}})
    mapping.write_text(
        json.dumps(
            {
                "eseRevision": "fixture-revision",
                "mappings": [
                    {
                        "songNo": 1,
                        "level": 4,
                        "status": "matched",
                        "selected": {
                            "relativePath": path.name,
                            "course": "oni",
                            "fingerprint": "test-fingerprint",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    builder.build(ese, index, mapping, root)
    library = ChartLibrary(root)
    ambiguous = library.query("Sample")
    assert ambiguous["status"] == "ambiguous"
    assert {c["level"] for c in ambiguous["candidates"]} == {4, 5}
    assert library.query("Sample", 5)["summary"]["notes"] == 4
    assert library.query("1", 4)["mapping"] == "verified"
    assert library.query("1", 5)["status"] == "not_found"


def test_branch_queries_and_whole_chart_feature_scope(tmp_path, monkeypatch):
    root, _, ese, index, mapping = build_fixture(tmp_path, monkeypatch)
    tja(
        ese,
        "#BRANCHSTART p,50,90\n#N\n10000000,\n#E\n11000000,\n#M\n11111111,\n#BRANCHEND",
    )
    builder.build(ese, index, mapping, root)
    library = ChartLibrary(root)
    assert library.query("Sample")["route"] == "M"
    assert library.query("Sample", route="N")["summary"]["notes"] == 1
    assert library.query("Sample", route="E")["summary"]["notes"] == 2
    assert (
        library.query("Sample", route="N", detail="features")["status"] == "unavailable"
    )
    assert library.query("Sample", route="single")["status"] == "invalid_route"


def test_service_public_lookup_never_syncs_or_needs_binding(tmp_path, monkeypatch):
    root, *_ = build_fixture(tmp_path, monkeypatch)

    def forbidden(*args, **kwargs):
        pytest.fail("public chart lookup attempted player/API access")

    service = ScoreService(
        MemoryBindingsStore(), forbidden, chart_library=ChartLibrary(root)
    )
    monkeypatch.setattr(service, "_get_analysis", forbidden)
    result = json.loads(asyncio.run(service.get_chart_analysis_text("鬼 Sample")))
    assert result["status"] == "ok" and result["level"] == 4
    assert (
        json.loads(
            asyncio.run(service.get_chart_analysis_text("鬼 Sample", level="里"))
        )["status"]
        == "invalid_argument"
    )


def test_tool_forwards_all_public_query_arguments():
    import mock_astrbot

    mock_astrbot.install()
    import main

    class Service:
        async def get_chart_analysis_text(self, song, **kwargs):
            return json.dumps({"song": song, **kwargs})

    plugin = main.RTLinkPlugin.__new__(main.RTLinkPlugin)
    plugin.service = Service()
    result = json.loads(
        asyncio.run(
            plugin.get_chart_analysis(None, "Sample", "4", "M", "segments", 2, 8, 1, 2)
        )
    )
    assert result == {
        "song": "Sample",
        "level": "4",
        "route": "M",
        "detail": "segments",
        "start_measure": 2,
        "end_measure": 8,
        "offset": 1,
        "limit": 2,
    }
