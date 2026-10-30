"""Account isolation, legacy inventory, Dashboard auth and real AI tool routing."""

import asyncio
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import mock_astrbot as mock
import pytest

mock.install()

from test_direct_query import event, plugin
from test_sources import setup_services

import main
from account_admin import AccountAdmin, AdminAPI, AdminError
from account_identity import BOT_OWNER_ID
from api_client import KinokoAPIError
from service import RATING_ALGORITHM_VERSION, RATING_CACHE_SCHEMA, MemoryBindingsStore
from source_service import MultiSourceService
from storage import load_charts


@pytest.fixture(scope="module")
def charts():
    return load_charts(
        Path(__file__).resolve().parents[1] / "resource/charts.v1.json.gz"
    )


@pytest.fixture
def system(tmp_path, charts):
    router, kinoko, sakura = setup_services(tmp_path, charts)
    router.known_store = MemoryBindingsStore()
    yield router, AccountAdmin(router), kinoko, sakura
    for service in router.services.values():
        service.db.close()


def test_inventory_is_local_only_and_includes_unsynced_users(system):
    async def run():
        router, admin, kinoko, sakura = system
        data = await admin.users({})
        assert data["stats"] == {"total": 1, "bound": 1, "unbound": 0}
        row = data["items"][0]
        assert row["owner_id"] == "qq" and row["bound_sources"] == ["kinoko"]
        assert row["rating"] is None and row["last_sync_at"] is None
        assert row["rating_state"] == "needs_sync"
        assert row["sources"][0]["player_id"] == "001234"
        assert kinoko.calls == sakura.calls == 0
        assert await router.current_source("qq") == "kinoko"
        assert "tk_test" not in json.dumps(data)

    asyncio.run(run())


def test_multiple_sources_current_rating_and_readonly_refresh(system):
    async def run():
        router, admin, kinoko, sakura = system
        await router.force_update("qq")
        await router.bind_sakura("qq", "x" * 48)
        await router.force_update("qq")
        calls = kinoko.calls, sakura.calls
        data = await admin.users({})
        assert data["total"] == 1
        row = data["items"][0]
        assert row["bound_sources"] == ["kinoko", "sakura"]
        assert row["current_source"] == "sakura"
        assert (
            row["rating"]
            == router.services["sakura"].db.get_rating_cache("qq")["summary"]["rating"]
        )
        assert all(
            source["last_sync_at"] and source["rating"] is not None
            for source in row["sources"]
        )
        assert "apikey" not in json.dumps(data) and "x" * 48 not in json.dumps(data)
        assert calls == (kinoko.calls, sakura.calls)
        await admin.perform({"owner_id": "qq", "source": "kinoko", "action": "select"})
        row = await admin.account("qq")
        assert (
            row["rating"]
            == router.services["kinoko"].db.get_rating_cache("qq")["summary"]["rating"]
        )
        assert row["current_source"] == "kinoko"

    asyncio.run(run())


def test_bot_binding_is_separate_and_survives_router_restart(system):
    async def run():
        router, admin, _, _ = system
        user_binding = copy.deepcopy(await router.services["kinoko"]._binding("qq"))
        saved = await admin.perform(
            {
                "owner_id": BOT_OWNER_ID,
                "source": "kinoko",
                "action": "bind",
                "token": "tk_bot_synthetic",
                "player_id": "001234",
                "server": "cn",
            }
        )
        assert saved["account"]["is_bot"]
        await admin.perform(
            {
                "owner_id": BOT_OWNER_ID,
                "source": "sakura",
                "action": "bind",
                "token": "b" * 48,
            }
        )
        synced = await admin.perform(
            {"owner_id": BOT_OWNER_ID, "source": "sakura", "action": "sync"}
        )
        assert synced["account"]["rating"] is not None
        assert await router.services["kinoko"]._binding("qq") == user_binding
        assert router.services["sakura"].db.get_rating_cache("qq") is None
        assert (await admin.users({}))["total"] == 1
        assert "tk_bot_synthetic" not in json.dumps(
            synced
        ) and "b" * 48 not in json.dumps(synced)
        restarted = MultiSourceService(
            router.services, router.selection_store, router.known_store
        )
        assert await restarted.current_source(BOT_OWNER_ID) == "sakura"
        assert (await AccountAdmin(restarted).account(BOT_OWNER_ID))[
            "rating"
        ] == synced["account"]["rating"]
        await admin.perform(
            {"owner_id": BOT_OWNER_ID, "source": "kinoko", "action": "unbind"}
        )
        assert await router.services["kinoko"]._binding("qq") == user_binding
        assert await router.current_source(BOT_OWNER_ID) == "sakura"

    asyncio.run(run())


