"""多来源隔离、旧库兼容、网络边界及真实命令入口回归。使用合成凭据。"""

import asyncio
import copy
import io
import json
import urllib.error
from pathlib import Path

import pytest

from sakura_client import SakuraAPIError, SakuraClient, _NoRedirect, normalize_sakura
from service import MemoryBindingsStore, ScoreService
from source_service import MultiSourceService
from storage import ScoreDatabase, load_charts


@pytest.fixture(scope="module")
def charts():
    return load_charts(Path(__file__).resolve().parents[1] / "resource/charts.v1.json.gz")


def payload(charts, score=900000):
    key, chart = next((key, chart) for key, chart in charts.items() if key[1] == 4 and chart.get("totalNotes", 0) > 10)
    return {"ok": True, "taikoId": "001234", "fetchedAt": "2026-10-14T08:00:00Z", "data": {
        "profile": {"userid": "001234", "mydon_name": "Test"},
        "songs": [{"song_no": key[0], "level": 4, "good_cnt": chart["totalNotes"] - 2,
                   "ok_cnt": 2, "ng_cnt": 0, "high_score": score, "best_score_rank": 5,
                   "pound_cnt": 0, "clear_cnt": 1, "full_combo_cnt": 1, "dondaful_combo_cnt": 0,
                   "update_datetime": "2026-10-14 16:00:00", "option_flg": [1]}],
        "achievement": {"count_level": 5}, "dojo": {"extra": True}, "_meta": {"source": "wahlap"},
    }}


class Client:
    def __init__(self, data):
        self.data = data
        self.calls = 0
        self.fail = False

    def fetch(self):
        self.calls += 1
        if self.fail:
            raise SakuraAPIError("Sakura HTTP 401：token 无效")
        return copy.deepcopy(self.data)

    def hiroba(self, *args, **kwargs):
        return normalize_sakura(copy.deepcopy(self.data))

    kinoko = hiroba
    hiroba_recent = hiroba


def setup_services(tmp_path, charts):
    old = ScoreDatabase(tmp_path / "rt_link.db")
    new = ScoreDatabase(tmp_path / "sources/sakura/rt_link.db")
    old_store = MemoryBindingsStore({"qq": {"apikey": "tk_test", "player_id": "001234", "server": "cn"}})
    token_store = MemoryBindingsStore()
    old_client, new_client = Client(payload(charts)), Client(payload(charts, 1000000))
    services = {
        "kinoko": ScoreService(old_store, lambda _: old_client, charts, old, report_dir=str(tmp_path)),
        "sakura": ScoreService(token_store, lambda _: new_client, charts, new, provider="sakura", alias_db=old, report_dir=str(tmp_path / "sources/sakura")),
    }
    selections = MemoryBindingsStore()
    return MultiSourceService(services, selections), old_client, new_client


