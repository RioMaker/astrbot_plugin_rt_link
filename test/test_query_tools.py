"""Recipe integrity, configuration persistence and mutation quota tests."""

import asyncio
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import query_gateway as gateway
from query_tools import CONFIG_KEY, MAX_CATALOG_CHARS, CustomToolStore, ToolError


class Config(dict):
    def __init__(self, rows=()):
        super().__init__({CONFIG_KEY: list(rows), "unrelated": "keep"})
        self.saves = []
        self.fail = False

    def save_config(self):
        if self.fail:
            raise OSError("SECRET-CONFIG-PATH")
        self.saves.append(copy.deepcopy(dict(self)))


def recipe(name="custom_dan", param="song", year=2024):
    return {
        "name": name,
        "description": "查询歌曲的两区段位记录",
        "note": "相同歌曲参数一次获取国服和日版课程",
        "parameters": {param: {"type": "string", "description": "歌曲名称"}},
        "queries": [
            {
                "tool": "query_dan_course",
                "args": {"song_name": {"param": param}, "region": region, "year": year},
            }
            for region in ("cn", "jp")
        ],
    }


def entry(value, enabled=True):
    return {
        "__template_key": "query_tool",
        "name": value["name"],
        "description": value["description"],
        "note": value["note"],
        "definition": json.dumps(
            {key: value[key] for key in ("parameters", "queries")}, ensure_ascii=False
        ),
        "enabled": enabled,
    }


def invoke(name="custom_dan", **args):
    return {"tool": name, "args": args or {"song": "六天"}}


def reject(code, function):
    with pytest.raises(ToolError) as caught:
        function()
    assert caught.value.code == code
    assert "SECRET" not in str(caught.value)


def test_create_persists_full_definition_and_expands_current_target():
    cfg, budget = Config(), {}
    store = CustomToolStore(cfg)
    result = asyncio.run(store.apply([recipe()], budget, queries=[invoke()]))
    assert len(result) == 2
    assert {row["args"]["region"] for row in result} == {"cn", "jp"}
    assert all(row["args"]["song_name"] == "六天" for row in result)
    assert budget == {"changes": 1} and len(cfg.saves) == 1
    assert cfg.saves[0]["unrelated"] == "keep"
    assert store.catalog()["tools"] == [recipe()]
    assert CustomToolStore(Config(cfg[CONFIG_KEY])).expand([invoke()]) == result


@pytest.mark.parametrize(
    "variant",
    [
        "base_name",
        "write",
        "recursive",
        "one",
        "repeat",
        "unused",
        "missing",
        "wrong_type",
        "unknown",
        "oversize",
        "bad_numeric",
        "many_params",
    ],
)
def test_invalid_recipes_never_change_config_or_base_functions(variant):
    definition = recipe()
    if variant == "base_name":
        definition["name"] = "query_dan_course"
    elif variant == "write":
        definition["queries"][0]["tool"] = "bind"
    elif variant == "recursive":
        definition["queries"][0]["tool"] = "custom_dan"
    elif variant == "one":
        definition["queries"].pop()
    elif variant == "repeat":
        definition["queries"][1] = copy.deepcopy(definition["queries"][0])
    elif variant == "unused":
        definition["parameters"]["unused"] = {
            "type": "integer",
            "description": "未使用",
        }
    elif variant == "missing":
        definition["parameters"] = {}
    elif variant == "wrong_type":
        definition["parameters"]["song"]["type"] = "integer"
    elif variant == "unknown":
        definition["queries"][0]["args"]["qq"] = "another-player"
    elif variant == "oversize":
        definition["note"] = "x" * 301
    elif variant == "bad_numeric":
        definition["queries"][0] = {
            "tool": "search_scores",
            "args": {"accuracy_min": 10**400},
        }
    elif variant == "many_params":
        definition["parameters"] = {
            f"p{i}": {"type": "string", "description": "参数"} for i in range(13)
        }
    cfg, budget, foundation = Config(), {}, copy.deepcopy(gateway.OPERATIONS)
    with pytest.raises(ToolError):
        asyncio.run(CustomToolStore(cfg).apply([definition], budget))
    assert cfg[CONFIG_KEY] == [] and not cfg.saves and not budget
    assert gateway.OPERATIONS == foundation


@pytest.mark.parametrize("enabled", [True, False])
def test_equivalent_recipes_rejected_even_after_renaming_parameters_and_reordering(
    enabled,
):
    cfg = Config([entry(recipe(), enabled)])
    definition = recipe("custom_clone", "title")
    definition["queries"].reverse()
    reject(
        "duplicate_tool",
        lambda: asyncio.run(CustomToolStore(cfg).apply([definition], {})),
    )
    assert len(cfg[CONFIG_KEY]) == 1 and not cfg.saves