def test_unbound_inventory_includes_legacy_syncs_and_never_synced_bindings(system):
    async def run():
        router, admin, _, _ = system
        await router.bind("never-synced", "tk_test", "001234")
        await router.unbind("never-synced")
        db = router.services["kinoko"].db
        db.replace_scores(
            "legacy",
            "hiroba",
            [],
            game_player_id="legacy-player",
            server="cn",
            fetched_at="2026-10-01T00:00:00+00:00",
        )
        result = await admin.users({"status": "unbound"})
        assert result["stats"] == {"total": 3, "bound": 1, "unbound": 2}
        rows = {row["owner_id"]: row for row in result["items"]}
        assert rows["legacy"]["last_sync_at"] == "2026-10-01T00:00:00+00:00"
        assert rows["legacy"]["sources"][0]["player_id"] == "legacy-player"
        assert rows["never-synced"]["sources"][0]["ever_bound"]
        assert rows["never-synced"]["last_sync_at"] is None
        assert rows["never-synced"]["rating"] is None
        assert "apikey" not in json.dumps(await router.known_store.load())

    asyncio.run(run())


def test_filters_and_pagination_exclude_bot_and_credentials(system):
    async def run():
        router, admin, _, _ = system
        await router.bind_sakura("second", "s" * 48)
        await router.bind_sakura(BOT_OWNER_ID, "b" * 48)
        assert (await admin.users({"source": "sakura"}))["total"] == 1
        assert (await admin.users({"q": "tk_test"}))["total"] == 0
        assert (await admin.users({"q": "001234"}))["total"] == 2
        page = await admin.users({"page_size": 1, "page": 2})
        assert page["total"] == 2 and len(page["items"]) == 1 and page["page"] == 2
        assert (await admin.users({"page": 100}))["page"] == 1
        for query in (
            {"page": "bad"},
            {"page_size": 0},
            {"source": "other"},
            {"status": "other"},
            {"q": "x" * 101},
        ):
            with pytest.raises(AdminError):
                await admin.users(query)

    asyncio.run(run())


@pytest.mark.parametrize("problem", ["identity", "algorithm", "schema", "nan"])
def test_mismatched_or_obsolete_rating_is_never_current(system, problem):
    async def run():
        router, admin, _, _ = system
        cache = {
            "meta": {"playerId": "001234", "server": "cn"},
            "summary": {"rating": 9.12},
            "ratingAlgorithmVersion": RATING_ALGORITHM_VERSION,
            "_cacheSchema": RATING_CACHE_SCHEMA,
            "profileSyncedAt": "2026-10-01T00:00:00+00:00",
        }
        if problem == "identity":
            cache["meta"]["playerId"] = "other"
        elif problem == "algorithm":
            cache["ratingAlgorithmVersion"] = "obsolete"
        elif problem == "schema":
            cache["_cacheSchema"] = -1
        else:
            cache["summary"]["rating"] = float("nan")
        router.services["kinoko"].db.put_rating_cache("qq", cache)
        row = await admin.account("qq")
        assert row["rating"] is None and row["rating_state"] == "needs_sync"
        json.dumps(row, allow_nan=False)

    asyncio.run(run())


