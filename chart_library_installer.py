"""Background installation of a pinned, verified public chart library."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import sqlite3
import stat
import time
import uuid
import zipfile
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp

if __package__:
    from .chart_library import _file_sha256
else:
    from chart_library import _file_sha256


class InstallError(Exception):
    """Safe, user-facing installation failure without URLs or credentials."""


class ChartLibraryInstaller:
    RETRY_SECONDS = 300

    def __init__(
        self, library, release_path, *, enabled=True, url="", quota_mb=512, logger=None
    ):
        self.library = library
        self.root = library.root
        self.enabled = enabled
        self.quota_bytes = max(1, int(quota_mb)) * 1048576
        self.logger = logger
        self._task = None
        self._closed = False
        self._next_retry = 0.0
        self._pointer_signature = None
        self._state = "idle"
        self._error = ""
        self._downloaded = 0
        self.spec = {}
        try:
            self.spec = json.loads(Path(release_path).read_bytes())
            if not isinstance(self.spec, dict):
                self.spec = {}
                raise TypeError("release object")
            if self.spec.get("schemaVersion") != 1 or not re.fullmatch(
                r"[A-Za-z0-9_-]{1,80}", self.spec["buildId"]
            ):
                raise ValueError("release identity")
            if not re.fullmatch(r"[0-9a-f]{64}", self.spec["archiveSha256"]):
                raise ValueError("archive hash")
            if not re.fullmatch(r"[0-9a-f]{64}", self.spec["chartsSha256"]):
                raise ValueError("catalog hash")
            for key in ("archiveBytes", "unpackedBytes"):
                if (
                    not isinstance(self.spec[key], int)
                    or not 0 < self.spec[key] < 512 * 1048576
                ):
                    raise ValueError("release size")
            if library.charts_hash and library.charts_hash != self.spec["chartsSha256"]:
                raise ValueError("catalog hash")
            self.url = str(url or self.spec["url"]).strip()
            parsed = urlsplit(self.url)
            # HTTP is only allowed for loopback integration testing/local mirrors.
            if (
                not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.fragment
                or (
                    parsed.scheme != "https"
                    and not (
                        parsed.scheme == "http"
                        and parsed.hostname in ("127.0.0.1", "localhost", "::1")
                    )
                )
            ):
                raise ValueError("download URL")
        except (OSError, ValueError, KeyError, TypeError):
            self._state = "invalid"
            self._error = "分析库发布清单或下载地址无效，请检查插件文件和配置。"

    def _signature(self):
        try:
            value = (self.root / "current.json").stat()
            return value.st_mtime_ns, value.st_size
        except OSError:
            return None

    def start(self, *, force=False):
        """Start at most one worker; safe when constructed outside an event loop."""
        if self._closed or self._state == "invalid":
            return None
        if self._task and not self._task.done():
            return self._task
        if not force:
            if self._state == "ready" and self._signature() == self._pointer_signature:
                return None
            if time.monotonic() < self._next_retry:
                return None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return None
        self._task = loop.create_task(
            self._run(force), name="rtlink-chart-library-install"
        )
        return self._task

    async def ensure(self, *, wait_seconds=2.0):
        task = self.start()
        if task:
            await asyncio.wait({task}, timeout=wait_seconds)
        # A previous compatible library remains queryable during an update or
        # download failure. The caller returns the build ID with every result.
        if self._state == "ready":
            return True
        return (await asyncio.to_thread(self.library.status))["available"]

    def status(self):
        return {
            "status": self._state,
            "downloadedBytes": self._downloaded,
            "totalBytes": self.spec.get("archiveBytes", 0),
            "message": self._error
            or {
                "idle": "分析库等待初始化。",
                "checking": "正在检查本地分析库。",
                "downloading": "正在首次安装或更新分析库，请稍后重试查询。",
                "verifying": "下载完成，正在校验分析库。",
                "ready": "分析库已就绪。",
                "disabled": "自动安装已关闭；可手动导入或由管理员执行 /rtlink library retry。",
                "closed": "插件已卸载。",
            }.get(self._state, "安装失败；管理员可执行 /rtlink library retry。"),
            "retryAfterSeconds": max(0, round(self._next_retry - time.monotonic())),
        }

    async def close(self):
        self._closed = True
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _worker(self, function, *args):
        # Do not remove temp files while a cancelled to_thread worker still uses
        # them. Plugin unload waits for the bounded extraction/validation phase.
        task = asyncio.create_task(asyncio.to_thread(function, *args))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                await task
            finally:
                raise

    def _check_space(self):
        self.root.mkdir(parents=True, exist_ok=True)
        used = sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file())
        needed = self.spec["archiveBytes"] + self.spec["unpackedBytes"] + 8 * 1048576
        if used + needed > self.quota_bytes:
            raise InstallError(
                "分析库配额不足；旧版本已保留，请调整 chart_library_quota_mb。"
            )
        if shutil.disk_usage(self.root).free < needed + 128 * 1048576:
            raise InstallError(
                "磁盘剩余空间不足；需为下载、解压及 128 MiB 余量留出空间。"
            )

    async def _download(self, destination):
        timeout = aiohttp.ClientTimeout(total=300, sock_connect=15, sock_read=30)
        digest = hashlib.sha256()
        self._downloaded = 0
        async with (
            aiohttp.ClientSession(
                timeout=timeout, trust_env=True, auto_decompress=False
            ) as session,
            session.get(
                self.url,
                headers={"User-Agent": "rtlink-chart-library/1"},
                allow_redirects=True,
            ) as response,
        ):
            if response.status != 200:
                raise InstallError(
                    f"分析库下载失败（HTTP {response.status}）；请确认数据包已发布或配置可用镜像。"
                )
            if urlsplit(self.url).scheme == "https" and response.url.scheme != "https":
                raise InstallError("分析库下载发生不安全的协议降级。")
            if (
                response.content_length is not None
                and response.content_length != self.spec["archiveBytes"]
            ):
                raise InstallError("分析库下载大小与发布清单不符。")
            with destination.open("xb") as stream:
                async for chunk in response.content.iter_chunked(256 * 1024):
                    self._downloaded += len(chunk)
                    if self._downloaded > self.spec["archiveBytes"]:
                        raise InstallError("分析库下载超过发布清单大小。")
                    digest.update(chunk)
                    stream.write(chunk)
        if (
            self._downloaded != self.spec["archiveBytes"]
            or digest.hexdigest() != self.spec["archiveSha256"]
        ):
            raise InstallError("分析库数据包 SHA-256 或大小校验失败；原有数据未切换。")

    def _extract_verify(self, package, temporary):
        build_id = self.spec["buildId"]
        prefix = f"chart_library/versions/{build_id}/"
        allowed = {
            "chart_library/current.json",
            *(
                prefix + name
                for name in (
                    "manifest.json",
                    "analysis.sqlite3",
                    "tja.zip",
                    "sources.json",
                )
            ),
        }
        with zipfile.ZipFile(package) as archive:
            entries = archive.infolist()
            if (
                len(entries) != len(allowed)
                or {item.filename for item in entries} != allowed
            ):
                raise InstallError("分析库压缩包包含非预期路径或重复文件。")
            if sum(item.file_size for item in entries) != self.spec["unpackedBytes"]:
                raise InstallError("分析库解压体积与发布清单不符。")
            for item in entries:
                if (
                    item.is_dir()
                    or stat.S_ISLNK(item.external_attr >> 16)
                    or item.flag_bits & 1
                ):
                    raise InstallError("分析库压缩包包含非普通文件。")
                target = temporary / item.filename
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
        directory = temporary / "chart_library" / "versions" / build_id
        pointer = json.loads((temporary / "chart_library/current.json").read_bytes())
        if pointer != {"buildId": build_id}:
            raise InstallError("分析库版本指针与发布清单不符。")
        self._verify_generation(directory)
        return directory

    def _verify_generation(self, directory):
        manifest = json.loads((directory / "manifest.json").read_bytes())
        if (
            manifest.get("schemaVersion") != 1
            or manifest.get("buildId") != self.spec["buildId"]
            or manifest.get("chartsSha256") != self.spec["chartsSha256"]
        ):
            raise InstallError("分析库版本或歌曲目录校验失败。")
        if set(manifest["files"]) != {"analysis.sqlite3", "tja.zip", "sources.json"}:
            raise InstallError("分析库文件清单无效。")
        for name, meta in manifest["files"].items():
            path = directory / name
            if (
                path.is_symlink()
                or path.stat().st_size != meta["bytes"]
                or _file_sha256(path) != meta["sha256"]
            ):
                raise InstallError("分析库内部文件校验失败；原有数据未切换。")
        with closing(
            sqlite3.connect(
                (directory / "analysis.sqlite3").resolve().as_uri() + "?mode=ro",
                uri=True,
            )
        ) as db:
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise InstallError("分析数据库完整性校验失败。")
            if (
                db.execute("SELECT count(*) FROM charts").fetchone()[0]
                != manifest["analyses"]
            ):
                raise InstallError("分析数据库记录数量不符。")

    def _publish(self, directory):
        # Readers finish before a same-version repair renames the database.
        with self.library._lock:
            self._publish_locked(directory)
            self.library.invalidate()

    def _publish_locked(self, directory):
        destination = self.root / "versions" / self.spec["buildId"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            try:
                self._verify_generation(destination)
            except (InstallError, OSError, ValueError, KeyError, sqlite3.Error):
                # Preserve even a damaged same-version folder before repair.
                backup = destination.with_name(
                    destination.name + "-backup-" + uuid.uuid4().hex[:8]
                )
                destination.rename(backup)
                try:
                    directory.rename(destination)
                except OSError:
                    backup.rename(destination)
                    raise
        else:
            directory.rename(destination)
        pointer = self.root / ("current." + uuid.uuid4().hex + ".tmp")
        pointer.write_text(
            json.dumps({"buildId": self.spec["buildId"]}), encoding="utf-8"
        )
        pointer.replace(self.root / "current.json")

    async def _run(self, force):
        temporary = None
        self._state, self._error = "checking", ""
        try:
            if force:
                self.library.invalidate()
            current = await self._worker(self.library.status)
            if current["available"] and current["buildId"] == self.spec["buildId"]:
                try:
                    await self._worker(
                        self._verify_generation,
                        self.root / "versions" / self.spec["buildId"],
                    )
                except (InstallError, OSError, ValueError, KeyError, sqlite3.Error):
                    pass  # Download a replacement, preserving the damaged folder.
                else:
                    self._state = "ready"
                    self._pointer_signature = self._signature()
                    self._next_retry = 0
                    return
            if not self.enabled and not force:
                self._state = "disabled"
                self._next_retry = time.monotonic() + self.RETRY_SECONDS
                return
            await self._worker(self._check_space)
            temporary = self.root / (".install-" + uuid.uuid4().hex)
            temporary.mkdir()
            package = temporary / "download.zip"
            self._state = "downloading"
            await self._download(package)
            self._state = "verifying"
            directory = await self._worker(self._extract_verify, package, temporary)
            await self._worker(self._publish, directory)
            self._pointer_signature = self._signature()
            self._state = "ready"
            self._next_retry = 0
            if self.logger:
                self.logger.info("rt_link：公共 TJA 分析库已校验并启用。")
        except asyncio.CancelledError:
            self._state = "closed"
            raise
        except InstallError as error:
            self._state, self._error = "failed", str(error)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            self._state, self._error = (
                "failed",
                "分析库下载连接失败或超时；可稍后重试或配置镜像地址。",
            )
        except Exception as error:  # noqa: BLE001 - background task must expose a safe failure state
            self._state, self._error = (
                "failed",
                f"分析库安装失败（{type(error).__name__}）；原有数据未切换。",
            )
        finally:
            if self._state == "failed":
                self._next_retry = time.monotonic() + self.RETRY_SECONDS
                if self.logger:
                    self.logger.warning("rt_link：" + self._error)
            if temporary and temporary.exists():
                # This is our unique staging directory; never delete generations.
                try:
                    await self._worker(shutil.rmtree, temporary)
                except OSError:
                    if self.logger:
                        self.logger.warning(
                            "rt_link：安装暂存目录清理失败；已启用的数据不受影响。"
                        )
