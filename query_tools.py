"""Bounded, declarative read-query recipes owned by the plugin configuration.

Recipes are data, never Python, SQL, URLs or model instructions. Their leaves
always resolve to the existing immutable query gateway allowlist.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from collections import Counter

if __package__:
    from . import query_gateway as gateway
else:
    import query_gateway as gateway

CONFIG_KEY = "query_agent_custom_tools"
MAX_DEFINITION_CHARS = 12000
MAX_CATALOG_CHARS = 64000
TOOL_NAME = re.compile(r"custom_[a-z0-9_]{1,93}\Z")
PARAM_NAME = re.compile(r"[a-z][a-z0-9_]{0,31}\Z")
FIELDS = {"name", "description", "note", "parameters", "queries"}


class ToolError(ValueError):
    """A stable, non-sensitive error suitable for the child agent's feedback."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _error(code, message):
    raise ToolError(code, message)


def _text(value, maximum, label, *, empty=False):
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or (not empty and not value.strip())
        or any(ord(char) < 32 and char != "\n" for char in value)
    ):
        _error("invalid_definition", f"{label}类型或长度无效。")
    return value.strip()


def _copy(value):
    try:
        return json.loads(gateway.dumps(value))
    except (TypeError, ValueError, RecursionError):
        _error("invalid_definition", "工具定义必须是有限大小的有效 JSON 数据。")


def _limits(per_session=None, total_limit=20):
    if type(total_limit) is not int or not 1 <= total_limit <= 100:
        _error("invalid_limits", "自定义工具总量上限必须为 1–100。")
    if per_session is not None and (
        type(per_session) is not int or not 1 <= per_session <= 3
    ):
        _error("invalid_limits", "单次会话工具变更上限必须为 1–3。")


def _base_arguments(item):
    # Import lazily: use exactly the same parsers as ScoreService's gateway.
    if __package__:
        from .score_rank import parse_score_rank
        from .service import parse_difficulty
    else:
        from score_rank import parse_score_rank
        from service import parse_difficulty
    try:
        gateway.item_arguments(item, parse_difficulty, parse_score_rank)
    except (TypeError, ValueError, KeyError, OverflowError):
        _error("invalid_query", "基础查询名称、参数类型或取值无效。")


def _arg_types(key):
    if key in gateway.INTEGER_ARGS:
        return {"integer"}
    if key in gateway.NUMBER_ARGS:
        return {"integer", "number"}
    if key in ("level", "target_rank"):
        return {"integer", "string"}
    return {"string"}


def _sample(key, kind):
    # Only placeholders are substituted for definition-time validation. Actual
    # calls run through the same validation again with real values.
    special = {
        "year": 2024,
        "level": 4,
        "target_rank": 2,
        "scope": "played",
        "match_mode": "contains",
        "match_fields": "any",
        "combo": "full",
        "reached": "yes",
        "order": "asc",
        "detail": "brief",
    }
    value = special.get(key, 1 if kind != "string" else "sample")
    return str(value) if kind == "string" else value


def _validate_definition(raw):
    if not isinstance(raw, dict) or set(raw) != FIELDS:
        _error(
            "invalid_definition",
            "工具仅允许 name、description、note、parameters、queries。",
        )
    value = _copy(raw)
    if len(gateway.dumps(value)) > MAX_DEFINITION_CHARS:
        _error("invalid_definition", "单个工具定义不能超过 12000 字符。")
    name = _text(value["name"], 100, "工具名")
    if not TOOL_NAME.fullmatch(name) or name in gateway.OPERATIONS:
        _error("immutable_base", "自定义工具名须以 custom_ 开头，不能覆盖基础工具。")
    value["name"] = name
    value["description"] = _text(value["description"], 300, "工具描述")
    value["note"] = _text(value["note"], 300, "工具注释", empty=True)
    parameters = value["parameters"]
    if not isinstance(parameters, dict) or len(parameters) > 12:
        _error("invalid_definition", "parameters 必须是至多 12 项的参数对象。")
    for name, schema in parameters.items():
        if (
            not PARAM_NAME.fullmatch(name)
            or not isinstance(schema, dict)
            or set(schema) != {"type", "description"}
            or schema["type"] not in ("string", "integer", "number")
        ):
            _error("invalid_definition", "参数须声明有效名称、type 和 description。")
        schema["description"] = _text(schema["description"], 160, "参数描述")
    queries = value["queries"]
    if not isinstance(queries, list) or not 2 <= len(queries) <= gateway.MAX_QUERIES:
        _error(
            "unnecessary_tool",
            "自定义工具必须组合 2–24 项查询；单项查询请直接用基础工具。",
        )
    used, seen = set(), set()
    for item in queries:
        if (
            not isinstance(item, dict)
            or set(item) - {"tool", "args"}
            or not isinstance(item.get("tool"), str)
            or item["tool"] not in gateway.OPERATIONS
            or not isinstance(item.get("args", {}), dict)
        ):
            _error(
                "immutable_base",
                "配方只能调用现有基础只读函数，不能递归调用自定义工具。",
            )
        args = item.setdefault("args", {})
        _, required, optional = gateway.OPERATIONS[item["tool"]]
        if set(args) - set(required) - set(optional) or set(required) - set(args):
            _error("invalid_definition", "配方包含不支持的参数或缺少必要参数。")
        sampled = {}
        for key, arg in args.items():
            if isinstance(arg, dict):
                if set(arg) != {"param"} or not isinstance(arg["param"], str):
                    _error("invalid_definition", "参数占位符只能使用 {param: 参数名}。")
                ref = arg["param"]
                if ref not in parameters or parameters[ref]["type"] not in _arg_types(
                    key
                ):
                    _error("invalid_definition", "占位符未声明或类型与基础参数不匹配。")
                used.add(ref)
                sampled[key] = _sample(key, parameters[ref]["type"])
            else:
                sampled[key] = arg
        _base_arguments({"tool": item["tool"], "args": sampled})
        signature = gateway.dumps(item)
        if signature in seen:
            _error("unnecessary_tool", "配方包含重复子查询，请复用已有结果。")
        seen.add(signature)
    if used != set(parameters):
        _error("invalid_definition", "声明的参数必须全部使用，不能保留无用参数。")
    return value


