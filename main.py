# -*- coding: utf-8 -*-
"""
rt_link 插件：将 QQ 号绑定到「菌菌控制台」apikey，查询太鼓达人成绩并评估玩家实力。

- 主 Rating：AI v2（Taiko Signal Rhythm v2），参考 OurTaiko-v1 公式（rating.py）
- 本地存储：SQLite（storage.py），菌菌 hiroba/kinoko 同步数据转义后落库
- 空间监管：/rtlink storage（管理员）查询用量，接近配额自动提醒
- 交互：命令（/rtlink ...）+ LLM 工具（模型可自动调用）
"""

import re
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, StarTools, register

# AstrBot 以包形式加载插件（如 data.plugins.<name>.main），此时需用相对导入；
# 本地直接运行/测试 main.py 时（__package__ 为空），回退到同目录绝对导入。
if __package__:
    from .api_client import KinokoClient
    from .service import BindingsStore, ScoreService, parse_difficulty
    from .storage import ScoreDatabase, load_charts
else:
    from api_client import KinokoClient
    from service import BindingsStore, ScoreService, parse_difficulty
    from storage import ScoreDatabase, load_charts

PLUGIN_NAME = "rt_link"
PLUGIN_AUTHOR = "Rio"
PLUGIN_DESC = "将 QQ 绑定到菌菌控制台 apikey，查询太鼓达人成绩并评估玩家实力"
PLUGIN_VERSION = "v0.3.0"

COMMAND_NAME = "rtlink"
BINDINGS_KEY = "bindings"

# 本评分系统只评估鬼/里（魔王/里魔王）；1–3 难度无谱面定数，不参与评级。
RATED_LEVELS = (4, 5)


class KvBindingsStore(BindingsStore):
    """基于 AstrBot PluginKVStore 的绑定存储。"""

    def __init__(self, star: "RTLinkPlugin"):
        self._star = star

    async def load(self) -> dict:
        data = await self._star.get_kv_data(BINDINGS_KEY, {})
        return data if isinstance(data, dict) else {}

    async def save(self, data: dict) -> None:
        await self._star.put_kv_data(BINDINGS_KEY, data)


