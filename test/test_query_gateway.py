"""Composite read queries: real services, snapshot isolation and transport limits."""

import asyncio
import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mock_astrbot as mock

mock.install()
from test_ai_coach import material
from test_chart_library import build_fixture

import main
import query_gateway as gateway
from chart_library import ChartLibrary
from service import MemoryBindingsStore, ScoreService
from source_service import MultiSourceService
from storage import ScoreDatabase, load_dan_courses


def make_service():
    analysis, charts = material()
    for row in analysis["records"]:
        row["updatedAt"] = "2099-01-01 00:00:00"
        row["genre"] = "J-POP"
    service = ScoreService(MemoryBindingsStore(), lambda _: None, charts)
    calls = []

    async def load(qq):
        calls.append(qq)
        return analysis, ""

    service._load_analysis = load
    return service, calls


def make_plugin(service):
    plugin = object.__new__(main.RTLinkPlugin)
    plugin.service = service
    plugin.dan_courses = load_dan_courses(
        Path(__file__).resolve().parents[1] / "resource/dan_courses.v1.json.gz"
    )
    return plugin


def event():
    return mock.AstrMessageEvent("qq", True, False, "")


def query(tool, **args):
    return {"tool": tool, "args": args}


def test_stats_and_multi_song_comparison_use_one_analysis_and_one_tool_call():
    async def run():
        service, loads = make_service()
        plugin, ev = make_plugin(service), event()
        requests = [
            query("get_player_overview"),
            query("get_player_rating"),
            query("get_player_profile"),
            query("get_rhythm_weakness"),
            query("get_difficulty_stats", level="鬼"),
            query("get_rank_distribution"),
            query("get_genre_strength"),
            query("get_accuracy_summary"),
            query("query_taiko_score", song_name="歌曲1"),
            query("query_song_brief", song_name="歌曲2"),
            query("get_song_full", song_name="歌曲3"),
            query("get_recent_scores", days=7),
            query("get_improvement_candidates"),
            query("find_rank_improvements", target_rank="金雅"),
            query("recommend_practice", goal="accuracy"),
            query("get_source_status"),
        ]
        result = json.loads(await plugin.query_rtlink(ev, requests))
        assert len(result["results"]) == len(requests)
        assert all(row["status"] == "completed" for row in result["results"]), result
        assert loads == ["qq"]
        assert ev._rtlink_ai_state["calls"] == 1
        assert result["snapshot"]["server"] == "cn"
        assert "评价等级分布" in result["results"][5]["data"]
        assert "J-POP" in result["results"][6]["data"]
        assert "歌曲1" in result["results"][8]["data"]
        assert "歌曲2" in result["results"][9]["data"]
        assert "歌曲3" in result["results"][10]["data"]
        assert gateway.ANALYSIS_SCOPE.get() is None
        # Another batch has a fresh scope; it can reuse normal service TTL caching.
        await plugin.query_rtlink(ev, [query("get_accuracy_summary", level="里")])
        assert loads == ["qq", "qq"]
        assert "预算已用完" in await plugin.get_player_overview(ev)

    asyncio.run(run())


def test_composite_search_preserves_zero_filters_scope_and_rank_routes():
    async def run():
        service, loads = make_service()
        result = await service.get_readonly_queries_text(
            "qq",
            [
                query("search_scores", ng_max=0),
                query(
                    "search_scores", ng_min=1, level="4,5", sort="accuracy", order="asc"
                ),
                query("search_scores", scope="unplayed", song_no=9),
                query("search_scores", scope="unrated", song_no=10),
                query(
                    "search_scores", target_rank="金雅", gap_max=20000, detail="full"
                ),
            ],
            {},
        )
        rows = result["results"]
        assert all(row["status"] == "completed" for row in rows), result
        assert "命中 0 条" in rows[0]["data"]
        assert "命中 8 条" in rows[1]["data"]
        assert "命中 0 条" in rows[2]["data"]  # raw played row 9 is excluded
        assert "有成绩但未参与评级" in rows[3]["data"]
        assert "门槛" in rows[4]["data"] and "良" in rows[4]["data"]
        assert loads == ["qq"]

    asyncio.run(run())


def test_public_dan_and_detailed_chart_queries_work_without_binding(
    tmp_path, monkeypatch
):
    library_root, *_ = build_fixture(tmp_path, monkeypatch)
    service = ScoreService(
        MemoryBindingsStore(),
        lambda _: pytest.fail("must not fetch player data"),
        {},
        chart_library=ChartLibrary(library_root),
    )

    async def forbidden(_qq):
        pytest.fail("public queries must not load player analysis")

    service._load_analysis = forbidden
    plugin = make_plugin(service)
    result = json.loads(
        asyncio.run(
            plugin.query_rtlink(
                event(),
                [
                    query("query_dan_course", song_no=765),
                    query(
                        "get_chart_analysis",
                        song_name="Sample",
                        level="鬼",
                        detail="segments",
                        start_measure=2,
                        end_measure=3,
                        limit=20,
                    ),
                    query("get_chart_analysis", song_name="Sample", detail="features"),
                    query("get_library_status"),
                ],
            )
        )
    )
    assert "2024 中国大陆版 达人 第3曲" in result["results"][0]["data"]
    chart = result["results"][1]["data"]
    assert chart["status"] == "ok" and chart["total"] == 2
    assert [row["measure"] for row in chart["segments"]] == [2, 3]
    assert chart["nextOffset"] is None and chart["limitations"]
    assert result["results"][2]["data"]["features"] == {"test_feature": 2}
    assert result["snapshot"] is None


