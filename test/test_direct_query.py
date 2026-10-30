"""Main-AI tools must return player evidence without a second model or image."""

import asyncio
import json
from pathlib import Path

import mock_astrbot as mock
import pytest

mock.install()
from test_sources import setup_services

import main
from storage import load_charts, load_dan_courses


class NoModelContext:
    def __getattr__(self, name):
        pytest.fail(f"Direct data queries must not access model context: {name}")


@pytest.fixture(scope="module")
def charts():
    return load_charts(
        Path(__file__).resolve().parents[1] / "resource/charts.v1.json.gz"
    )


def event(sender="qq"):
    return mock.AstrMessageEvent(sender, True, False, "查看我的成绩")


def plugin(router, tmp_path):
    star = object.__new__(main.RTLinkPlugin)
    star.context = NoModelContext()
    star.service = router
    star.data_dir = tmp_path
    star.dan_courses = load_dan_courses(
        Path(__file__).resolve().parents[1] / "resource/dan_courses.v1.json.gz"
    )
    # Broken or leftover sub-agent settings must not block ordinary player data.
    star.cfg = {
        "query_agent_output_mode": "image",
        "query_agent_context_tokens": 1,
        "query_agent_custom_tools": "obsolete-invalid-value",
    }
    return star


def close(router):
    for service in router.services.values():
        service.db.close()


@pytest.mark.parametrize(
    "source,expected_score", [("kinoko", 900000), ("sakura", 1000000)]
)
def test_registered_tools_return_synced_scores_from_selected_source(
    tmp_path, charts, source, expected_score
):
    async def run():
        router, kinoko, sakura = setup_services(tmp_path, charts)
        try:
            if source == "sakura":
                assert (await router.bind_sakura("qq", "x" * 48))[0]
            star = plugin(router, tmp_path)
            song = kinoko.data["data"]["songs"][0]
            text = await star.query_rtlink(
                event(),
                [
                    {"tool": "get_source_status"},
                    {"tool": "get_player_rating"},
                    {"tool": "get_rank_distribution"},
                    {
                        "tool": "query_song_brief",
                        "args": {"song_name": str(song["song_no"]), "level": "4"},
                    },
                    {
                        "tool": "search_scores",
                        "args": {"song_no": song["song_no"], "detail": "full"},
                    },
                ],
            )
            result = json.loads(text)
            assert result["source"] == ("菌菌" if source == "kinoko" else "Sakura")
            assert result["complete"] and result["snapshot"]["server"] == "cn"
            assert all(row["status"] == "completed" for row in result["results"])
            assert result["results"][0]["data"]["bound"] is True
            assert "Rating" in result["results"][1]["data"]
            assert "评价等级分布" in result["results"][2]["data"]
            assert str(expected_score) in result["results"][3]["data"]
            assert str(expected_score) in result["results"][4]["data"]
            assert "良" in result["results"][4]["data"]
            assert "delivery" not in result and "summary" not in result
            assert "tk_test" not in text and "x" * 48 not in text
            assert not (tmp_path / "query_results").exists()
            assert not (tmp_path / "query_exports").exists()
            calls = (kinoko.calls, sakura.calls)
            # Direct shortcuts must also return data and reuse the same TTL cache.
            assert "Rating" in await star.get_player_overview(event())
            assert str(expected_score) in await star.query_song_brief(
                event(), str(song["song_no"]), "4"
            )
            assert (kinoko.calls, sakura.calls) == calls
            assert (sakura.calls if source == "kinoko" else kinoko.calls) == 0
        finally:
            close(router)

    asyncio.run(run())