def test_failure_retains_sync_date_rating_binding_and_never_echoes_credentials(system):
    async def run():
        router, admin, client, _ = system
        await router.force_update("qq")
        before = await admin.account("qq")

        def fail(*args, **kwargs):
            raise KinokoAPIError("remote echoed tk_test and tk_new_secret")

        client.hiroba = client.kinoko = client.hiroba_recent = fail
        for data in (
            {"owner_id": "qq", "source": "kinoko", "action": "sync"},
            {
                "owner_id": "qq",
                "source": "kinoko",
                "action": "bind",
                "token": "tk_new_secret",
                "player_id": "other",
                "server": "cn",
            },
        ):
            with pytest.raises(AdminError) as error:
                await admin.perform(data)
            assert "tk_" not in str(error.value)
        assert await admin.account("qq") == before
        assert (await router.services["kinoko"]._binding("qq"))["apikey"] == "tk_test"
        assert "tk_test" not in await router.get_rating_text("qq")

    asyncio.run(run())


def test_syncing_noncurrent_source_does_not_switch_current_and_serializes(system):
    async def run():
        router, admin, _, _ = system
        await router.bind_sakura("qq", "s" * 48)
        started, release = asyncio.Event(), asyncio.Event()

        async def sync(owner):
            assert owner == "qq"
            started.set()
            await release.wait()
            return True, "done"

        router.services["kinoko"].force_update = sync
        sync_task = asyncio.create_task(
            admin.perform({"owner_id": "qq", "source": "kinoko", "action": "sync"})
        )
        await started.wait()
        unbind_task = asyncio.create_task(router.unbind("qq"))
        await asyncio.sleep(0)
        assert not unbind_task.done()
        release.set()
        await asyncio.wait_for(asyncio.gather(sync_task, unbind_task), 3)
        assert await router.current_source("qq") == "sakura"
        assert await router.services["kinoko"]._binding("qq")
        assert not await router.services["sakura"]._binding("qq")

    asyncio.run(run())


def test_bot_and_caller_comparison_use_distinct_targets_with_shared_budget(
    system, tmp_path
):
    async def run():
        router, _, _, _ = system
        await router.bind_sakura(BOT_OWNER_ID, "b" * 48)
        star = plugin(router, tmp_path)
        ev = event()
        requests = [{"tool": "search_scores", "args": {"detail": "full"}}]
        caller = json.loads(await star.query_rtlink(ev, requests))
        bot = json.loads(await star.query_rtlink(ev, requests, target="bot"))
        assert (
            caller["subject"]["target"] == "caller"
            and bot["subject"]["name"] == "可可子"
        )
        assert caller["source"] == "菌菌" and bot["source"] == "Sakura"
        assert "900000" in caller["results"][0]["data"]
        assert "1000000" in bot["results"][0]["data"]
        assert ev._rtlink_ai_state["calls"] == 2
        assert "已提供" in await star.query_rtlink(ev, requests, target="bot")
        assert "预算已用完" in await star.get_player_overview(ev, target="bot")
        assert "b" * 48 not in json.dumps(bot)

    asyncio.run(run())


@pytest.mark.parametrize(
    "tool,args",
    [
        ("get_player_overview", []),
        ("query_song_brief", ["1"]),
        ("recommend_practice", []),
        ("evaluate_player_dan", [2025, "十段"]),
    ],
)
def test_shortcuts_support_bot_and_unbound_bot_never_reads_caller(
    system, tmp_path, tool, args
):
    async def run():
        router, _, kinoko, sakura = system
        star = plugin(router, tmp_path)
        result = await getattr(star, tool)(event(), *args, target="bot")
        assert "可可子" in result and "尚未绑定" in result
        assert kinoko.calls == sakura.calls == 0
        await router.bind_sakura(BOT_OWNER_ID, "b" * 48)
        result = await getattr(star, tool)(event(), *args, target="bot")
        assert result.startswith("查询对象：可可子（AI 自己）")
        assert kinoko.calls == 0

    asyncio.run(run())


@pytest.mark.parametrize("target", ["other-qq", "__rtlink_ai__", "", None, [], 123])
def test_llm_cannot_choose_arbitrary_owner(system, tmp_path, target):
    async def run():
        router, _, kinoko, sakura = system
        star = plugin(router, tmp_path)
        ev = event()
        result = json.loads(
            await star.query_rtlink(ev, [{"tool": "get_player_rating"}], target=target)
        )
        assert result["status"] == "invalid_argument"
        assert "仅支持" in await star.get_player_overview(ev, target=target)
        assert not hasattr(ev, "_rtlink_ai_state")
        assert kinoko.calls == sakura.calls == 0

    asyncio.run(run())