def _matches(left, right, left_params, right_params, mapping):
    if left["tool"] != right["tool"] or set(left["args"]) != set(right["args"]):
        return None
    result = dict(mapping)
    for key, value in left["args"].items():
        other = right["args"][key]
        if isinstance(value, dict):
            if not isinstance(other, dict):
                return None
            source, target = value["param"], other["param"]
            if left_params[source]["type"] != right_params[target]["type"]:
                return None
            if source in result and result[source] != target:
                return None
            if source not in result and target in result.values():
                return None
            result[source] = target
        elif (
            isinstance(other, dict) or type(value) is not type(other) or value != other
        ):
            return None
    return result


def _covers(container, contained):
    """Check lossless inclusion allowing consistent parameter renaming.

    Mapping is injective: two independently configurable inputs cannot silently
    collapse into one. A bounded search rejects pathological ambiguous recipes.
    """
    choices = []
    for item in contained["queries"]:
        candidates = [
            i
            for i, candidate in enumerate(container["queries"])
            if _matches(
                item, candidate, contained["parameters"], container["parameters"], {}
            )
            is not None
        ]
        if not candidates:
            return False
        choices.append((item, candidates))
    choices.sort(key=lambda pair: len(pair[1]))
    attempts = 0

    def visit(index, occupied, mapping):
        nonlocal attempts
        if index == len(choices):
            return True
        item, candidates = choices[index]
        for candidate in candidates:
            attempts += 1
            if attempts > 10000:
                _error(
                    "complex_definition",
                    "工具参数映射过于复杂，请简化组合并复用现有工具。",
                )
            if candidate in occupied:
                continue
            result = _matches(
                item,
                container["queries"][candidate],
                contained["parameters"],
                container["parameters"],
                mapping,
            )
            if result is not None and visit(index + 1, occupied | {candidate}, result):
                return True
        return False

    return visit(0, set(), {})


def _equivalent(left, right):
    return (
        len(left["queries"]) == len(right["queries"])
        and len(left["parameters"]) == len(right["parameters"])
        and _covers(left, right)
    )


def _entry(definition):
    return {
        "__template_key": "query_tool",
        "name": definition["name"],
        "description": definition["description"],
        "note": definition["note"],
        "definition": gateway.dumps(
            {k: definition[k] for k in ("parameters", "queries")}
        ),
        "enabled": True,
    }


def _read_entry(entry):
    if (
        not isinstance(entry, dict)
        or set(entry)
        != {"__template_key", "name", "description", "note", "definition", "enabled"}
        or entry["__template_key"] != "query_tool"
        or type(entry["enabled"]) is not bool
        or not isinstance(entry["definition"], str)
        or len(entry["definition"]) > MAX_DEFINITION_CHARS
    ):
        _error("invalid_definition", "配置中的工具条目格式无效。")
    try:
        body = json.loads(entry["definition"])
    except (ValueError, RecursionError):
        _error("invalid_definition", "配置中的工具定义不是有效 JSON。")
    if not isinstance(body, dict) or set(body) != {"parameters", "queries"}:
        _error("invalid_definition", "配置中的工具定义字段无效。")
    return _validate_definition(
        {
            "name": entry["name"],
            "description": entry["description"],
            "note": entry["note"],
            **body,
        }
    )


