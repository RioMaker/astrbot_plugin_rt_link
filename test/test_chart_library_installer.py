"""Real loopback downloads into empty data directories; no external network."""

import asyncio
import hashlib
import json
import shutil
import warnings
import zipfile
from contextlib import asynccontextmanager

import pytest
from aiohttp import web
from test_chart_library import build_fixture

from chart_library import ChartLibrary
from chart_library_installer import ChartLibraryInstaller, InstallError
from service import MemoryBindingsStore, ScoreService


@pytest.fixture
def release(tmp_path, monkeypatch):
    root, manifest, *_ = build_fixture(tmp_path, monkeypatch)
    package = tmp_path / "package.zip"
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in root.rglob("*"):
            if path.is_file():
                archive.write(
                    path, "chart_library/" + path.relative_to(root).as_posix()
                )
    with zipfile.ZipFile(package) as archive:
        unpacked = sum(item.file_size for item in archive.infolist())
    spec = {
        "schemaVersion": 1,
        "buildId": manifest["buildId"],
        "chartsSha256": manifest["chartsSha256"],
        "archiveBytes": package.stat().st_size,
        "archiveSha256": hashlib.sha256(package.read_bytes()).hexdigest(),
        "unpackedBytes": unpacked,
        "url": "https://example.invalid/data.zip",
    }
    spec_path = tmp_path / "release.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    return root, package, spec_path, spec


@asynccontextmanager
async def server(package, *, gate=None, bad=False, chunked=False):
    calls = []

    async def get(request):
        calls.append(request.path)
        if gate:
            await gate.wait()
        data = package.read_bytes()
        if bad:
            data = bytes([data[0] ^ 1]) + data[1:]
        if chunked:
            response = web.StreamResponse()
            await response.prepare(request)
            await response.write(data + b"overflow")
            await response.write_eof()
            return response
        return web.Response(body=data)

    app = web.Application()
    app.router.add_get("/library.zip", get)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}/library.zip", calls
    finally:
        await runner.cleanup()


def make_installer(tmp_path, release, **kwargs):
    library = ChartLibrary(tmp_path / "installed", release[3]["chartsSha256"])
    return ChartLibraryInstaller(library, release[2], **kwargs)


@pytest.mark.parametrize("state", ["valid", "missing", "damaged"])
def test_bundled_install_without_network(tmp_path, release, monkeypatch, state):
    spec = dict(release[3], archiveFile=release[1].name)
    spec.pop("url")
    release[2].write_text(json.dumps(spec), encoding="utf-8")
    if state == "missing":
        release[1].unlink()
    elif state == "damaged":
        release[1].write_bytes(b"broken")

    def forbidden(*args, **kwargs):
        pytest.fail("bundled installation attempted network access")

    monkeypatch.setattr("chart_library_installer.aiohttp.ClientSession", forbidden)

    async def run():
        installer = make_installer(tmp_path, release)
        available = await installer.ensure()
        assert available == (state == "valid")
        if available:
            assert installer.library.query("Sample")["status"] == "ok"
            assert installer.status()["downloadedBytes"] == 0
            assert installer._use_bundled()
            assert release[1].is_file()  # Never remove the plugin's archive.
        else:
            assert installer.status()["status"] == "failed"
            assert not (installer.root / "current.json").exists()
        assert not list(installer.root.glob(".install-*"))
        await installer.close()

    asyncio.run(run())


def test_explicit_mirror_overrides_bundled_source(tmp_path, release):
    release[2].write_text(
        json.dumps(dict(release[3], archiveFile=release[1].name)), encoding="utf-8"
    )

    async def run():
        async with server(release[1]) as (url, calls):
            installer = make_installer(tmp_path, release, url=url)
            assert not installer._use_bundled()
            assert await installer.ensure()
            assert len(calls) == 1
            await installer.close()

    asyncio.run(run())


