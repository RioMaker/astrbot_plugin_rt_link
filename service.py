# -*- coding: utf-8 -*-
"""rt_link 核心服务层：与 AstrBot 解耦，可独立测试。

包含：
- BindingsStore 抽象及内存/JSON 文件两种实现（AstrBot 用 KV，测试用文件）
- ScoreService：绑定/解绑/列表/曲名查分等核心逻辑
- match_songs / format_records：曲名模糊匹配与成绩格式化
"""

import asyncio
import json
import os
import time
from collections import defaultdict

# 包加载（AstrBot）时用相对导入；本地直接运行 service.py 时回退到绝对导入。
if __package__:
    from .api_client import KinokoClient, KinokoAPIError
else:
    from api_client import KinokoClient, KinokoAPIError


class BindingsStore:
    """绑定存储抽象接口。"""

    async def load(self) -> dict:
        raise NotImplementedError

    async def save(self, data: dict) -> None:
        raise NotImplementedError


class MemoryBindingsStore(BindingsStore):
    def __init__(self, initial: dict | None = None):
        self._data = dict(initial or {})

    async def load(self) -> dict:
        return dict(self._data)

    async def save(self, data: dict) -> None:
        self._data = dict(data)


class JsonFileBindingsStore(BindingsStore):
    def __init__(self, path: str):
        self.path = path

    async def load(self) -> dict:
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    async def save(self, data: dict) -> None:
        d = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(d, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)


def match_songs(records: list, query: str) -> list:
    """按曲名/日文名/副标题做大小写不敏感的包含匹配。"""
    q = (query or "").strip().lower()
    matched = []
    for r in records:
        sd = r.get("song_detail") or {}
        hay = " | ".join(
            [
                str(sd.get("song_name") or ""),
                str(sd.get("song_name_jp") or ""),
                str(sd.get("subtitle") or ""),
            ]
        ).lower()
        if q and q in hay:
            matched.append(r)
    return matched


def format_records(records: list) -> str:
    """把命中的成绩记录按歌曲分组、按难度排序后格式化为文本。"""
    by_song = defaultdict(list)
    for r in records:
        by_song[r.get("song_no")].append(r)

    lines = []
    for song_no, recs in by_song.items():
        recs.sort(key=lambda x: x.get("level", 0))
        sd = recs[0].get("song_detail") or {}
        name = sd.get("song_name") or str(song_no)
        name_jp = sd.get("song_name_jp") or ""
        subtitle = sd.get("subtitle") or ""
        title = f"《{name}》"
        if name_jp and name_jp != name:
            title += f"（{name_jp}）"
        if subtitle:
            title += f" - {subtitle}"
        lines.append(title)
        for r in recs:
            lines.append(
                "  难度{}：{} 评分{}｜良{} 可{} 不可{}｜全连{} 咚大福{}".format(
                    r.get("level"),
                    r.get("high_score"),
                    r.get("best_score_rank"),
                    r.get("good_cnt"),
                    r.get("ok_cnt"),
                    r.get("ng_cnt"),
                    r.get("full_combo_cnt"),
                    r.get("dondaful_combo_cnt"),
                )
            )
    return "\n".join(lines)


class ScoreService:
    """rt_link 核心业务逻辑。"""

    def __init__(
        self,
        store: BindingsStore,
        client_factory,
        default_server: str = "cn",
        cache_ttl: int = 60,
    ):
        self.store = store
        self._client_factory = client_factory
        self.default_server = default_server
        self.cache_ttl = cache_ttl
        self._scores_cache: dict = {}

    def _client(self, apikey: str) -> KinokoClient:
        return self._client_factory(apikey)

    async def bind(self, qq, apikey, player_id, server="") -> tuple[bool, str]:
        if not qq:
            return False, "无法获取你的 QQ 号。"
        if not apikey.startswith("tk_"):
            return False, "apikey 应以 tk_ 开头，请检查后重试。"
        server = server or self.default_server
        try:
            await asyncio.to_thread(
                self._client(apikey).hiroba_recent,
                player_id=player_id,
                server=server,
            )
        except KinokoAPIError as e:
            return False, f"绑定失败：无法用该 apikey 查询玩家 {player_id}（{e}）"

        bindings = await self.store.load()
        bindings[qq] = {"apikey": apikey, "player_id": player_id, "server": server}
        await self.store.save(bindings)
        return True, f"绑定成功：QQ {qq} ↔ 玩家 {player_id}（{server}）。现在可查询成绩。"

    async def unbind(self, qq) -> tuple[bool, str]:
        bindings = await self.store.load()
        if qq in bindings:
            del bindings[qq]
            await self.store.save(bindings)
            return True, "已解绑。"
        return False, "你还没有绑定记录。"

    async def list_bindings(self) -> str:
        bindings = await self.store.load()
        if not bindings:
            return "暂无绑定记录。"
        lines = ["当前绑定："]
        for qq, b in bindings.items():
            lines.append(f"  QQ {qq} → 玩家 {b.get('player_id')}（{b.get('server')}）")
        return "\n".join(lines)

    async def _fetch_scores(self, apikey, player_id, server) -> dict:
        key = (apikey[-8:], player_id, server)
        cached = self._scores_cache.get(key)
        if cached and (time.time() - cached[0]) < self.cache_ttl:
            return cached[1]
        data = await asyncio.to_thread(
            self._client(apikey).hiroba, player_id=player_id, server=server
        )
        self._scores_cache[key] = (time.time(), data)
        return data

    async def query_score_text(self, qq, song_name) -> str:
        if not qq:
            return "无法识别你的 QQ 号。"
        b = (await self.store.load()).get(qq)
        if not b:
            return "你还没有绑定菌菌账号。请先发送：/rt_link bind <apikey> <player_id> [server]"
        try:
            data = await self._fetch_scores(
                b["apikey"],
                str(b.get("player_id") or ""),
                b.get("server") or self.default_server,
            )
        except KinokoAPIError as e:
            return f"查询失败：{e}"

        played = (data or {}).get("data", {}).get("playedRecords", {})
        records = played.get("scoreInfo", [])
        matched = match_songs(records, song_name)
        if not matched:
            return f"未找到与「{song_name}」匹配的曲目，试试更精确的曲名。"
        text = format_records(matched)
        if len(matched) > 40:
            text += "\n（结果较多，建议输入更精确的曲名）"
        return text