def make_web_api(router):
    request = SimpleNamespace(
        username="admin", headers={}, content_type="application/json", query={}
    )
    request.raw = b"{}"

    async def body():
        return request.raw

    request.body = body
    web = SimpleNamespace(
        request=request,
        json_response=lambda data, **kwargs: (data, 200, kwargs.get("headers")),
        error_response=lambda message, status_code=400: (
            {"message": message},
            status_code,
            {},
        ),
    )
    routes = []
    context = SimpleNamespace(
        registered_web_apis=routes, register_web_api=lambda *args: routes.append(args)
    )
    api = AdminAPI(SimpleNamespace(service=router, context=context), web)
    api.register()
    return api, web, routes


def test_dashboard_auth_no_store_and_unload(system):
    async def run():
        router, _, _, _ = system
        api, web, routes = make_web_api(router)
        assert [route[0] for route in routes] == [
            "/rt_link/admin/users",
            "/rt_link/admin/account",
            "/rt_link/admin/action",
        ]
        users = routes[0][1]
        assert (await users())[2] == {"Cache-Control": "no-store"}
        web.request.username = None
        assert all([(await route[1]())[1] == 401 for route in routes])
        web.request.username = "admin"
        web.request.headers = {"Sec-Fetch-Site": "cross-site"}
        assert (await users())[1] == 403
        web.request.headers = {}
        api.close()
        assert not routes and (await users())[1] == 503

    asyncio.run(run())


@pytest.mark.parametrize(
    "raw,content_type,expected",
    [
        (b"invalid", "application/json", 400),
        (b"[]", "application/json", 400),
        (b"{}", "text/plain", 415),
        (b"x" * 4097, "application/json", 413),
        (b"{}", "application/json", 400),
    ],
)
def test_dashboard_rejects_malformed_requests(system, raw, content_type, expected):
    async def run():
        router, _, kinoko, sakura = system
        _, web, routes = make_web_api(router)
        web.request.raw, web.request.content_type = raw, content_type
        assert (await routes[-1][1]())[1] == expected
        assert kinoko.calls == sakura.calls == 0

    asyncio.run(run())


@pytest.mark.parametrize(
    "changes",
    [
        {"owner_id": "unknown"},
        {"source": "unknown"},
        {"action": "delete_all"},
        {"token": "bad"},
        {"server": "bad"},
        {"player_id": "../bad"},
    ],
)
def test_invalid_management_does_not_touch_bindings(system, changes):
    async def run():
        router, admin, client, _ = system
        before = copy.deepcopy(await router.services["kinoko"].store.load())
        data = {
            "owner_id": "qq",
            "source": "kinoko",
            "action": "bind",
            "token": "tk_new",
            "player_id": "001234",
            "server": "cn",
            **changes,
        }
        with pytest.raises(AdminError):
            await admin.perform(data)
        assert before == await router.services["kinoko"].store.load()
        assert client.calls == 0

    asyncio.run(run())


def test_plugin_wires_persistent_stores_and_routes_and_cleans_up(tmp_path, monkeypatch):
    async def run():
        monkeypatch.setattr(main.StarTools, "get_data_dir", lambda _: tmp_path)
        context = mock.Context({"chart_library_auto_install": False})
        context.registered_web_apis = []
        context.register_web_api = lambda *args: context.registered_web_apis.append(
            args
        )
        _, web, _ = make_web_api(None)
        monkeypatch.setattr(sys.modules["astrbot.api"], "web", web, raising=False)
        star = main.RTLinkPlugin(context)
        assert star.admin_api is not None
        await star.service.known_store.save({"user": {"kinoko": {"player_id": "123"}}})
        assert "known_accounts" in star._kv
        assert len(context.registered_web_apis) == 3
        await star.terminate()
        assert not context.registered_web_apis

    asyncio.run(run())