def test_growth_and_dan_capability_are_available_in_same_batch(tmp_path):
    async def run():
        service, _ = make_service()
        plugin = make_plugin(service)
        db = ScoreDatabase(tmp_path / "player.db")
        service.db = db
        service.store = MemoryBindingsStore(
            {
                "qq": {"apikey": "synthetic", "player_id": "game1", "server": "cn"},
            }
        )
        try:
            for i, score in enumerate((800000, 900000)):
                db.replace_scores(
                    "qq",
                    "kinoko",
                    [
                        {
                            "id": 1,
                            "level": 4,
                            "high_score": score,
                            "good_cnt": 960 + i,
                            "ok_cnt": 30,
                            "ng_cnt": 5,
                            "update_datetime": f"2026-10-2{5 + i} 12:00:00",
                            "raw": {"good_cnt": 960 + i, "ok_cnt": 30, "ng_cnt": 5},
                        }
                    ],
                )
            course = plugin.dan_courses["by_key"][(2023, "cn", "五级")]
            db.replace_scores(
                "qq",
                "hiroba",
                [
                    {
                        "id": song["song_no"],
                        "level": song["level"],
                        "good_cnt": song["total_notes"],
                        "ok_cnt": 0,
                        "ng_cnt": 0,
                        "pound_cnt": 100,
                        "high_score": 900000,
                        "best_score_rank": 4,
                        "raw": {},
                    }
                    for song in course["songs"]
                ],
                game_player_id="game1",
                server="cn",
            )
            db.kv_set(
                "score_storage_schema:qq",
                {"schema": 2, "playerId": "game1", "server": "cn"},
            )
            result = await service.get_readonly_queries_text(
                "qq",
                [
                    query("get_growth_trend", song_name="歌曲1"),
                    query("evaluate_player_dan", year=2023, rank="五级"),
                ],
                plugin.dan_courses,
            )
            assert "800000" in result["results"][0]["data"]
            assert "900000" in result["results"][0]["data"]
            assert "2023 中国大陆版 五级" in result["results"][1]["data"]
            assert (
                "各曲最佳记录满足目前可计算的金合格条件" in result["results"][1]["data"]
            )
        finally:
            db.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "bad",
    [
        query("set_song_alias", song="1", alias="X"),
        query("generate_rating_image"),
        query("bind", apikey="secret"),
        query("__getattribute__", name="store"),
        query("search_scores", qq="other-player"),
        query("query_song_brief"),
        query("get_recent_scores", days=True),
        query("get_recent_scores", days=-1),
        query("search_scores", limit=201),
        query("search_scores", level="typo"),
        query("search_scores", scope="typo"),
        query("find_rank_improvements", target_rank="typo"),
        query("get_chart_analysis", song_name="X", limit=21),
        query("evaluate_player_dan", year=0, rank="十段"),
        {"tool": "get_player_rating", "args": []},
        1,
    ],
)
def test_bad_item_does_not_abort_batch_or_execute_unrequested_work(bad):
    service, loads = make_service()
    result = asyncio.run(
        service.get_readonly_queries_text(
            "qq",
            [bad, query("get_rank_distribution")],
            {},
        )
    )
    assert result["results"][0]["status"] == "invalid_argument"
    assert result["results"][1]["status"] == "completed"
    assert loads == ["qq"]
    assert "secret" not in gateway.dumps(result)


@pytest.mark.parametrize(
    "bad",
    [
        [],
        {},
        [query("get_player_rating")] * 25,
        [query("search_scores", query="x" * 17000)],
        [query("search_scores", constant_min=float("nan"))],
    ],
)
def test_invalid_envelope_does_not_consume_tool_budget(bad):
    service, loads = make_service()
    ev = event()
    result = json.loads(asyncio.run(make_plugin(service).query_rtlink(ev, bad)))
    assert result["status"] == "invalid_argument"
    assert not hasattr(ev, "_rtlink_ai_state") and not loads


def test_backend_error_is_isolated_sanitized_and_batch_deduplicates():
    async def run():
        service, loads = make_service()

        async def failed(_qq):
            raise ValueError("secret-api-key")

        service.get_rating_text = failed
        result = await service.get_readonly_queries_text(
            "qq",
            [
                query("get_player_rating"),
                query("get_rank_distribution"),
                query("get_rank_distribution"),
            ],
            {},
        )
        assert result["results"][0]["status"] == "error"
        assert "secret-api-key" not in gateway.dumps(result)
        assert result["results"][2] == {
            "index": 3,
            "tool": "get_rank_distribution",
            "args": {},
            "status": "reused",
            "same_as": 2,
        }
        assert loads == ["qq"]

    asyncio.run(run())