def test_config_edits_and_deletion_are_authoritative_without_cache_resurrection():
    cfg = Config([entry(recipe())])
    store = CustomToolStore(cfg)
    cfg[CONFIG_KEY][0]["description"] = "管理员改过的说明"
    assert store.catalog()["tools"][0]["description"] == "管理员改过的说明"
    cfg[CONFIG_KEY].clear()
    assert store.catalog()["tools"] == []
    reject("unknown_tool", lambda: store.expand([invoke()]))
    asyncio.run(store.apply([recipe("custom_other", year=2023)], {}))
    assert [row["name"] for row in cfg[CONFIG_KEY]] == ["custom_other"]


def test_invalid_configuration_entries_are_isolated_including_overflow():
    bad = recipe("custom_invalid")
    bad["queries"][0] = {"tool": "search_scores", "args": {"accuracy_min": 10**400}}
    cfg = Config(
        [
            entry(bad),
            {"enabled": True},
            entry(recipe()),
            entry(recipe("custom_disabled", year=2023), False),
        ]
    )
    store = CustomToolStore(cfg)
    catalog = store.catalog()
    assert catalog["invalid_count"] == 2 and catalog["disabled_count"] == 1
    assert [tool["name"] for tool in catalog["tools"]] == ["custom_dan"]
    assert store.expand([{"tool": "get_library_status"}]) == [
        {"tool": "get_library_status"}
    ]
    assert len(store.expand([invoke()])) == 2
    cfg[CONFIG_KEY] = "invalid-root"
    assert store.catalog()["invalid_count"] == 1
    assert store.expand([{"tool": "get_library_status"}])
    reject("invalid_config", lambda: asyncio.run(store.apply([recipe()], {})))


def test_duplicate_names_are_unavailable_and_over_limit_entries_stay_stored():
    rows = [entry(recipe()), entry(recipe()), entry(recipe("custom_later", year=2022))]
    cfg = Config(rows)
    store = CustomToolStore(cfg)
    catalog = store.catalog(total_limit=2)
    assert catalog["invalid_count"] == 2 and catalog["over_limit_count"] == 1
    assert not catalog["tools"] and len(cfg[CONFIG_KEY]) == 3
    reject(
        "unknown_tool", lambda: store.expand([invoke("custom_later")], total_limit=2)
    )


def test_catalog_has_an_independent_size_bound():
    rows = []
    for i in range(100):
        tool = recipe(f"custom_{i}")
        tool["description"] = "描" * 300
        tool["note"] = "注" * 300
        rows.append(entry(tool))
    catalog = CustomToolStore(Config(rows)).catalog(100)
    assert len(gateway.dumps(catalog)) <= MAX_CATALOG_CHARS
    assert catalog["omitted_count"] > 0


def test_session_and_global_limits_include_disabled_rows_and_are_atomic():
    cfg, budget = Config(), {}
    definitions = [recipe(f"custom_{i}", year=2022 + i) for i in range(3)]
    store = CustomToolStore(cfg)
    asyncio.run(store.apply(definitions, budget, per_session=3))
    assert budget["changes"] == 3 and len(cfg.saves) == 1
    reject(
        "session_limit",
        lambda: asyncio.run(
            store.apply([recipe("custom_fourth", year=2025)], budget, per_session=3)
        ),
    )
    cfg[CONFIG_KEY][0]["enabled"] = False
    reject(
        "total_limit",
        lambda: asyncio.run(
            store.apply([recipe("custom_fourth", year=2025)], {}, total_limit=3)
        ),
    )
    assert len(cfg[CONFIG_KEY]) == 3 and len(cfg.saves) == 1


def test_concurrent_players_cannot_exceed_global_capacity():
    async def run():
        cfg = Config()
        store = CustomToolStore(cfg)
        results = await asyncio.gather(
            store.apply([recipe("custom_one", year=2023)], {}, total_limit=1),
            store.apply([recipe("custom_two", year=2024)], {}, total_limit=1),
            return_exceptions=True,
        )
        assert sum(isinstance(value, ToolError) for value in results) == 1
        assert len(cfg[CONFIG_KEY]) == 1 and len(cfg.saves) == 1

    asyncio.run(run())


