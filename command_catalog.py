"""QQ 子指令的分发、用法及帮助文本。"""

from dataclasses import dataclass

COMMAND_NAME = "rtlink"
BIND_SAKURA_USAGE = "/rtlink bind sakura <token>"
IMPROVE_SHORT_USAGE = "/rtlink <评价> [难度]"
LIBRARY_RETRY_USAGE = "/rtlink library retry"


@dataclass(frozen=True)
class Command:
    name: str
    handler: str
    usage: str
    description: str
    aliases: tuple[str, ...] = ()
    accepts_args: bool = False
    admin_only: bool = False


COMMANDS = (
    Command("bind", "bind_cmd", "/rtlink bind <apikey> <player_id> [server]",
            "在 QQ 私聊绑定菌菌账号", accepts_args=True),
    Command("source", "source_cmd", "/rtlink source [kinoko|sakura]",
            "查看当前来源，或切换到已绑定的来源", accepts_args=True),
    Command("unbind", "unbind", "/rtlink unbind", "解绑当前来源，保留历史成绩"),
    Command("update", "update_cmd", "/rtlink update", "立即同步当前来源的成绩"),
    Command("score", "score", "/rtlink score <曲名或ID>",
            "查单曲成绩，支持别名和难度前缀", accepts_args=True),
    Command("profile", "profile_cmd", "/rtlink profile", "使用有效缓存查看个人画像、BEST 20 和提升建议"),
    Command("rating", "rating_cmd", "/rtlink rating", "查看 Rating、七维能力、强弱项和冷门配置"),
    Command("progress", "progress_cmd", "/rtlink progress", "查看配置评分、理论满分、样本和历史"),
    Command("weakness", "weakness_cmd", "/rtlink weakness", "查看节奏型弱项及练习建议"),
    Command("improve", "improve_cmd", "/rtlink improve [评价] [难度]",
            "按分区查看升评价的判定和连打路线", ("提升",), accepts_args=True),
    Command("dan", "dan_cmd", "/rtlink dan [年份] [区域] [段位] [曲名]",
            "查段位课题曲及合格条件，也可由曲名反查", ("段位",), accepts_args=True),
    Command("library", "library_cmd", "/rtlink library", "查看公共谱面分析库的安装状态", accepts_args=True),
    Command("alias", "alias_cmd", "/rtlink alias <曲名或ID> <别名>",
            "申请歌曲别名，含空格的曲名加引号", accepts_args=True),
    Command("help", "help", "/rtlink help", "查看指令、绑定与评级说明", ("帮助",)),
    Command("about", "about", "/rtlink about", "查看插件版本与简介"),
    Command("list", "list_bindings", "/rtlink list", "查看全部绑定", admin_only=True),
    Command("storage", "storage_cmd", "/rtlink storage", "查看存储用量", admin_only=True),
    Command("cleanup", "cleanup_cmd", "/rtlink cleanup", "回收数据库空页", admin_only=True),
    Command("aliaslist", "aliaslist_cmd", "/rtlink aliaslist", "查看待审批别名", admin_only=True),
    Command("aliasapprove", "aliasapprove_cmd", "/rtlink aliasapprove all|<编号...>",
            "批量通过别名申请", accepts_args=True, admin_only=True),
)

COMMAND_BY_NAME = {
    name: command for command in COMMANDS for name in (command.name, *command.aliases)
}


def user_command_rows() -> list[tuple[str, str]]:
    rows = [(f"/{COMMAND_NAME}", "立即同步并生成个人画像")]
    for command in COMMANDS:
        if command.admin_only:
            continue
        description = command.description
        if command.aliases:
            aliases = "、".join(f"「{alias}」" for alias in command.aliases)
            description += f" · 也可用 {aliases}"
        rows.append((command.usage, description))
        if command.name == "bind":
            rows.append((BIND_SAKURA_USAGE, "在 QQ 私聊绑定 Sakura 账号"))
        if command.name == "improve":
            rows.append((IMPROVE_SHORT_USAGE, "提升评价的简写，例如 /rtlink 金雅 鬼"))
    return rows
