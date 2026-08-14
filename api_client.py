# -*- coding: utf-8 -*-
"""
菌菌控制台公开 API 客户端（标准库实现，无第三方依赖）。

公开 API 契约（已实测验证）：
- Base URL : https://kinoko.zorua.cn/api/v1
- 鉴权     : Authorization: Bearer <tk_... API Key>
- 成绩端点 : GET /scores/hiroba | /scores/kinoko
              GET /scores/hiroba/recent | /scores/kinoko/recent
- 查询参数 : player_id (string, 可选，账号拥有的玩家 ID)
              server    (cn | jp | custom, 可选)

响应结构（hiroba 风格）：
    {"data": {"playedRecords": {"userid": "...", "server": "cn",
        "scoreInfo": [{song_no, level, high_score, best_score_rank,
                       good_cnt, ok_cnt, ng_cnt, pound_cnt, combo_cnt,
                       clear_cnt, full_combo_cnt, dondaful_combo_cnt,
                       highscore_datetime, song_detail: {...}}]}}}
"""

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request


class KinokoAPIError(Exception):
    """菌菌 API 调用错误。"""


class KinokoClient:
    DEFAULT_BASE_URL = "https://kinoko.zorua.cn/api/v1"

    def __init__(self, apikey: str, base_url: str | None = None, timeout: int = 30):
        self.apikey = apikey
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout
        self._ctx = ssl.create_default_context()

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = self.base_url + path
        if params:
            query = urllib.parse.urlencode(
                {k: v for k, v in params.items() if v not in (None, "")}
            )
            if query:
                url += "?" + query

        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": "Bearer " + self.apikey,
                "User-Agent": "astrbot-plugin-rt_link/0.1",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self._ctx) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = json.loads(e.read().decode("utf-8")).get("detail", "")
            except Exception:
                pass
            raise KinokoAPIError(f"HTTP {e.code}: {detail or e.reason}")
        except urllib.error.URLError as e:
            raise KinokoAPIError(f"网络错误: {e.reason}")

    # -- 成绩查询 -----------------------------------------------------------
    def scores(self, style: str = "hiroba", recent: bool = False,
               player_id: str | None = None, server: str | None = None) -> dict:
        """style: hiroba | kinoko"""
        path = f"/scores/{style}" + ("/recent" if recent else "")
        return self._get(path, {"player_id": player_id, "server": server})

    def hiroba(self, player_id=None, server=None) -> dict:
        return self.scores("hiroba", player_id=player_id, server=server)

    def hiroba_recent(self, player_id=None, server=None) -> dict:
        return self.scores("hiroba", recent=True, player_id=player_id, server=server)

    def kinoko(self, player_id=None, server=None) -> dict:
        return self.scores("kinoko", player_id=player_id, server=server)

    def kinoko_recent(self, player_id=None, server=None) -> dict:
        return self.scores("kinoko", recent=True, player_id=player_id, server=server)