def test_empty_install_concurrent_public_lookup_and_restart(tmp_path, release):
    async def run():
        async with server(release[1]) as (url, calls):
            installer = make_installer(tmp_path, release, url=url)

            def forbidden(*args):
                pytest.fail("public lookup touched player/API")

            service = ScoreService(
                MemoryBindingsStore(),
                forbidden,
                chart_library=installer.library,
                chart_installer=installer,
            )
            results = await asyncio.gather(
                *(service.get_chart_analysis_text("Sample") for _ in range(5))
            )
            assert all(json.loads(result)["status"] == "ok" for result in results)
            assert len(calls) == 1
            assert installer.status()["status"] == "ready"
            assert not list(installer.root.glob(".install-*"))
            await installer.close()
            restarted = make_installer(tmp_path, release, url=url)
            assert await restarted.ensure()
            assert len(calls) == 1
            await restarted.close()

    asyncio.run(run())


def test_failed_hash_preserves_previous_version_and_retry(tmp_path, release):
    async def run():
        installed = tmp_path / "installed"
        shutil.copytree(release[0], installed)
        old = release[3]["buildId"]
        directory = installed / "versions" / old
        directory.rename(directory.with_name("old-generation"))
        manifest_path = directory.with_name("old-generation") / "manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        manifest["buildId"] = "old-generation"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        (installed / "current.json").write_text(
            json.dumps({"buildId": "old-generation"})
        )
        async with server(release[1], bad=True) as (url, calls):
            installer = make_installer(tmp_path, release, url=url)
            assert await installer.ensure()
            assert installer.status()["status"] == "failed"
            assert installer.library.query("Sample")["buildId"] == "old-generation"
            assert await installer.ensure()
            assert len(calls) == 1  # cooldown
        async with server(release[1]) as (url, calls):
            installer.url = url
            await installer.start(force=True)
            assert installer.status()["status"] == "ready"
            assert installer.library.query("Sample")["buildId"] == old
            assert (installed / "versions/old-generation").is_dir()
            await installer.close()

    asyncio.run(run())


def test_disabled_and_quota_do_not_download(tmp_path, release):
    async def run():
        async with server(release[1]) as (url, calls):
            installer = make_installer(tmp_path, release, url=url, enabled=False)
            assert not await installer.ensure()
            assert installer.status()["status"] == "disabled"
            installer.quota_bytes = 1
            await installer.start(force=True)
            assert installer.status()["status"] == "failed"
            assert "配额" in installer.status()["message"]
            assert not calls
            await installer.close()

    asyncio.run(run())


def test_chunked_download_is_bounded(tmp_path, release):
    async def run():
        async with server(release[1], chunked=True) as (url, _):
            installer = make_installer(tmp_path, release, url=url)
            assert not await installer.ensure()
            assert "超过" in installer.status()["message"]
            assert not (installer.root / "current.json").exists()
            assert not list(installer.root.glob(".install-*"))
            await installer.close()

    asyncio.run(run())


def test_query_timeout_does_not_cancel_download_and_unload_cleans(tmp_path, release):
    async def run():
        gate = asyncio.Event()
        async with server(release[1], gate=gate) as (url, _):
            installer = make_installer(tmp_path, release, url=url)
            assert not await installer.ensure(wait_seconds=0.05)
            assert installer.status()["status"] == "downloading"
            assert not installer._task.done()
            await installer.close()
            gate.set()
            assert installer.status()["status"] == "closed"
            assert not list(installer.root.glob(".install-*"))

    asyncio.run(run())


