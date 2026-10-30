"""The assistant has a dedicated owner; never accept arbitrary owners from LLMs."""

BOT_OWNER_ID = "__rtlink_ai__"
BOT_NAME = "可可子"


def query_owner(event, target):
    if target == "bot":
        return BOT_OWNER_ID
    if target != "caller":
        raise ValueError("target 仅支持 caller（当前发言者）或 bot（可可子自己）。")
    owner = str(event.get_sender_id() or "")
    if not owner or owner == BOT_OWNER_ID:
        raise ValueError("无法识别当前发言者。")
    return owner


BOT_UNBOUND = "可可子的当前数据源尚未绑定。请管理员在 AstrBot 插件管理页的「可可子账号」中设置 Token 和当前来源。"