@register(PLUGIN_NAME, PLUGIN_AUTHOR, PLUGIN_DESC, PLUGIN_VERSION)
class RTLinkPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.cfg = self.context.get_config() or {}
        self.plugin_dir = Path(__file__).resolve().parent

        # 数据目录：优先 AstrBot 提供的持久化目录，本地测试回退到插件目录下 data/。
        try:
            self.data_dir = Path(StarTools.get_data_dir("astrbot_plugin_rt_link"))
        except Exception:
            self.data_dir = self.plugin_dir / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 谱面元数据（静态，打包在 resource/charts.v1.json.gz）
        try:
            self.charts = load_charts(self.plugin_dir / "resource" / "charts.v1.json.gz")
            logger.info(f"rt_link：已加载谱面数据 {len(self.charts)} 张")
        except Exception as e:
            self.charts = {}
            logger.warning(f"rt_link：谱面数据加载失败，评级功能不可用：{e}")

        self.db = ScoreDatabase(self.data_dir / "rt_link.db")

        self.service = ScoreService(
            store=KvBindingsStore(self),
            client_factory=self._make_client,
            charts=self.charts,
            score_db=self.db,
            default_server=self.cfg.get("default_server") or "cn",
            sync_ttl=int(self.cfg.get("sync_ttl", 300) or 300),
            quota_mb=int(self.cfg.get("storage_quota_mb", 256) or 256),
            warn_ratio=float(self.cfg.get("storage_warn_ratio", 0.8) or 0.8),
            report_dir=str(self.data_dir),
            logger=logger,
        )

    def _make_client(self, apikey: str) -> KinokoClient:
        return KinokoClient(
            apikey,
            base_url=self.cfg.get("base_url") or None,
            timeout=int(self.cfg.get("request_timeout", 30) or 30),
        )

    async def terminate(self):
        try:
            self.db.close()
        except Exception:
            pass
        logger.info("rt_link 插件已卸载")

    # ------------------------------------------------------------------
    # 命令（扁平化注册，避免裸 /rtlink 触发指令组「参数不足」提示）
    # ------------------------------------------------------------------
    @filter.command(COMMAND_NAME)
    async def rtlink(self, event: AstrMessageEvent):
        """裸 /rtlink：默认返回实力画像图片。"""
        if self._bare_rest(event.get_message_str()):
            return  # 带子命令，交给对应子命令处理
        ok, result = await self.service.generate_report_image(event.get_sender_id())
        if not ok:
            yield event.plain_result(result)
            return
        yield event.image_result(result)

    @filter.command(f"{COMMAND_NAME} help")
    async def help(self, event: AstrMessageEvent):
        yield event.plain_result(
            "rtlink 命令：\n"
            "/rtlink bind <apikey> <player_id> [server]  绑定当前 QQ\n"
            "/rtlink unbind                             解绑当前 QQ\n"
            "/rtlink score <曲名>                       查询指定曲目成绩（可加难度前缀如「鬼夏祭」）\n"
            "/rtlink rating                             生成实力画像图片\n"
            "/rtlink profile                            查看我的强项/弱项画像\n"
            "/rtlink weakness                           查看节奏型弱项与参考曲目\n"
            "/rtlink alias <ID或曲名> <别名>             申请歌曲别名（待审核）\n"
            "/rtlink help                               查看帮助\n"
            "/rtlink about                              查看插件信息\n"
            "也可以直接用自然语言问我，例如「我的实力怎么样」「我该练什么」\n"
            "注意：apikey 仅用于服务端绑定与查询，不会发送给大模型；请在私聊中绑定。"
        )

    @filter.command(f"{COMMAND_NAME} bind")
    async def bind(self, event: AstrMessageEvent, apikey: str, player_id: str, server: str = ""):
        if not event.is_private_chat():
            yield event.plain_result("请在私聊中发送绑定命令，避免 apikey 泄露到群聊。")
            return
        ok, msg = await self.service.bind(event.get_sender_id(), apikey, player_id, server)
        yield event.plain_result(msg)

    @filter.command(f"{COMMAND_NAME} unbind")
    async def unbind(self, event: AstrMessageEvent):
        ok, msg = await self.service.unbind(event.get_sender_id())
        yield event.plain_result(msg)

    @filter.command(f"{COMMAND_NAME} list")
    async def list_bindings(self, event: AstrMessageEvent):
        if not event.is_admin():
            yield event.plain_result("无权限：仅管理员可查看全部绑定。")
            return
        warning = await self.service.low_space_warning_text()
        yield event.plain_result(warning + await self.service.list_bindings())

    @filter.command(f"{COMMAND_NAME} score")
    async def score(self, event: AstrMessageEvent):
        song_name = self._parse_score_query(event.get_message_str())
        if not song_name:
            yield event.plain_result("用法：/rtlink score <曲名>")
            return
        yield event.plain_result(await self.service.query_score_text(event.get_sender_id(), song_name))

    @filter.command(f"{COMMAND_NAME} rating")
    async def rating_cmd(self, event: AstrMessageEvent):
        ok, result = await self.service.generate_report_image(event.get_sender_id())
        if not ok:
            yield event.plain_result(result)
            return
        yield event.image_result(result)

    @filter.command(f"{COMMAND_NAME} profile")
    async def profile_cmd(self, event: AstrMessageEvent):
        yield event.plain_result(await self.service.get_profile_text(event.get_sender_id()))

    @filter.command(f"{COMMAND_NAME} weakness")
    async def weakness_cmd(self, event: AstrMessageEvent):
        yield event.plain_result(await self.service.get_rhythm_weakness_text(event.get_sender_id()))

    @filter.command(f"{COMMAND_NAME} storage")
    async def storage_cmd(self, event: AstrMessageEvent):
        if not event.is_admin():
            yield event.plain_result("无权限：仅管理员可查看存储用量。")
            return
        yield event.plain_result(await self.service.storage_status_text())

    @filter.command(f"{COMMAND_NAME} cleanup")
    async def cleanup_cmd(self, event: AstrMessageEvent):
        if not event.is_admin():
            yield event.plain_result("无权限：仅管理员可回收空间。")
            return
        yield event.plain_result(await self.service.cleanup())

    @filter.command(f"{COMMAND_NAME} alias")
    async def alias_cmd(self, event: AstrMessageEvent):
        args = self._parse_alias_args(event.get_message_str())
        if not args:
            yield event.plain_result("用法：/rtlink alias <精准ID或曲名> <别名>")
            return
        target, alias = args
        yield event.plain_result(
            await self.service.request_alias(event.get_sender_id(), target, alias)
        )

    @filter.command(f"{COMMAND_NAME} aliaslist")
    async def aliaslist_cmd(self, event: AstrMessageEvent):
        if not event.is_admin():
            yield event.plain_result("无权限：仅管理员可查看待审批别名。")
            return
        yield event.plain_result(await self.service.list_pending_aliases_text())

    @filter.command(f"{COMMAND_NAME} aliasapprove")
    async def aliasapprove_cmd(self, event: AstrMessageEvent):
        if not event.is_admin():
            yield event.plain_result("无权限：仅管理员可审批别名。")
            return
        args = self._parse_rest(event.get_message_str(), "aliasapprove")
        yield event.plain_result(await self.service.approve_aliases_text(args))

    @filter.command(f"{COMMAND_NAME} about")
    async def about(self, event: AstrMessageEvent):
        yield event.plain_result(f"{PLUGIN_NAME} v{PLUGIN_VERSION}\n{PLUGIN_DESC}")

    @staticmethod
    def _bare_rest(msg: str) -> str:
        """裸命令判定：返回 rtlink 之后的内容；空串表示裸 /rtlink。"""
        s = (msg or "").strip()
        if s == COMMAND_NAME:
            return ""
        if s.startswith(COMMAND_NAME + " "):
            return s[len(COMMAND_NAME) + 1:].strip()
        return s

    @staticmethod
    def _parse_score_query(msg: str) -> str:
        m = re.search(r"score\s+(.+)$", msg or "", re.IGNORECASE)
        return m.group(1).strip() if m else ""

    @staticmethod
    def _parse_alias_args(msg: str):
        """解析「alias <target> <别名>」，别名可含空格；返回 (target, alias) 或 None。"""
        m = re.search(r"alias\s+(.+)$", msg or "", re.IGNORECASE)
        if not m:
            return None
        parts = m.group(1).strip().split(None, 1)
        if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
            return None
        return parts[0].strip(), parts[1].strip()

    @staticmethod
    def _parse_rest(msg: str, command: str) -> str:
        m = re.search(re.escape(command) + r"\s+(.+)$", msg or "", re.IGNORECASE)
        return m.group(1).strip() if m else ""

    @staticmethod
    def _level_arg(level: int) -> int | None:
        return level if level in RATED_LEVELS else (None if level == 0 else level)

    # ------------------------------------------------------------------
    # LLM 工具：允许模型在对话中直接调用（安全约定：只返回成绩/画像文本，绝不返回 apikey）
    # ------------------------------------------------------------------
    @filter.llm_tool(name="query_taiko_score")
    async def query_taiko_score(self, event: AstrMessageEvent, song_name: str, level: str = "") -> str:
        """查询当前 QQ 用户绑定账号中，指定歌曲的成绩与 Rating。支持别名与「鬼夏祭」这类难度前缀组合名。

        Args:
            song_name(string): 歌曲名称或别名，支持中文/日文/英文模糊匹配；可加难度前缀如「鬼夏祭」「里夏祭」
            level(string): 难度筛选，可省略。可选：4/鬼/魔王、5/里/里魔王、3/松/困难、2/竹/一般、1/梅/简单
        """
        return await self.service.query_score_text(
            event.get_sender_id(), song_name, parse_difficulty(level) if level else None
        )

    @filter.llm_tool(name="get_player_rating")
    async def get_player_rating(self, event: AstrMessageEvent) -> str:
        """查询当前 QQ 用户的综合 Rating 与七维能力（谱面底力/持续耐力/爆发手速/击打精度/配置处理/节奏适应/读谱）。

        说明：本 Rating 仅评估鬼/里（魔王/里魔王）谱面，1-3 难度不参与评级。
        返回文本含「覆盖谱面」分布，可作为判断玩家水平（新手/老手）的语境锚点。
        """
        return await self.service.get_rating_text(event.get_sender_id())

    @filter.llm_tool(name="get_player_profile")
    async def get_player_profile(self, event: AstrMessageEvent) -> str:
        """查询当前 QQ 用户的实力画像：综合 Rating、七维能力、强项与弱项、全连/咚大福数量。

        用于回答「这个玩家什么水平、擅长什么、短板在哪」。
        """
        return await self.service.get_profile_text(event.get_sender_id())

    @filter.llm_tool(name="get_rhythm_weakness")
    async def get_rhythm_weakness(self, event: AstrMessageEvent) -> str:
        """查询当前 QQ 用户在具体节奏型上的弱项，并给出参考曲目（用于回答「该练什么」）。

        按「节奏型 × BPM 档」给出处理 Rating 最低的几项，每项附带参考曲目。
        """
        return await self.service.get_rhythm_weakness_text(event.get_sender_id())

    @filter.llm_tool(name="get_difficulty_stats")
    async def get_difficulty_stats(self, event: AstrMessageEvent, level: int = 0) -> str:
        """查询指定难度的曲目数、全连率、咚大福数、平均 Rating、最高定数。

        Args:
            level(int): 难度等级。4=鬼（魔王），5=里鬼（里魔王）；0 或省略=鬼/里合计。1-3 难度不参与评级。
        """
        return await self.service.get_difficulty_stats_text(event.get_sender_id(), self._level_arg(level))

    @filter.llm_tool(name="get_rank_distribution")
    async def get_rank_distribution(self, event: AstrMessageEvent, level: int = 0) -> str:
        """查询当前 QQ 用户评价等级的分布（评价越高代表段位越高），含各档代表曲目。

        Args:
            level(int): 4=鬼，5=里鬼；0 或省略=鬼/里合计。
        """
        return await self.service.get_rank_distribution_text(event.get_sender_id(), self._level_arg(level))

    @filter.llm_tool(name="get_genre_strength")
    async def get_genre_strength(self, event: AstrMessageEvent) -> str:
        """查询当前 QQ 用户各曲风分区（J-POP/アニメ/ナムコオリジナル等）的平均 Rating 与全连数，识别擅长曲风。"""
        return await self.service.get_genre_strength_text(event.get_sender_id())

    @filter.llm_tool(name="get_accuracy_summary")
    async def get_accuracy_summary(self, event: AstrMessageEvent, level: int = 0) -> str:
        """查询当前 QQ 用户的精度概况：平均精度、精度区间、精度最高/最低的曲目。

        Args:
            level(int): 4=鬼，5=里鬼；0 或省略=鬼/里合计。
        """
        return await self.service.get_accuracy_summary_text(event.get_sender_id(), self._level_arg(level))

    @filter.llm_tool(name="search_scores")
    async def search_scores(
        self, event: AstrMessageEvent, query: str = "", level: str = "",
        constant_min: float = 0.0, constant_max: float = 0.0, rank_min: int = 0,
    ) -> str:
        """按条件检索成绩：曲名/别名模糊匹配、难度、定数范围、评价下限。

        Args:
            query(string): 曲名关键词或别名，可省略；可加难度前缀如「鬼夏祭」
            level(string): 难度筛选，可省略。可选：4/鬼/魔王、5/里/里魔王、3/松/困难、2/竹/一般、1/梅/简单
            constant_min(float): 最低定数，0 表示不限
            constant_max(float): 最高定数，0 表示不限
            rank_min(int): 最低评价等级，0 表示不限
        """
        return await self.service.search_scores_text(
            event.get_sender_id(),
            query=query or None,
            level=parse_difficulty(level) if level else None,
            constant_min=constant_min or None,
            constant_max=constant_max or None,
            rank_min=rank_min or None,
        )

    @filter.llm_tool(name="get_song_full")
    async def get_song_full(self, event: AstrMessageEvent, song_name: str) -> str:
        """查询指定歌曲的鬼/里全部难度成绩、定数、Rating 与七维能力。

        Args:
            song_name(string): 歌曲名称，支持中文/日文/英文模糊匹配
        """
        return await self.service.get_song_full_text(event.get_sender_id(), song_name)

    @filter.llm_tool(name="get_recent_scores")
    async def get_recent_scores(self, event: AstrMessageEvent, days: int = 1) -> str:
        """查询当前 QQ 用户最近游玩/更新的成绩（按更新时间排序）。

        Args:
            days(int): 最近天数，默认 1
        """
        return await self.service.get_recent_scores_text(event.get_sender_id(), days)

    @filter.llm_tool(name="get_growth_trend")
    async def get_growth_trend(self, event: AstrMessageEvent, song_name: str = "") -> str:
        """查询指定歌曲（省略则取 Rating 最高的曲目）的分数/精度/评价随时间的变化。

        Args:
            song_name(string): 歌曲名称，可省略
        """
        return await self.service.get_growth_trend_text(event.get_sender_id(), song_name or None)

    @filter.llm_tool(name="get_improvement_candidates")
    async def get_improvement_candidates(self, event: AstrMessageEvent, level: int = 0) -> str:
        """查询「差一点全连/差一点咚大福」的谱面清单，用于给玩家提升建议。

        Args:
            level(int): 4=鬼，5=里鬼；0 或省略=鬼/里合计。
        """
        return await self.service.get_improvement_candidates_text(event.get_sender_id(), self._level_arg(level))

    @filter.llm_tool(name="set_song_alias")
    async def set_song_alias(self, event: AstrMessageEvent, song: str, alias: str) -> str:
        """为指定歌曲设置别名（需管理员审核通过后生效）。设置前会返回歌曲 ID/名称等信息供确认。

        Args:
            song(string): 歌曲的精准 ID 或曲名（曲名建议用全名，避免多首匹配）
            alias(string): 要设置的别名
        """
        return await self.service.request_alias(event.get_sender_id(), song, alias)

    @filter.llm_tool(name="generate_rating_image")
    async def generate_rating_image(self, event: AstrMessageEvent):
        """生成当前 QQ 用户的鼓点画像评价图片（Rating 环 + 七维能力 + 强弱项 + 表现证据），并直接发送给用户。

        当用户想看「实力画像 / 评级报告 / 能力图 / 我的评价」时调用此工具。
        """
        ok, result = await self.service.generate_report_image(event.get_sender_id())
        if not ok:
            yield event.plain_result(result)
            return
        yield event.image_result(result)