def test_independent_databases_binding_cache_history_and_restart(tmp_path, charts):
    async def run():
        router, _, client = setup_services(tmp_path, charts)
        kinoko, sakura = router.services.values()
        try:
            # 无迁移、无新配置时仍读旧绑定与旧数据库。
            assert await router.current_source("qq") == "kinoko"
            assert (await router.force_update("qq"))[0]
            old_rows = kinoko.db.get_scores("qq")
            old_cache = kinoko.db.get_rating_cache("qq")
            old_history = kinoko.db.get_rating_snapshots("qq")
            old_config = kinoko.db.storage_stats()["configuration_snapshot_count"]
            old_binding = await kinoko._binding("qq")
            assert (await router.bind_sakura("qq", "x" * 48))[0]
            assert (await router.force_update("qq"))[0]
            assert await router.current_source("qq") == "sakura"
            assert kinoko.db.get_scores("qq") == old_rows
            assert kinoko.db.get_rating_cache("qq") == old_cache
            assert kinoko.db.get_rating_snapshots("qq") == old_history
            assert kinoko.db.storage_stats()["configuration_snapshot_count"] == old_config
            assert await kinoko._binding("qq") == old_binding
            assert sakura.db.get_scores("qq")[0]["high_score"] == 1000000
            assert {row["source"] for row in sakura.db.get_scores("qq")} == {"sakura"}
            assert sakura.db.kv_get("source_payload:qq")["data"]["dojo"] == {"extra": True}
            assert sakura.db.get_rating_cache("qq")["meta"]["provider"] == "Sakura"
            families = sakura.db.get_rating_cache("qq")["featureAbility"]["families"]
            assert all(not row["title"].startswith("Song ") for family in families for row in family["best"])
            snapshots = sakura.db.get_rating_snapshots("qq")
            assert snapshots and "x" * 48 not in json.dumps(snapshots)
            count = client.calls
            await asyncio.gather(router.get_rating_text("qq"), router.get_profile_text("qq"))
            assert client.calls == count  # 缓存仅从当前来源读取。
            assert (await router.force_update("qq"))[0]
            assert sakura.db.get_rating_snapshots("qq") == snapshots
            client.data["data"]["songs"][0]["good_cnt"] += 1
            client.data["data"]["songs"][0]["ok_cnt"] -= 1
            assert (await router.force_update("qq"))[0]
            snapshots = sakura.db.get_rating_snapshots("qq")
            assert len(snapshots) == 2
            assert kinoko.db.get_rating_snapshots("qq") == old_history
            assert kinoko.db.get_scores("qq") == old_rows
            restarted = MultiSourceService(router.services, router.selection_store)
            assert await restarted.current_source("qq") == "sakura"
            assert "kinoko" in await restarted.source_text("qq", "kinoko")
            assert "菌菌" in await restarted.source_text("qq")
            assert (await restarted.unbind("qq"))[0]
            assert await sakura._binding("qq") is not None
            assert sakura.db.get_scores("qq")
            await restarted.source_text("qq", "sakura")
            assert (await restarted.unbind("qq"))[0]
            assert sakura.db.get_rating_snapshots("qq") == snapshots
        finally:
            kinoko.db.close()
            sakura.db.close()
        reopened = ScoreDatabase(tmp_path / "sources/sakura/rt_link.db")
        try:
            assert reopened.get_rating_snapshots("qq") == snapshots
            assert reopened.get_scores("qq")[0]["source"] == "sakura"
        finally:
            reopened.close()
    asyncio.run(run())


def test_failed_bind_sync_and_identity_change_do_not_overwrite(tmp_path, charts):
    async def run():
        router, _, client = setup_services(tmp_path, charts)
        try:
            client.fail = True
            assert not (await router.bind_sakura("qq", "x" * 48))[0]
            assert await router.current_source("qq") == "kinoko"
            assert await router.services["sakura"]._binding("qq") is None
            client.fail = False
            assert (await router.bind_sakura("qq", "x" * 48))[0]
            assert (await router.force_update("qq"))[0]
            db = router.services["sakura"].db
            before = db.get_scores("qq"), db.get_rating_cache("qq"), db.get_rating_snapshots("qq")
            for kind in ("identity", "network", "malformed"):
                client.data = payload(charts)
                client.fail = kind == "network"
                if kind == "identity":
                    client.data["taikoId"] = "other"
                    client.data["data"]["profile"]["userid"] = "other"
                if kind == "malformed":
                    client.data["data"]["songs"] = [None]
                assert not (await router.force_update("qq"))[0]
                assert (db.get_scores("qq"), db.get_rating_cache("qq"), db.get_rating_snapshots("qq")) == before
        finally:
            for service in router.services.values():
                service.db.close()
    asyncio.run(run())


def test_switch_waits_for_inflight_operation(tmp_path, charts):
    async def run():
        router, _, _ = setup_services(tmp_path, charts)
        started, release = asyncio.Event(), asyncio.Event()
        try:
            await router.bind_sakura("qq", "x" * 48)
            async def blocked(qq):
                started.set()
                await release.wait()
                return "Sakura"
            router.services["sakura"].get_rating_text = blocked
            task = asyncio.create_task(router.get_rating_text("qq"))
            await started.wait()
            switch = asyncio.create_task(router.source_text("qq", "kinoko"))
            await asyncio.sleep(0)
            assert not switch.done()
            release.set()
            assert await task == "Sakura"
            await switch
            assert await router.current_source("qq") == "kinoko"
        finally:
            for service in router.services.values():
                service.db.close()
    asyncio.run(run())