def test_public_catalog_and_personal_dan_judgements_are_distinct(tmp_path, charts):
    async def run():
        router, client, _ = setup_services(tmp_path, charts)
        try:
            star = plugin(router, tmp_path)
            course = star.dan_courses["by_key"][(2025, "cn", "十段")]
            for index, song in enumerate(course["songs"]):
                client.data["data"]["songs"].append(
                    {
                        "song_no": song["song_no"],
                        "level": song["level"],
                        "good_cnt": song["total_notes"] - 3,
                        "ok_cnt": 2,
                        "ng_cnt": 1,
                        "pound_cnt": 40 + index,
                        "combo_cnt": 100,
                        "high_score": 900001 + index,
                        "best_score_rank": 5,
                        "update_datetime": "2026-10-30 12:00:00",
                    }
                )
            ev = event()
            public = await star.query_dan_course(
                ev, year=2025, region="cn", rank="十段"
            )
            assert "公共课题曲" in public and "本次未查询个人成绩" in public
            assert "不能据此判断玩家成绩未同步" in public
            assert client.calls == 0
            personal = await star.evaluate_player_dan(
                ev, year=2025, region="cn", rank="十段"
            )
            assert client.calls > 0
            assert "玩家段位能力参考" in personal
            for index, song in enumerate(course["songs"]):
                assert (
                    f"良 {song['total_notes'] - 3} / 可 2 / 不可 1 / 连打 {40 + index}"
                    in personal
                )
                assert str(900001 + index) in personal
            assert "不能据此断言已经过段" in personal
            # The composite path must return the same evidence to the main AI.
            result = json.loads(
                await star.query_rtlink(
                    event(),
                    [
                        {
                            "tool": "query_dan_course",
                            "args": {"year": 2025, "region": "cn", "rank": "十段"},
                        },
                        {
                            "tool": "evaluate_player_dan",
                            "args": {"year": 2025, "region": "cn", "rank": "十段"},
                        },
                    ],
                )
            )
            assert result["results"][0]["data"] == public
            assert result["results"][1]["data"] == personal
        finally:
            close(router)

    asyncio.run(run())


@pytest.mark.parametrize("unbound", [True, False])
def test_missing_binding_and_sync_failure_do_not_look_like_public_catalog_gaps(
    tmp_path, charts, unbound
):
    async def run():
        router, client, _ = setup_services(tmp_path, charts)
        try:
            if unbound:
                await router.services["kinoko"].store.save({})
            else:
                client.fail = True
            star = plugin(router, tmp_path)
            result = json.loads(
                await star.query_rtlink(
                    event(),
                    [
                        {"tool": "get_source_status"},
                        {"tool": "get_player_rating"},
                        {"tool": "query_dan_course", "args": {"song_no": 765}},
                    ],
                )
            )
            assert result["results"][0]["data"]["bound"] is not unbound
            personal = result["results"][1]["data"]
            assert ("绑定" if unbound else "503") in personal
            assert "没有玩过" not in personal
            assert "2024 中国大陆版 达人 第3曲" in result["results"][2]["data"]
            assert "本次未查询个人成绩" in result["results"][2]["data"]
        finally:
            close(router)

    asyncio.run(run())


def test_missing_queries_returns_migration_hint_without_spending_budget():
    star = object.__new__(main.RTLinkPlugin)
    ev = event()
    result = json.loads(asyncio.run(star.query_rtlink(ev)))
    assert result["status"] == "invalid_argument"
    assert "queries" in result["usage"] and "get_player_overview" in result["usage"]
    assert not hasattr(ev, "_rtlink_ai_state")


def test_plugin_config_injection_and_legacy_bindings_survive_rollback(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(main.StarTools, "get_data_dir", lambda _: str(tmp_path))
    config = {"chart_library_auto_install": False, "query_agent_context_tokens": 1}

    async def run():
        star = main.RTLinkPlugin(
            mock.Context({"query_agent_context_tokens": 8192}), config
        )
        try:
            assert star.cfg is config
            legacy = {"qq": {"apikey": "synthetic", "player_id": "old", "server": "cn"}}
            star._kv["bindings"] = legacy
            assert await star.service.services["kinoko"].store.load() == legacy
            assert Path(star.db.db_path) == tmp_path / "rt_link.db"
        finally:
            await star.terminate()

    asyncio.run(run())