class CustomToolStore:
    def __init__(self, config):
        self.config = config
        self.lock = asyncio.Lock()
        self.closed = False

    def close(self):
        """Prevent a child started before plugin reload from saving old config."""
        self.closed = True

    def _rows(self):
        rows = self.config.get(CONFIG_KEY, [])
        return rows if isinstance(rows, list) else []

    def _validated(self, rows, total_limit):
        names = Counter(
            row.get("name")
            for row in rows
            if isinstance(row, dict) and isinstance(row.get("name"), str)
        )
        valid, invalid, disabled = {}, 0, 0
        for index, row in enumerate(rows):
            try:
                definition = _read_entry(row)
                if names[definition["name"]] != 1:
                    raise ToolError("invalid_definition", "重复工具名。")
            except (ToolError, TypeError, KeyError, RecursionError):
                invalid += 1
                continue
            if not row["enabled"]:
                disabled += 1
            elif index < total_limit:
                valid[definition["name"]] = definition
        return valid, invalid, disabled

    def catalog(self, total_limit=20):
        _limits(total_limit=total_limit)
        rows = self._rows()
        valid, invalid, disabled = self._validated(rows, total_limit)
        result = {
            "tools": [],
            "total_count": len(rows),
            "disabled_count": disabled,
            "invalid_count": invalid
            + (not isinstance(self.config.get(CONFIG_KEY, []), list)),
            "over_limit_count": max(0, len(rows) - total_limit),
            "omitted_count": 0,
            "can_save": callable(getattr(self.config, "save_config", None))
            and not self.closed,
        }
        for definition in valid.values():
            if (
                len(gateway.dumps(result)) + len(gateway.dumps(definition)) + 64
                <= MAX_CATALOG_CHARS
            ):
                result["tools"].append(definition)
            else:
                result["omitted_count"] += 1
        return result

    def _expand(self, queries, rows, total_limit):
        try:
            requests = gateway.validate_queries(queries)
        except ValueError:
            _error("invalid_query", "查询批次格式、数量或总长度无效。")
        valid, _, _ = self._validated(rows, total_limit)
        expanded = []
        for item in requests:
            if not isinstance(item, dict) or set(item) - {"tool", "args"}:
                _error("invalid_query", "每项查询仅允许 tool 和 args。")
            name, args = item.get("tool"), item.get("args", {})
            if not isinstance(name, str) or not isinstance(args, dict):
                _error("invalid_query", "查询名称或参数对象无效。")
            if name in gateway.OPERATIONS:
                expanded.append(item)
                continue
            if name not in valid:
                _error("unknown_tool", "自定义工具不存在、已停用、无效或超出总量上限。")
            definition = valid[name]
            parameters = definition["parameters"]
            if set(args) != set(parameters):
                _error("invalid_query", "自定义工具的调用参数必须与声明完全一致。")
            for key, schema in parameters.items():
                value, kind = args[key], schema["type"]
                try:
                    finite_number = type(value) in (int, float) and math.isfinite(value)
                except OverflowError:
                    finite_number = False
                acceptable = (
                    (
                        kind == "string"
                        and isinstance(value, str)
                        and 0 < len(value.strip()) <= 200
                    )
                    or (kind == "integer" and type(value) is int)
                    or (kind == "number" and finite_number)
                )
                if not acceptable:
                    _error("invalid_query", "自定义工具参数类型或长度无效。")
            for template in definition["queries"]:
                query = {
                    "tool": template["tool"],
                    "args": {
                        key: args[value["param"]] if isinstance(value, dict) else value
                        for key, value in template["args"].items()
                    },
                }
                _base_arguments(query)
                expanded.append(query)
        try:
            return gateway.validate_queries(expanded)
        except ValueError:
            _error(
                "expanded_limit",
                "展开后的基础查询不能超过 24 项或 16000 字符，请缩小批次。",
            )

    def expand(self, queries, total_limit=20):
        _limits(total_limit=total_limit)
        return self._expand(queries, self._rows(), total_limit)

    async def apply(
        self,
        definitions,
        budget,
        per_session=1,
        total_limit=20,
        allow_optimize=False,
        *,
        queries=None,
        seen=None,
    ):
        """Validate and persist a whole mutation batch, or change nothing.

        The synchronous save happens without yielding after the lock is held.
        Definitions must be invoked in this same action when queries is supplied.
        """
        _limits(per_session, total_limit)
        if not isinstance(definitions, list) or not 1 <= len(definitions) <= 3:
            _error("invalid_definition", "单次只接受 1–3 个工具定义。")
        async with self.lock:
            if self.closed:
                _error("store_closed", "插件已重载，本次工具变更不再保存。")
            save = getattr(self.config, "save_config", None)
            if not callable(save):
                _error(
                    "save_unavailable",
                    "当前运行环境无法持久化配置，请直接使用基础查询。",
                )
            changes = budget.get("changes", 0)
            if (
                type(changes) is not int
                or changes < 0
                or changes + len(definitions) > per_session
            ):
                _error(
                    "session_limit",
                    "本次会话自定义工具变更额度已用完，请复用现有工具。",
                )
            existing_rows = self.config.get(CONFIG_KEY, [])
            if not isinstance(existing_rows, list):
                _error("invalid_config", "自定义工具配置必须是列表，请管理员修正。")
            rows = _copy(existing_rows)
            current, _, _ = self._validated(rows, total_limit)
            known = []
            for row in rows:
                try:
                    known.append(_read_entry(row))
                except (ToolError, TypeError, KeyError, RecursionError):
                    continue
            proposed, removed, names = [], set(), set()
            occupied = {
                row.get("name")
                for row in rows
                if isinstance(row, dict) and isinstance(row.get("name"), str)
            }
            for raw in definitions:
                if not isinstance(raw, dict) or set(raw) - FIELDS - {"replaces"}:
                    _error("invalid_definition", "工具定义字段无效。")
                definition = _validate_definition(
                    {key: raw[key] for key in FIELDS if key in raw}
                )
                name = definition["name"]
                if name in names:
                    _error("duplicate_tool", "同批工具名不能重复。")
                names.add(name)
                replacements = raw.get("replaces", [])
                if (
                    not isinstance(replacements, list)
                    or any(not isinstance(x, str) for x in replacements)
                    or len(set(replacements)) != len(replacements)
                ):
                    _error(
                        "invalid_definition",
                        "replaces 必须是不重复的自定义工具名列表。",
                    )
                targets = set(replacements)
                if name in occupied:
                    targets.add(name)
                if targets:
                    if not allow_optimize:
                        _error(
                            "optimization_not_needed",
                            "尚有查询轮数，请复用现有工具，不要提前改写或合并。",
                        )
                    if targets - set(current) or targets & removed:
                        _error(
                            "immutable_base",
                            "只能优化或合并有效且启用的已有自定义工具。",
                        )
                    for target in targets:
                        if not _covers(definition, current[target]):
                            _error(
                                "lossy_merge",
                                "优化或合并必须保留原工具的全部查询及参数独立性。",
                            )
                    if len(targets) == 1 and _equivalent(
                        definition, current[next(iter(targets))]
                    ):
                        _error(
                            "unnecessary_tool",
                            "仅改名或改描述没有新增查询能力，请复用现有工具。",
                        )
                    removed.update(targets)
                for previous in [*known, *proposed]:
                    if previous["name"] not in targets and _equivalent(
                        definition, previous
                    ):
                        _error(
                            "duplicate_tool",
                            "已有等价工具，请复用；参数改名不构成新能力。",
                        )
                if name in current and _equivalent(definition, current[name]):
                    _error(
                        "unnecessary_tool",
                        "工具能力没有变化，描述修改请由管理员在配置中完成。",
                    )
                proposed.append(definition)
            if removed & (names - set(current)):
                _error("invalid_definition", "同批不能创建并替换同一工具。")
            updated = [
                row
                for row in rows
                if not isinstance(row, dict) or row.get("name") not in removed
            ]
            updated.extend(_entry(value) for value in proposed)
            if len(updated) > total_limit:
                _error(
                    "total_limit",
                    "自定义工具总量已达上限，请复用或由管理员清理；不会自动删除。",
                )
            if removed and len(updated) > len(rows):
                _error("total_limit", "优化或合并不能增加自定义工具总量。")
            expanded = None
            if queries is not None:
                expanded = self._expand(queries, updated, total_limit)
                for query in expanded:
                    _base_arguments(query)
                if seen and gateway.dumps(expanded) in seen:
                    _error(
                        "duplicate_query",
                        "本批查询已执行，请复用已有材料，无需创建工具。",
                    )
                used = {item.get("tool") for item in queries if isinstance(item, dict)}
                if names - used:
                    _error(
                        "unused_tool",
                        "新建或优化的每个工具都必须用于当前查询，不能只创建不查询。",
                    )
            missing = CONFIG_KEY not in self.config
            previous = self.config.get(CONFIG_KEY)
            self.config[CONFIG_KEY] = updated
            try:
                save()
            except Exception:  # noqa: BLE001 -- never leak config paths or secrets
                if missing:
                    self.config.pop(CONFIG_KEY, None)
                else:
                    self.config[CONFIG_KEY] = previous
                _error(
                    "save_failed",
                    "自定义工具保存失败，变更未生效；请直接使用现有查询。",
                )
            budget["changes"] = changes + len(proposed)
            return expanded
