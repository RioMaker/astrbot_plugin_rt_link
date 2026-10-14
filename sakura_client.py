"""Sakura 只读成绩接口；凭据只放入固定 HTTPS 地址的 POST 请求体。"""

import json
import re
import ssl
import urllib.error
import urllib.request

if __package__:
    from .api_client import KinokoAPIError
else:
    from api_client import KinokoAPIError


class SakuraAPIError(KinokoAPIError):
    """使用固定错误文案，不回显远端响应或凭据。"""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def normalize_sakura(payload, expected_player_id=None):
    """转为既有评级输入，原始 userdata 随响应保留供独立落库。"""
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise SakuraAPIError("Sakura 返回了无效的成功响应。")
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("profile"), dict):
        raise SakuraAPIError("Sakura 响应缺少玩家资料。")
    player_id = payload.get("taikoId")
    profile_id = data["profile"].get("userid")
    if not isinstance(player_id, (str, int)) or not str(player_id):
        raise SakuraAPIError("Sakura 响应缺少玩家编号。")
    player_id = str(player_id)
    if str(profile_id) != player_id or (expected_player_id is not None and str(expected_player_id) != player_id):
        raise SakuraAPIError("Sakura token 对应的玩家已改变，请重新绑定。")
    songs = data.get("songs")
    if not isinstance(songs, list) or any(not isinstance(row, dict) for row in songs):
        raise SakuraAPIError("Sakura 成绩数组格式错误。")
    # 不为未知服务器伪造 cn；当前已验证的 wahlap 数据明确属于国服。
    metadata = data.get("_meta") or {}
    if not isinstance(metadata, dict):
        raise SakuraAPIError("Sakura 来源信息格式错误。")
    upstream = metadata.get("source")
    server = "cn" if upstream == "wahlap" else "unknown"
    for row in songs:
        if not isinstance(row.get("song_no"), int) or row["song_no"] <= 0 or row.get("level") not in (1, 2, 3, 4, 5):
            raise SakuraAPIError("Sakura 谱面编号或难度无效。")
        for key in ("good_cnt", "ok_cnt", "ng_cnt", "high_score", "pound_cnt", "combo_cnt", "stage_cnt", "clear_cnt", "full_combo_cnt", "dondaful_combo_cnt", "best_score_rank"):
            value = row.get(key)
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
                raise SakuraAPIError("Sakura 成绩数值格式错误。")
    return {"data": {"playedRecords": {"userid": player_id, "server": server, "scoreInfo": songs}}, "sakura_userdata": payload}


class SakuraClient:
    ENDPOINT = "https://sakura-bot.cn/api/public-score/by-token"

    def __init__(self, token, timeout=30):
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9]{48}", token):
            raise SakuraAPIError("Sakura token 应为 48 位字母或数字。")
        self._token = token
        self.timeout = timeout

    def fetch(self):
        request = urllib.request.Request(
            self.ENDPOINT,
            data=json.dumps({"token": self._token}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        opener = urllib.request.build_opener(
            _NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context())
        )
        try:
            with opener.open(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            normalize_sakura(payload)
            return payload
        except urllib.error.HTTPError as error:
            messages = {400: "请求格式不合法", 401: "token 无效、已轮换或已撤销", 404: "绑定或本地成绩不存在", 429: "请求过于频繁，请稍后重试", 502: "上游成绩拉取失败"}
            raise SakuraAPIError(f"Sakura HTTP {error.code}：{messages.get(error.code, '请求失败')}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise SakuraAPIError("Sakura 网络请求失败或超时，请稍后重试。") from None
        except (ValueError, TypeError):
            raise SakuraAPIError("Sakura 响应格式错误。") from None