def test_transport_never_echoes_token_or_follows_redirect(monkeypatch, charts):
    token = "z" * 48
    class Opener:
        def open(self, request, timeout):
            assert request.full_url == SakuraClient.ENDPOINT
            assert request.method == "POST"
            assert json.loads(request.data) == {"token": token}
            assert token not in request.full_url
            raise urllib.error.HTTPError(request.full_url, 401, token, {}, io.BytesIO(json.dumps({"detail": token}).encode()))
    monkeypatch.setattr("urllib.request.build_opener", lambda *args: Opener())
    with pytest.raises(SakuraAPIError) as error:
        SakuraClient(token).fetch()
    assert "401" in str(error.value) and token not in str(error.value)
    assert _NoRedirect().redirect_request(None, None, 307, "", {}, "https://example.com") is None


def test_normalization_preserves_zero_unknown_fields_and_identity(charts):
    data = payload(charts)
    normalized = normalize_sakura(data)
    played = normalized["data"]["playedRecords"]
    assert played["userid"] == "001234"
    assert played["scoreInfo"][0]["pound_cnt"] == 0
    assert played["scoreInfo"][0]["option_flg"] == [1]
    assert "combo_cnt" not in played["scoreInfo"][0]
    data["data"].pop("_meta")
    assert normalize_sakura(data)["data"]["playedRecords"]["server"] == "unknown"
    with pytest.raises(SakuraAPIError):
        normalize_sakura(data, "wrong")


def test_shared_aliases_work_for_sakura_only_binding(tmp_path, charts):
    async def run():
        router, _, _ = setup_services(tmp_path, charts)
        try:
            await router.services["kinoko"].unbind("qq")
            await router.bind_sakura("qq", "x" * 48)
            song_no = payload(charts)["data"]["songs"][0]["song_no"]
            message = await router.request_alias("qq", str(song_no), "多源测试别名")
            assert "已收到" in message
            assert router.services["sakura"].db.list_pending_aliases() == []
            assert "多源测试别名" in await router.list_pending_aliases_text()
            await router.approve_aliases_text("all")
            aliases = await router.services["sakura"]._get_alias_map()
            assert aliases["多源测试别名"] == song_no
        finally:
            for service in router.services.values():
                service.db.close()
    asyncio.run(run())


def test_command_private_binding_and_source_dispatch():
    import test_command_dispatch as dispatch
    mock, main = dispatch.mock, dispatch.main
    async def run():
        plugin = dispatch.make_plugin()
        seen = []
        async def bind(qq, token):
            seen.append((qq, token))
            return True, "Sakura 绑定成功"
        async def source(qq, name):
            return "来源：" + name
        plugin.service.bind_sakura = bind
        plugin.service.source_text = source
        token = "x" * 48
        for private in (False, True):
            event = mock.AstrMessageEvent("qq", private=private, is_admin=False, message_str=f"/rtlink bind sakura {token}")
            text = await dispatch.invoke(plugin, event)
            assert token not in str(text)
            assert len(seen) == int(private)
        event = mock.AstrMessageEvent("qq", private=True, is_admin=False, message_str="/rtlink source sakura")
        assert await dispatch.invoke(plugin, event) == ["来源：sakura"]
    asyncio.run(run())


def test_plugin_startup_preserves_legacy_keys_and_owns_two_databases(tmp_path, monkeypatch):
    import test_command_dispatch as dispatch
    mock, main = dispatch.mock, dispatch.main
    monkeypatch.setattr(main.StarTools, "get_data_dir", lambda _: str(tmp_path))
    async def run():
        plugin = main.RTLinkPlugin(mock.Context({"chart_library_auto_install": False}))
        try:
            legacy = {"qq": {"apikey": "tk_legacy", "player_id": "old", "server": "cn"}}
            plugin._kv["bindings"] = legacy
            assert await plugin.service.current_source("qq") == "kinoko"
            assert await plugin.service.services["kinoko"].store.load() == legacy
            assert await plugin.service.services["sakura"].store.load() == {}
            await plugin.service.services["sakura"].store.save({"test": {"apikey": "synthetic"}})
            assert plugin._kv["bindings"] == legacy
            assert "bindings_sakura" in plugin._kv
            assert Path(plugin.db.db_path) == tmp_path / "rt_link.db"
            assert Path(plugin.sakura_db.db_path) == tmp_path / "sources/sakura/rt_link.db"
            assert plugin.service.services["sakura"].alias_db is plugin.db
        finally:
            await plugin.terminate()
    asyncio.run(run())