def test_no_recent_updates_does_not_return_old_best_scores():
    async def run():
        service, _ = make_service()
        load = service._load_analysis

        async def old_analysis(qq):
            analysis, error = await load(qq)
            for row in analysis["records"]:
                row["updatedAt"] = "2000-01-01 00:00:00"
            return analysis, error

        service._load_analysis = old_analysis
        result = await service.get_readonly_queries_text(
            "qq", [query("get_recent_scores", days=7)], {}
        )
        assert "最近 7 天没有更新" in result["results"][0]["data"]
        assert "歌曲1" not in result["results"][0]["data"]

    asyncio.run(run())


def test_failed_sync_is_attempted_once_per_batch():
    async def run():
        service, calls = make_service()

        async def unavailable(qq):
            calls.append(qq)
            return None, "当前数据源同步失败"

        service._load_analysis = unavailable
        result = await service.get_readonly_queries_text(
            "qq",
            [
                query("get_player_rating"),
                query("get_accuracy_summary"),
                query("query_dan_course", song_no=765),
            ],
            make_plugin(service).dan_courses,
        )
        assert calls == ["qq"]
        assert "同步失败" in result["results"][0]["data"]
        assert "同步失败" in result["results"][1]["data"]
        assert "达人" in result["results"][2]["data"]

    asyncio.run(run())


def test_source_cannot_change_mid_batch_and_locks_release_after_failure():
    async def run():
        old, old_calls = make_service()
        new, new_calls = make_service()
        new.provider_label = "Sakura"
        new.store = MemoryBindingsStore({"qq": {"player_id": "p", "server": "cn"}})
        router = MultiSourceService(
            {"kinoko": old, "sakura": new}, MemoryBindingsStore()
        )
        started, release = asyncio.Event(), asyncio.Event()
        load = old._load_analysis

        async def delayed(qq):
            started.set()
            await release.wait()
            return await load(qq)

        old._load_analysis = delayed
        requests = [query("get_player_rating"), query("get_rank_distribution")]
        task = asyncio.create_task(router.get_readonly_queries_text("qq", requests, {}))
        await started.wait()
        switch = asyncio.create_task(router.source_text("qq", "sakura"))
        await asyncio.sleep(0)
        assert not switch.done()
        release.set()
        result = await task
        await switch
        assert result["source"] == "菌菌" and old_calls == ["qq"] and not new_calls
        result = await router.get_readonly_queries_text("qq", requests, {})
        assert result["source"] == "Sakura" and new_calls == ["qq"]

    asyncio.run(run())


def test_concurrent_players_have_separate_analysis_scopes():
    async def run():
        service, _ = make_service()

        async def load(qq):
            await asyncio.sleep(0)
            analysis, _ = material()
            analysis["summary"]["rating"] = 11 if qq == "A" else 22
            return analysis, ""

        service._load_analysis = load
        a, b = await asyncio.gather(
            *[
                service.get_readonly_queries_text(qq, [query("get_player_rating")], {})
                for qq in ("A", "B")
            ]
        )
        assert "Rating 11" in a["results"][0]["data"]
        assert "Rating 22" in b["results"][0]["data"]
        assert gateway.ANALYSIS_SCOPE.get() is None

    asyncio.run(run())


@pytest.mark.parametrize("send_fails", [False, True])
@pytest.mark.parametrize("large", [False, True])
def test_large_results_export_full_data_and_preserve_each_query_in_preview(
    tmp_path, monkeypatch, send_fails, large
):
    module = types.ModuleType("astrbot.api.message_components")

    class File:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    module.File = File
    monkeypatch.setitem(sys.modules, "astrbot.api.message_components", module)

    async def run():
        service, _ = make_service()
        content = ('详细资料\\"\n' * (10000 if large else 1)) + "结束标记"

        async def long_result(_qq):
            return content

        service.get_rating_text = long_result
        plugin, ev = make_plugin(service), event()
        plugin.data_dir = tmp_path
        sent = []
        ev.chain_result = lambda components: components

        async def send(components):
            if send_fails:
                raise RuntimeError("synthetic secret")
            sent.extend(components)

        ev.send = send
        text = await plugin.query_rtlink(
            ev,
            [
                query("get_player_rating"),
                query("get_rank_distribution"),
            ],
            export=not large,
        )
        result = json.loads(text)
        assert len(text) <= gateway.MAX_OUTPUT_CHARS and result["complete"] is not large
        assert len(result["results"]) == 2
        assert "评价等级分布" in result["results"][1]["data"]
        assert "结束标记" in result["results"][0]["preview" if large else "data"]
        assert result["attachment"]["status"] == ("failed" if send_fails else "sent")
        assert "synthetic secret" not in text
        files = list((tmp_path / "query_exports").glob("*.json"))
        assert len(files) == 1
        exported = json.loads(files[0].read_text(encoding="utf-8"))
        assert exported["results"][0]["data"] == content
        assert len(sent) == (0 if send_fails else 1)
        assert ev._rtlink_ai_state["calls"] == 1

    asyncio.run(run())