def test_same_generation_damage_is_backed_up_and_repaired(tmp_path, release):
    async def run():
        shutil.copytree(release[0], tmp_path / "installed")
        async with server(release[1]) as (url, calls):
            installer = make_installer(tmp_path, release, url=url)
            assert await installer.ensure()
            assert not calls
            db = (
                installer.root / "versions" / release[3]["buildId"] / "analysis.sqlite3"
            )
            db.write_bytes(b"damaged")
            await installer.start(force=True)
            assert installer.status()["status"] == "ready"
            assert installer.library.query("Sample")["status"] == "ok"
            backups = list((installer.root / "versions").glob("*-backup-*"))
            assert len(backups) == 1
            assert (backups[0] / "analysis.sqlite3").read_bytes() == b"damaged"
            await installer.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "mutation", ["traversal", "duplicate", "symlink", "charts", "db"]
)
def test_archive_and_manifest_validation(tmp_path, release, mutation):
    installer = make_installer(tmp_path, release)
    if mutation in ("traversal", "duplicate", "symlink"):
        with zipfile.ZipFile(release[1]) as archive:
            files = [(item.filename, archive.read(item)) for item in archive.infolist()]
        with warnings.catch_warnings(), zipfile.ZipFile(release[1], "w") as archive:
            warnings.filterwarnings(
                "ignore", message="Duplicate name:", category=UserWarning
            )
            for i, (name, data) in enumerate(files):
                if i == 0 and mutation == "traversal":
                    name = "../escaped.json"
                if i == 0 and mutation == "duplicate":
                    name = files[1][0]
                info = zipfile.ZipInfo(name)
                if i == 0 and mutation == "symlink":
                    info.external_attr = 0o120777 << 16
                archive.writestr(info, data)
        with pytest.raises(InstallError):
            installer._extract_verify(release[1], tmp_path / "staging")
        assert not (tmp_path / "escaped.json").exists()
    else:
        generation = release[0] / "versions" / release[3]["buildId"]
        if mutation == "charts":
            installer.spec["chartsSha256"] = "wrong-catalog"
        else:
            (generation / "analysis.sqlite3").write_bytes(b"bad")
        with pytest.raises(InstallError):
            installer._verify_generation(generation)


def test_retry_command_requires_admin(tmp_path, release):
    import mock_astrbot as mock

    mock.install()
    import main

    installer = make_installer(tmp_path, release, enabled=False)
    plugin = object.__new__(main.RTLinkPlugin)
    plugin.chart_installer = installer
    plugin.service = ScoreService(
        MemoryBindingsStore(),
        None,
        chart_library=installer.library,
        chart_installer=installer,
    )

    async def run():
        event = mock.AstrMessageEvent(
            "test", private=True, is_admin=False, message_str="/rtlink library retry"
        )
        results = [item async for item in plugin.rtlink(event)]
        assert results == ["仅管理员可重试安装分析库。"]
        assert installer._task is None
        event = mock.AstrMessageEvent(
            "test", private=True, is_admin=True, message_str="/rtlink library retry"
        )
        installer.quota_bytes = 1
        results = [item async for item in plugin.rtlink(event)]
        assert json.loads(results[0])["installation"]["status"] == "failed"
        await installer.close()

    asyncio.run(run())


def test_plugin_startup_and_terminate_use_installer(tmp_path, release, monkeypatch):
    import mock_astrbot as mock

    mock.install()
    import main

    monkeypatch.setattr(
        main.StarTools, "get_data_dir", lambda name: tmp_path / "astrbot-data"
    )

    def pinned_fixture(library, release_path, **kwargs):
        return ChartLibraryInstaller(library, release[2], **kwargs)

    monkeypatch.setattr(main, "ChartLibraryInstaller", pinned_fixture)

    async def run():
        async with server(release[1]) as (url, calls):
            plugin = main.RTLinkPlugin(
                mock.Context({"chart_library_download_url": url})
            )
            assert plugin.chart_installer._task is not None
            await plugin.chart_installer._task
            result = json.loads(await plugin.get_chart_analysis(None, "Sample"))
            assert result["status"] == "ok"
            assert len(calls) == 1
            await plugin.terminate()
            assert plugin.chart_installer._closed

    asyncio.run(run())
