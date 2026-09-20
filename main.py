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
    from .dan_query import match_rank, match_region, query_dan_courses_text
    from .score_rank import empty_rolls, empty_score_rank, load_rolls, load_score_rank, parse_score_rank
    from .service import BindingsStore, ScoreService, parse_difficulty
    from .song_alias import empty_aliases, load_aliases
    from .storage import ScoreDatabase, load_charts, load_dan_courses
else:
    from api_client import KinokoClient
    from dan_query import match_rank, match_region, query_dan_courses_text
    from score_rank import empty_rolls, empty_score_rank, load_rolls, load_score_rank, parse_score_rank
    from service import BindingsStore, ScoreService, parse_difficulty
    from song_alias import empty_aliases, load_aliases
    from storage import ScoreDatabase, load_charts, load_dan_courses

PLUGIN_NAME = "rt_link"
PLUGIN_AUTHOR = "Rio"
PLUGIN_DESC = "将 QQ 绑定到菌菌控制台 apikey，查询太鼓达人成绩并评估玩家实力"
PLUGIN_VERSION = "v0.14.0"

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

        # 段位道场参考数据（静态资源；暂不参与 Rating 计算）。
        try:
            self.dan_courses = load_dan_courses(
                self.plugin_dir / "resource" / "dan_courses.v1.json.gz",
                self.charts,
            )
            logger.info(
                f"rt_link：已加载段位数据 {len(self.dan_courses['courses'])} 个课程，"
                f"关联 {len(self.dan_courses['by_song'])} 个曲目 ID"
            )
        except Exception as e:
            self.dan_courses = {"courses": [], "by_key": {}, "by_song": {}}
            logger.warning(f"rt_link：段位数据加载失败，段位参考功能不可用：{e}")

        self.db = ScoreDatabase(self.data_dir / "rt_link.db")

        # スコアランク（成绩评价）门槛：wiki 实测天井スコア / 極スコア；缺失曲目运行时按音符数估算。
        try:
            self.score_rank = load_score_rank(
                self.plugin_dir / "resource" / "score_rank.v1.json.gz",
                self.charts,
            )
            logger.info(
                f"rt_link：已加载评价门槛数据 {len(self.score_rank['songs'])} 个谱面"
                f"（版本 {self.score_rank['data_version']}）"
            )
        except Exception as e:
            self.score_rank = empty_score_rank()
            logger.warning(f"rt_link：评价门槛数据加载失败，评价提升分析将使用估算门槛：{e}")

        # 连打资料（黄色連打秒数 / 風船）：把「还差几打连打」换算成秒速与可行性。
        try:
            self.rolls = load_rolls(
                self.plugin_dir / "resource" / "rolls.v1.json.gz",
                self.charts,
            )
            with_rolls = sum(1 for item in self.rolls["songs"].values() if item["rolls"] > 0)
            logger.info(
                f"rt_link：已加载连打资料 {len(self.rolls['songs'])} 个谱面"
                f"（其中有黄条 {with_rolls} 张，版本 {self.rolls['data_version']}）"
            )
        except Exception as e:
            self.rolls = empty_rolls()
            logger.warning(f"rt_link：连打资料加载失败，连打路线只报「资料未知」：{e}")

        # 曲名别名索引（国服名 / 日文名 / 罗马字 / 常用别名）：段位查询与成绩检索共用。
        try:
            self.aliases = load_aliases(
                self.plugin_dir / "resource" / "aliases.v1.json.gz",
                self.charts,
            )
            logger.info(
                f"rt_link：已加载曲名别名 {len(self.aliases['songs'])} 个谱面"
                f"（{len(self.aliases['index'])} 种写法，版本 {self.aliases['data_version']}）"
            )
        except Exception as e:
            self.aliases = empty_aliases()
            logger.warning(f"rt_link：曲名别名加载失败，只按谱面库曲名匹配：{e}")

        self.service = ScoreService(
            store=KvBindingsStore(self),
            client_factory=self._make_client,
            charts=self.charts,
            score_db=self.db,
            score_rank=self.score_rank,
            rolls=self.rolls,
            aliases=self.aliases,
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
    # 命令入口
    #
    # AstrBot 的普通指令名不能包含空格；/rtlink score ... 中的 score
    # 会被解析成根指令的第一个参数。所有子指令因此统一由这个合法的
    # rtlink 根指令分发，同时保留裸 /rtlink 直接生成画像的行为。
    # ------------------------------------------------------------------
    @filter.command(COMMAND_NAME)
    async def rtlink(self, event: AstrMessageEvent, subcommand: str = ""):
        """太鼓成绩、Rating 画像与绑定管理；不带子指令时生成实力画像。"""
        rest = self._bare_rest(event.get_message_str()) or (subcommand or "").strip()
        if rest:
            async for result in self._dispatch_command(event, rest):
                yield result
            return
        ok, result = await self.service.generate_profile_image(event.get_sender_id())
        if not ok:
            yield event.plain_result(result)
            return
        yield event.image_result(result)

    async def _dispatch_command(self, event: AstrMessageEvent, rest: str):
        """分发 /rtlink <子指令> ...，保证未知或参数错误时也有明确回复。"""
        command = rest.split(None, 1)[0].lower()

        if command == "bind":
            parts = rest.split()
            if len(parts) not in (3, 4):
                yield event.plain_result(
                    "用法：/rtlink bind <apikey> <player_id> [server]"
                )
                return
            async for result in self.bind(event, *parts[1:]):
                yield result
            return

        handlers = {
            "help": self.help,
            "帮助": self.help,
            "unbind": self.unbind,
            "list": self.list_bindings,
            "score": self.score,
            "rating": self.rating_cmd,
            "update": self.update_cmd,
            "profile": self.profile_cmd,
            "progress": self.progress_cmd,
            "weakness": self.weakness_cmd,
            "improve": self.improve_cmd,
            "提升": self.improve_cmd,
            "dan": self.dan_cmd,
            "段位": self.dan_cmd,
            "storage": self.storage_cmd,
            "cleanup": self.cleanup_cmd,
            "alias": self.alias_cmd,
            "aliaslist": self.aliaslist_cmd,
            "aliasapprove": self.aliasapprove_cmd,
            "about": self.about,
        }
        handler = handlers.get(command)
        if handler is None:
            # 简写：`/rtlink 金雅`、`/rtlink 紫雅 鬼` 直接等价于 `/rtlink improve …`。
            target, level = self._parse_improve_args("improve " + rest)
            if target is not None or level is not None:
                async for result in self.improve_cmd(event, target, level):
                    yield result
                return
            yield event.plain_result(
                f"未知子指令：{command}。发送 /rtlink help 查看可用指令。"
            )
            return
        async for result in handler(event):
            yield result

    async def help(self, event: AstrMessageEvent):
        reminder = await self.service.score_sync_reminder_text(event.get_sender_id())
        if reminder:
            yield event.plain_result(reminder)
        ok, result = await self.service.generate_help_image(event.get_sender_id())
        if not ok:
            yield event.plain_result(result)
            return
        yield event.image_result(result)

    async def bind(self, event: AstrMessageEvent, apikey: str, player_id: str, server: str = ""):
        if not event.is_private_chat():
            yield event.plain_result("请在私聊中发送绑定命令，避免 apikey 泄露到群聊。")
            return
        ok, msg = await self.service.bind(event.get_sender_id(), apikey, player_id, server)
        yield event.plain_result(msg)

    async def unbind(self, event: AstrMessageEvent):
        ok, msg = await self.service.unbind(event.get_sender_id())
        yield event.plain_result(msg)

    async def list_bindings(self, event: AstrMessageEvent):
        if not event.is_admin():
            yield event.plain_result("无权限：仅管理员可查看全部绑定。")
            return
        warning = await self.service.low_space_warning_text()
        yield event.plain_result(warning + await self.service.list_bindings())

    async def score(self, event: AstrMessageEvent):
        song_name = self._parse_score_query(event.get_message_str())
        if not song_name:
            yield event.plain_result("用法：/rtlink score <曲名>")
            return
        yield event.plain_result(await self.service.query_score_text(event.get_sender_id(), song_name))

    async def rating_cmd(self, event: AstrMessageEvent):
        ok, result = await self.service.generate_report_image(event.get_sender_id())
        if not ok:
            yield event.plain_result(result)
            return
        yield event.image_result(result)

    async def profile_cmd(self, event: AstrMessageEvent):
        ok, result = await self.service.generate_profile_image(event.get_sender_id())
        if not ok:
            yield event.plain_result(result)
            return
        yield event.image_result(result)

    async def update_cmd(self, event: AstrMessageEvent):
        _ok, result = await self.service.force_update(event.get_sender_id())
        yield event.plain_result(result)

    async def progress_cmd(self, event: AstrMessageEvent):
        ok, result = await self.service.generate_configuration_image(event.get_sender_id())
        if not ok:
            yield event.plain_result(result)
            return
        yield event.image_result(result)

    async def weakness_cmd(self, event: AstrMessageEvent):
        ok, result = await self.service.generate_weakness_image(event.get_sender_id())
        if not ok:
            yield event.plain_result(result)
            return
        yield event.image_result(result)

    async def improve_cmd(self, event: AstrMessageEvent, target=None, level=None):
        """提升评价候选曲目：按分区列出离目标评价最近的谱面与判定/连打两条补分路线。

        作为子指令调用时参数从消息里解析；作为 `/rtlink <评价>` 简写调用时由分发层直接传入。
        """
        if target is None and level is None:
            target, level = self._parse_improve_args(event.get_message_str())
        ok, result = await self.service.generate_rank_improve_image(
            event.get_sender_id(), target, level
        )
        if not ok:
            yield event.plain_result(result)
            return
        yield event.image_result(result)

    async def dan_cmd(self, event: AstrMessageEvent):
        """段位道场课题曲查询：`/rtlink dan [年份] [区域] [段位] [曲名]`，参数顺序不限。

        曲名支持国服名、日文名、罗马字与常用别名；不带参数时列出可查询的年份与段位。
        """
        match = re.search(r"(?:dan|段位)\s+(.+)$", event.get_message_str() or "", re.IGNORECASE)
        args = self._parse_dan_args(match.group(1) if match else "")
        yield event.plain_result(
            query_dan_courses_text(
                self.dan_courses,
                alias_data=getattr(self, "aliases", None),
                **args,
            )
        )

    @staticmethod
    def _parse_dan_args(text: str) -> dict:
        """解析段位查询参数：年份、区域、段位、曲名，顺序不限。"""
        args = {"year": 0, "region": "", "rank": "", "song_name": ""}
        song_parts = []
        for token in re.split(r"[\s,，、]+", str(text or "").strip()):
            if not token:
                continue
            if re.fullmatch(r"20\d{2}", token) and not args["year"]:
                args["year"] = int(token)
                continue
            if not args["rank"]:
                rank = match_rank(token)
                if rank:
                    args["rank"] = rank
                    continue
            if not args["region"] and match_region(token):
                args["region"] = token
                continue
            song_parts.append(token)
        args["song_name"] = " ".join(song_parts).strip()
        return args

    async def storage_cmd(self, event: AstrMessageEvent):
        if not event.is_admin():
            yield event.plain_result("无权限：仅管理员可查看存储用量。")
            return
        yield event.plain_result(await self.service.storage_status_text())

    async def cleanup_cmd(self, event: AstrMessageEvent):
        if not event.is_admin():
            yield event.plain_result("无权限：仅管理员可回收空间。")
            return
        yield event.plain_result(await self.service.cleanup())

    async def alias_cmd(self, event: AstrMessageEvent):
        args = self._parse_alias_args(event.get_message_str())
        if not args:
            yield event.plain_result("用法：/rtlink alias <精准ID或曲名> <别名>")
            return
        target, alias = args
        yield event.plain_result(
            await self.service.request_alias(event.get_sender_id(), target, alias)
        )

    async def aliaslist_cmd(self, event: AstrMessageEvent):
        if not event.is_admin():
            yield event.plain_result("无权限：仅管理员可查看待审批别名。")
            return
        yield event.plain_result(await self.service.list_pending_aliases_text())

    async def aliasapprove_cmd(self, event: AstrMessageEvent):
        if not event.is_admin():
            yield event.plain_result("无权限：仅管理员可审批别名。")
            return
        args = self._parse_rest(event.get_message_str(), "aliasapprove")
        yield event.plain_result(await self.service.approve_aliases_text(args))

    async def about(self, event: AstrMessageEvent):
        yield event.plain_result(f"{PLUGIN_NAME} {PLUGIN_VERSION}\n{PLUGIN_DESC}")

    @staticmethod
    def _bare_rest(msg: str) -> str:
        """裸命令判定：返回 rtlink 之后的内容；空串表示裸 /rtlink。"""
        s = (msg or "").strip()
        if s.startswith("/"):
            s = s[1:].lstrip()
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
    def _parse_levels(text: str):
        """解析难度筛选，支持「鬼」「4,5」「鬼 里」「鬼里」等写法；返回 tuple 或 None。"""
        raw = (text or "").strip()
        if not raw:
            return None
        whole = parse_difficulty(raw)
        if whole in RATED_LEVELS:
            return (whole,)
        compact = re.sub(r"[\s+／/、,，]+", "", raw).lower()
        if compact in ("鬼里", "里鬼", "45", "54", "oniura", "uraoni", "maniaura", "uramania"):
            return (4, 5)
        levels = []
        for token in re.split(r"[\s,，、/／+]+", raw):
            if not token:
                continue
            level = parse_difficulty(token)
            if level in RATED_LEVELS and level not in levels:
                levels.append(level)
        return tuple(sorted(levels)) or None

    @staticmethod
    def _parse_improve_args(msg: str):
        """解析「improve [目标评价] [难度]」，顺序不限、均可省略。

        纯数字按「先目标评价、后难度」的顺序赋值：`improve 4` 指评价 4（金雅），
        `improve 金雅 5` 指评价金雅 + 里谱面。中文/日文评价名与难度名互不冲突。
        """
        m = re.search(r"(?:improve|提升)\s+(.+)$", msg or "", re.IGNORECASE)
        target = level = None
        if not m:
            return None, None
        for token in m.group(1).split():
            token = token.strip()
            if not token:
                continue
            if token.isdigit():
                number = int(token)
                if target is None and 1 <= number <= 8:
                    target = number
                elif level is None and number in RATED_LEVELS:
                    level = number
                continue
            rank = parse_score_rank(token)
            if rank is not None and target is None:
                target = rank
                continue
            difficulty = parse_difficulty(token)
            if difficulty in RATED_LEVELS and level is None:
                level = difficulty
        return target, level

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

    @filter.llm_tool(name="query_dan_course")
    async def query_dan_course(
        self,
        event: AstrMessageEvent,
        year: int = 0,
        region: str = "",
        rank: str = "",
        song_name: str = "",
        song_no: int = 0,
    ) -> str:
        """查询太鼓达人街机版段位道场课题曲、普通/金合格条件、开放时间与来源。

        用户询问某年段位内容、国服与日版差异、某首歌出现在哪届段位，或需要用段位曲目辅助判断水平时调用。
        若用户询问自己的过段能力，必须改用 evaluate_player_dan，不能只凭本工具的公开门槛进行判断。
        单曲成绩只能作为段位能力参考，不能据此断言玩家已通过段位。

        Args:
            year(int): 年份，可选 2022、2023、2024、2025、2026；0 表示不限
            region(string): 区域，可选 cn/国服/中国大陆 或 jp/日版/国际版；空表示不限
            rank(string): 段位，如 五级、初段、十段、玄人、达人；空表示不限
            song_name(string): 按课题曲名称反查段位，可省略。支持国服曲名、日文曲名、罗马字与常用别名
                （例如「北埼玉」「きたさいたま2000」「六天」「罗特」「顿卡马」），
                也可以写成「鬼 天竺2000」这样带难度前缀
            song_no(int): 按 RTLink 曲目 ID 反查段位，0 表示不用 ID 筛选
        """
        return query_dan_courses_text(
            self.dan_courses,
            year=year,
            region=region,
            rank=rank,
            song_name=song_name,
            song_no=song_no,
            alias_data=getattr(self, "aliases", None),
        )

    @filter.llm_tool(name="evaluate_player_dan")
    async def evaluate_player_dan(
        self,
        event: AstrMessageEvent,
        year: int,
        rank: str,
        region: str = "",
    ) -> str:
        """按玩家三首课题曲的实际良/可/不可/连打数据，核对指定段位的可计算合格条件。

        用户询问「我能不能过某段」「评价我的过段能力」「哪些课题曲条件没达到」时，
        应调用本工具，而不是只调用 query_dan_course。返回结果会明确区分可核对条件与
        无法由单曲成绩证明的魂槽、连续演奏条件。

        Args:
            year(int): 段位年份，可选 2022、2023、2024、2025、2026
            rank(string): 段位，如 五级、初段、十段、玄人、达人
            region(string): 区域，可选 cn/国服/中国大陆 或 jp/日版/国际版；省略时按玩家绑定服务器选择
        """
        return await self.service.get_player_dan_capability_text(
            event.get_sender_id(), self.dan_courses, year, region, rank
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
        self,
        event: AstrMessageEvent,
        query: str = "",
        match_mode: str = "contains",
        match_fields: str = "any",
        scope: str = "played",
        level: str = "",
        genre: str = "",
        song_no: int = 0,
        constant_min: float = 0.0,
        constant_max: float = -1.0,
        rating_min: float = 0.0,
        rating_max: float = -1.0,
        accuracy_min: float = 0.0,
        accuracy_max: float = -1.0,
        score_min: int = 0,
        score_max: int = -1,
        notes_min: int = 0,
        notes_max: int = -1,
        rank_min: int = 0,
        rank_max: int = -1,
        ok_min: int = 0,
        ok_max: int = -1,
        ng_min: int = 0,
        ng_max: int = -1,
        combo: str = "",
        target_rank: str = "",
        reached: str = "",
        gap_max: int = -1,
        sort: str = "rating",
        order: str = "desc",
        detail: str = "brief",
        limit: int = 20,
        offset: int = 0,
    ) -> str:
        """【通用检索】按任意条件组合检索成绩与谱面库，是回答各类成绩/曲目问题的首选工具。

        条件之间是「且」的关系，全部可省略、可自由组合；未提供的条件不参与筛选。
        用户问「有哪些…的歌」「我打得最好的定数 10 的歌」「哪些歌零不可」「哪些歌我没打过」
        「离金雅最近的歌」「日文名含 xx 的曲目」这类问题时都用本工具，一次查全。

        匹配方式：
        - match_mode：contains(包含，默认) / exact(精确相等) / regex(正则) / all(空格分词全部命中) / any(任一分词命中)
        - match_fields：any(曲名+日文名+分区+别名，默认) / title / titleJa / genre / alias
        - scope：played(只看已有成绩并已评级，默认) / unrated(打过但未参与评级) / unplayed(只看没打过的) / all(全部 1393 张谱面)

        数值条件的「不限」写法：下限用 0，上限用 -1 或直接省略；
        定数／Rating／精度／分数／音符数的上限传 0 也按「不限」处理。
        注意 ok_max=0 表示「一个『可』都没有」、ng_max=0 表示「零不可」、gap_max=0 表示「刚好达标」，
        这几个 0 是有效条件。

        Args:
            query(string): 关键词，可省略；支持空格分词与「鬼夏祭」这类难度前缀组合名
            match_mode(string): 匹配方式，见上。默认 contains
            match_fields(string): 匹配字段，见上。默认 any
            scope(string): played/unrated/unplayed/all，默认 played
            level(string): 难度，可省略。4/鬼/魔王、5/里/里魔王；多个用逗号，如「4,5」
            genre(string): 曲风分区关键词（如「ナムコ」「アニメ」「J-POP」），可省略
            song_no(int): 精确曲目 ID，0 表示不限
            constant_min(float): 最低定数，0 表示不限
            constant_max(float): 最高定数，0 或 -1 表示不限
            rating_min(float): 最低单谱 Rating，0 表示不限
            rating_max(float): 最高单谱 Rating，0 或 -1 表示不限
            accuracy_min(float): 最低精度，可用 0~1 或 0~100，0 表示不限
            accuracy_max(float): 最高精度，可用 0~1 或 0~100，0 或 -1 表示不限
            score_min(int): 最低分数，0 表示不限
            score_max(int): 最高分数，0 或 -1 表示不限
            notes_min(int): 最低音符数，0 表示不限
            notes_max(int): 最高音符数，0 或 -1 表示不限
            rank_min(int): 最低评价等级 1-8（1 无 / 2 白粹 / 3 铜粹 / 4 银粹 / 5 金雅 / 6 粉雅 / 7 紫雅 / 8 极），0 表示不限
            rank_max(int): 最高评价等级 1-8，-1 表示不限
            ok_min(int): 「可」数量下限，0 表示不限
            ok_max(int): 「可」数量上限，-1 表示不限；0 = 零「可」
            ng_min(int): 「不可」数量下限，0 表示不限
            ng_max(int): 「不可」数量上限，-1 表示不限；0 = 零「不可」
            combo(string): 连段条件，可省略。可选 full(已全连) / no-fc(未全连) / dondaful(已全良) / no-miss(零不可) / miss(有不可)
            target_rank(string): 目标评价，填了会给每条结果算出距该评价的门槛、缺口、所需良数与连打数
                                    （连打部分含：还差几打、总打数、要求秒速、是否打得出来；
                                    没有黄条的曲目会明确标出）
            reached(string): 是否已达 target_rank，可省略。no=只看还没达成的、yes=只看已达成的
            gap_max(int): 距 target_rank 门槛的最大分数缺口，-1 表示不限（用它筛「差一点就能升评价」；填了会自动排除已达成）
            sort(string): 排序字段：rating / score / accuracy / constant / notes / gap / rank / updated / title / id，默认 rating
            order(string): desc(默认) 或 asc
            detail(string): brief(默认，一行) 或 full(附良/可/不可/连打/全连/全良与更新时间)
            limit(int): 返回条数，默认 20，上限 200
            offset(int): 翻页偏移，默认 0
        """
        levels = self._parse_levels(level)
        filters = {
            "query": query or "",
            "match_mode": match_mode or "contains",
            "match_fields": match_fields or "any",
            "scope": scope or "played",
            "levels": levels,
            "genre": genre or "",
            "song_no": song_no or None,
            "constant_min": constant_min or None,
            "constant_max": constant_max if constant_max is not None and constant_max >= 0 else None,
            "rating_min": rating_min or None,
            "rating_max": rating_max if rating_max is not None and rating_max >= 0 else None,
            "accuracy_min": accuracy_min or None,
            "accuracy_max": accuracy_max if accuracy_max is not None and accuracy_max >= 0 else None,
            "score_min": score_min or None,
            "score_max": score_max if score_max is not None and score_max >= 0 else None,
            "notes_min": notes_min or None,
            "notes_max": notes_max if notes_max is not None and notes_max >= 0 else None,
            "rank_min": rank_min or None,
            "rank_max": rank_max if rank_max is not None and rank_max >= 1 else None,
            "ok_min": ok_min or None,
            "ok_max": ok_max if ok_max is not None and ok_max >= 0 else None,
            "ng_min": ng_min or None,
            "ng_max": ng_max if ng_max is not None and ng_max >= 0 else None,
            "combo": combo or "",
            "target_rank": parse_score_rank(target_rank) if target_rank else None,
            "reached": reached or "",
            "gap_max": gap_max if gap_max is not None and gap_max >= 0 else None,
            "sort": sort or "rating",
            "order": order or "desc",
            "limit": limit or 20,
            "offset": offset or 0,
        }
        return await self.service.query_scores_text(
            event.get_sender_id(), detail or "brief", **filters
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

    @filter.llm_tool(name="find_rank_improvements")
    async def find_rank_improvements(
        self, event: AstrMessageEvent, target_rank: str = "", level: str = ""
    ) -> str:
        """查询「还差一点就能提升成绩评价」的曲目，按曲风分区列出所需分数、良数与连打打数/秒速。

        用户询问「怎么提高评价」「哪些歌能升评价」「我离金雅还差多少」「刷评价推荐哪些歌」
        「怎么把紫雅变成极」时调用本工具。

        评价门槛：スコア = 良×基本点 + 可×⌊基本点/2⌋ + 黄色連打×100，
        基本点 = 天井スコア ÷ 总音符数。
        评价门槛 = **该谱極スコア × 50/60/70/80/90/95/100%**：
        白粹 50% / 铜粹 60% / 银粹 70% / 金雅 80% / 粉雅 90% / 紫雅 95% / 极 100%
        （極スコア ≈ 100 万，所以数值上接近 50/60/70/80/90/95/100 万，但各曲有 ±1% 浮动）。

        两条路线：
        - 判定路线：把「可」/「不可」打成「良」；若必须把全部「可」「不可」都转成良，
          结果里会写「走判定就得全良」。
        - 连打路线：黄条每打固定 100 分。结果会给出还差几打、补完这局一共几打、
          以及对应秒速（= 黄色連打打数 ÷ 合计黄色連打秒数，风船连打不计入）。
          没有黄条的曲目会明确写「本曲没有黄条」，连打补不满（超过該谱連打理論値）的
          也会写「已超上限」，这时只能靠判定提升。若连全良＋黄条打满都够不到门槛，
          会直接写「本曲上限约 X，达不到门槛」。

        Args:
            target_rank(string): 目标评价，省略时取玩家最常拿到的评价的上一档。可选：白粹、铜粹、银粹、金雅、粉雅、紫雅、极，或 2-8
            level(string): 难度筛选，省略表示鬼/里都看。可选：4/鬼/魔王、5/里/里魔王
        """
        return await self.service.get_rank_improvement_text(
            event.get_sender_id(),
            parse_score_rank(target_rank) if target_rank else None,
            parse_difficulty(level) if level else None,
        )

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