def test_save_failure_and_reload_leave_no_runtime_tool_or_quota_charge():
    cfg, budget = Config(), {}
    cfg.fail = True
    store = CustomToolStore(cfg)
    reject("save_failed", lambda: asyncio.run(store.apply([recipe()], budget)))
    assert cfg[CONFIG_KEY] == [] and not budget
    store.close()
    reject("store_closed", lambda: asyncio.run(store.apply([recipe()], budget)))
    assert not store.catalog()["can_save"]
    plain = CustomToolStore({CONFIG_KEY: [entry(recipe())]})
    assert len(plain.expand([invoke()])) == 2
    reject(
        "save_unavailable",
        lambda: asyncio.run(plain.apply([recipe("custom_new", year=2023)], {})),
    )


def test_lossless_merge_requires_late_round_and_preserves_existing_operations():
    first, second = (
        recipe("custom_first", year=2023),
        recipe("custom_second", year=2024),
    )
    cfg = Config([entry(first), entry(second)])
    store = CustomToolStore(cfg)
    merged = recipe("custom_merged", year=2023)
    merged["queries"].extend(second["queries"])
    merged["replaces"] = ["custom_first", "custom_second"]
    reject("optimization_not_needed", lambda: asyncio.run(store.apply([merged], {})))
    result = asyncio.run(
        store.apply(
            [merged], {}, allow_optimize=True, queries=[invoke("custom_merged")]
        )
    )
    assert len(result) == 4 and len(cfg[CONFIG_KEY]) == 1
    assert cfg[CONFIG_KEY][0]["name"] == "custom_merged"


@pytest.mark.parametrize("variant", ["drop", "break_shared", "collapse_independent"])
def test_optimization_cannot_silently_change_parameter_relationships(variant):
    original = recipe()
    updated = copy.deepcopy(original)
    if variant == "drop":
        updated["queries"][1]["args"]["year"] = 2025
    elif variant == "break_shared":
        updated["parameters"]["other"] = {"type": "string", "description": "另一个歌曲"}
        updated["queries"][1]["args"]["song_name"] = {"param": "other"}
    else:
        original["parameters"]["other"] = {
            "type": "string",
            "description": "另一个歌曲",
        }
        original["queries"][1]["args"]["song_name"] = {"param": "other"}
    cfg = Config([entry(original)])
    reject(
        "lossy_merge",
        lambda: asyncio.run(
            CustomToolStore(cfg).apply([updated], {}, allow_optimize=True)
        ),
    )
    assert cfg[CONFIG_KEY] == [entry(original)] and not cfg.saves


@pytest.mark.parametrize("variant", ["unused", "seen", "bad_argument", "too_many"])
def test_save_and_use_is_atomic_if_current_query_is_invalid(variant):
    cfg, budget = Config(), {}
    queries, kwargs = [invoke()], {}
    code = {
        "unused": "unused_tool",
        "seen": "duplicate_query",
        "bad_argument": "invalid_query",
        "too_many": "expanded_limit",
    }[variant]
    if variant == "unused":
        queries = [{"tool": "get_library_status"}]
    elif variant == "seen":
        temp = CustomToolStore(Config([entry(recipe())]))
        kwargs["seen"] = {gateway.dumps(temp.expand(queries))}
    elif variant == "bad_argument":
        queries.append({"tool": "get_recent_scores", "args": {"days": 0}})
    else:
        queries = [invoke(song=f"歌{i}") for i in range(13)]
    reject(
        code,
        lambda: asyncio.run(
            CustomToolStore(cfg).apply([recipe()], budget, queries=queries, **kwargs)
        ),
    )
    assert not cfg.saves and cfg[CONFIG_KEY] == [] and not budget


@pytest.mark.parametrize("value", [True, float("inf"), 10**400, "42"])
def test_number_call_parameters_are_finite_and_do_not_raise_overflow(value):
    tool = recipe()
    tool["parameters"] = {"minimum": {"type": "number", "description": "最低精度"}}
    tool["queries"] = [
        {
            "tool": "search_scores",
            "args": {"accuracy_min": {"param": "minimum"}, "level": level},
        }
        for level in (4, 5)
    ]
    store = CustomToolStore(Config([entry(tool)]))
    reject("invalid_query", lambda: store.expand([invoke(minimum=value)]))


def test_valid_templates_still_validate_actual_integer_ranges():
    tool = recipe()
    tool["parameters"] = {"year": {"type": "integer", "description": "课程年度"}}
    for query in tool["queries"]:
        query["args"]["song_name"] = "六天"
        query["args"]["year"] = {"param": "year"}
    store = CustomToolStore(Config([entry(tool)]))
    reject("invalid_query", lambda: store.expand([invoke(year=1980)]))
    assert len(store.expand([invoke(year=2024)])) == 2
