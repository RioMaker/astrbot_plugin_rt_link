"""Replay the public child-agent boundary with persistent custom query recipes."""

import asyncio
import copy
import json

import mock_astrbot as mock
import pytest
from test_query_agent import final, plan, plugin, public_query

import query_gateway as gateway
from query_agent import AgentSettings, token_upper_bound


class SavedConfig(dict):
    """AstrBot's synchronous config persistence boundary without live services."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.saved = []
        self.failure = None

    def save_config(self):
        if self.failure:
            raise self.failure
        self.saved.append(copy.deepcopy(dict(self)))


def recipe(name="custom_song_regions", variant=0):
    queries = [
        {
            "tool": "query_dan_course",
            "args": {"song_name": {"param": "song"}, "region": "cn"},
        },
        {
            "tool": "query_dan_course",
            "args": {"song_name": {"param": "song"}, "region": "jp"},
        },
    ]
    if variant:
        queries[1] = {
            "tool": "get_library_status" if variant == 1 else "get_source_status"
        }
    return {
        "name": name,
        "description": "查询指定歌曲在各区域的段位记录。",
        "note": "复用同一歌曲参数并合并区域查询，不保存玩家资料。",
        "parameters": {"song": {"type": "string", "description": "歌曲名或别名"}},
        "queries": queries,
    }


def stored(definition=None):
    definition = definition or recipe()
    return {
        "__template_key": "query_tool",
        "name": definition["name"],
        "description": definition["description"],
        "note": definition["note"],
        "enabled": True,
        "definition": gateway.dumps(
            {key: definition[key] for key in ("parameters", "queries")}
        ),
    }


def invoke(name="custom_song_regions", song="六天"):
    return {"tool": name, "args": {"song": song}}


def create(definition=None):
    definition = definition or recipe()
    return {
        "action": "query",
        "save_tools": [definition],
        "queries": [invoke(definition["name"])],
    }


def configured_plugin(tmp_path, script, **cfg):
    star, ev, backend, loads = plugin(tmp_path, script, **cfg)
    star.cfg = SavedConfig(star.cfg)
    return star, ev, backend, loads


def fresh_event(ev):
    fresh = mock.AstrMessageEvent("qq", False, False, "NEW-MAIN-HISTORY")
    fresh.unified_msg_origin = ev.unified_msg_origin
    return fresh


def assert_final_only(text):
    assert json.loads(text)["summary"] == final()["summary"]
    for private in (
        "custom_song_regions",
        "save_tools",
        "query_dan_course",
        "SECRET",
        "materials",
        "parameters",
    ):
        assert private not in text


def test_create_and_execute_in_one_round_then_reuse_after_reload(tmp_path):
    async def run():
        star, ev, _, loads = configured_plugin(tmp_path, [create(), final()])
        result = await star.query_rtlink(ev, "六天在哪些区域的段位中？")
        assert_final_only(result)
        assert len(star.context.calls) == 2 and not loads
        assert len(star.cfg.saved) == 1
        entries = star.cfg.saved[-1]["query_agent_custom_tools"]
        assert len(entries) == 1 and entries[0]["name"] == "custom_song_regions"
        assert entries[0]["note"] == recipe()["note"]
        assert entries[0]["__template_key"] == "query_tool"
        assert "PRIVATE-MAIN-HISTORY" not in gateway.dumps(entries)
        materials = json.loads(star.context.calls[-1]["prompt"])["materials"]
        assert {row["args"]["region"] for row in materials[0]["results"]} == {
            "cn",
            "jp",
        }
        assert all(row["status"] == "completed" for row in materials[0]["results"])

        reloaded, other, _, _ = configured_plugin(
            tmp_path, [plan(invoke()), final()], query_agent_custom_tools=entries
        )
        assert_final_only(await reloaded.query_rtlink(other, "查询六天的段位"))
        assert not reloaded.cfg.saved
        assert "custom_song_regions" in reloaded.context.calls[0]["prompt"]
        assert len(reloaded.context.calls) == 2

    asyncio.run(run())


def test_existing_base_query_does_not_save_a_tool(tmp_path):
    async def run():
        star, ev, _, _ = configured_plugin(tmp_path, [plan(public_query()), final()])
        assert_final_only(await star.query_rtlink(ev, "六天在哪个段位？"))
        assert not star.cfg.saved and not star.cfg.get("query_agent_custom_tools")
        prompt = star.context.calls[0]["system_prompt"]
        assert "勿增实体" in prompt

    asyncio.run(run())


def test_already_queried_combination_is_not_saved_as_a_new_tool(tmp_path):
    async def run():
        existing = plan(
            {
                "tool": "query_dan_course",
                "args": {"song_name": "六天", "region": "cn"},
            },
            {
                "tool": "query_dan_course",
                "args": {"song_name": "六天", "region": "jp"},
            },
        )
        star, ev, _, _ = configured_plugin(tmp_path, [existing, create(), final()])
        assert_final_only(await star.query_rtlink(ev, "六天在哪些区域的段位中？"))
        assert not star.cfg.saved and not star.cfg.get("query_agent_custom_tools")
        materials = json.loads(star.context.calls[-1]["prompt"])["materials"]
        assert len(materials) == 1

    asyncio.run(run())


def test_description_edits_and_deletion_are_read_from_current_config(tmp_path):
    async def run():
        star, ev, _, _ = configured_plugin(
            tmp_path,
            [plan(invoke()), final(), plan(invoke()), plan(public_query()), final()],
            query_agent_custom_tools=[stored()],
        )
        star.cfg["query_agent_custom_tools"][0]["description"] = (
            "ADMIN-EDIT-DESCRIPTION"
        )
        assert_final_only(await star.query_rtlink(ev, "查六天的段位"))
        assert "ADMIN-EDIT-DESCRIPTION" in star.context.calls[0]["prompt"]
        star.cfg["query_agent_custom_tools"] = []
        other = fresh_event(ev)
        assert_final_only(await star.query_rtlink(other, "再查六天的段位"))
        assert "custom_song_regions" not in star.context.calls[2]["prompt"]
        assert not star.cfg["query_agent_custom_tools"] and not star.cfg.saved
        materials = json.loads(star.context.calls[-1]["prompt"])["materials"]
        assert len(materials) == 1 and len(materials[0]["results"]) == 1

    asyncio.run(run())


def test_two_parent_calls_share_creation_budget_and_next_message_resets(tmp_path):
    async def run():
        second = recipe("custom_song_library", variant=1)
        star, ev, _, _ = configured_plugin(
            tmp_path,
            [
                create(),
                final(),
                create(second),
                plan(public_query()),
                final(),
                create(second),
                final(),
            ],
            query_agent_tools_per_session=1,
        )
        assert_final_only(await star.query_rtlink(ev, "查询六天各区域段位"))
        assert_final_only(await star.query_rtlink(ev, "补充谱面库状态"))
        assert len(star.cfg.saved) == 1
        assert len(star.cfg["query_agent_custom_tools"]) == 1
        assert ev._rtlink_ai_state["custom_tools"]["changes"] == 1
        other = fresh_event(ev)
        assert_final_only(await star.query_rtlink(other, "查询六天和谱面库"))
        assert len(star.cfg.saved) == 2
        assert len(star.cfg["query_agent_custom_tools"]) == 2
        assert other._rtlink_ai_state["custom_tools"]["changes"] == 1

    asyncio.run(run())


def test_disabling_creation_preserves_existing_custom_queries(tmp_path):
    async def run():
        star, ev, _, _ = configured_plugin(
            tmp_path,
            [create(recipe("custom_song_library", 1)), plan(invoke()), final()],
            query_agent_tools_enabled=False,
            query_agent_custom_tools=[stored()],
        )
        assert_final_only(await star.query_rtlink(ev, "查询六天的段位"))
        assert not star.cfg.saved
        assert len(star.cfg["query_agent_custom_tools"]) == 1
        assert len(star.context.calls) == 3

    asyncio.run(run())


def test_storage_failure_is_private_and_base_query_still_works(tmp_path):
    async def run():
        star, ev, _, _ = configured_plugin(
            tmp_path, [create(), plan(public_query()), final()]
        )
        star.cfg.failure = OSError("SECRET-FILESYSTEM-PATH-AND-PAYLOAD")
        assert_final_only(await star.query_rtlink(ev, "查六天的段位"))
        assert not star.cfg.get("query_agent_custom_tools") and not star.cfg.saved
        assert ev._rtlink_ai_state["custom_tools"].get("changes", 0) == 0
        assert "SECRET" not in star.context.calls[1]["prompt"]

    asyncio.run(run())


def test_dictionary_config_cannot_claim_successful_persistence(tmp_path):
    async def run():
        star, ev, _, _ = plugin(tmp_path, [create(), plan(public_query()), final()])
        assert_final_only(await star.query_rtlink(ev, "查六天的段位"))
        assert not star.cfg.get("query_agent_custom_tools")
        assert len(star.context.calls) == 3

    asyncio.run(run())


def test_recipe_cannot_turn_read_query_into_business_write(tmp_path):
    async def run():
        definition = recipe()
        definition["queries"][1] = {
            "tool": "set_song_alias",
            "args": {"song_name": {"param": "song"}, "alias": "SECRET-ALIAS"},
        }
        star, ev, backend, _ = configured_plugin(
            tmp_path, [create(definition), plan(public_query()), final()]
        )

        async def forbidden(*_args, **_kwargs):
            pytest.fail("a generated recipe must never execute a business write")

        backend.request_alias = forbidden
        assert_final_only(await star.query_rtlink(ev, "查六天的段位"))
        assert not star.cfg.saved and not star.cfg.get("query_agent_custom_tools")
        assert "SECRET-ALIAS" not in star.context.calls[1]["prompt"]

    asyncio.run(run())


def test_disabled_tool_cannot_execute_or_be_implicitly_reenabled(tmp_path):
    async def run():
        entry = stored()
        entry["enabled"] = False
        star, ev, _, _ = configured_plugin(
            tmp_path,
            [plan(invoke()), plan(public_query()), final()],
            query_agent_custom_tools=[entry],
        )
        assert_final_only(await star.query_rtlink(ev, "查六天的段位"))
        assert not star.cfg.saved
        assert star.cfg["query_agent_custom_tools"][0]["enabled"] is False
        materials = json.loads(star.context.calls[-1]["prompt"])["materials"]
        assert len(materials) == 1 and len(materials[0]["results"]) == 1

    asyncio.run(run())


def test_last_round_cannot_save_a_tool_even_with_previous_evidence(tmp_path):
    async def run():
        star, ev, _, _ = configured_plugin(
            tmp_path,
            [plan(public_query()), create()],
            query_agent_max_rounds=2,
        )
        text = await star.query_rtlink(ev, "查六天的段位")
        assert "未能" in text
        assert not star.cfg.saved and not star.cfg.get("query_agent_custom_tools")
        assert len(star.context.calls) == 2

    asyncio.run(run())


def test_optimization_only_in_last_query_round(tmp_path):
    async def run():
        modified = recipe()
        modified["queries"].append({"tool": "get_library_status"})
        modified["note"] = "轮数不足，将库状态与各区域段位合并查询。"
        star, ev, _, _ = configured_plugin(
            tmp_path,
            [create(modified), create(modified), final()],
            query_agent_custom_tools=[stored()],
            query_agent_max_rounds=3,
        )
        assert_final_only(await star.query_rtlink(ev, "查六天各区域段位和谱面库"))
        assert len(star.cfg.saved) == 1
        assert len(star.context.calls) == 3
        definition = json.loads(star.cfg["query_agent_custom_tools"][0]["definition"])
        assert len(definition["queries"]) == 3

    asyncio.run(run())


def test_catalog_and_saved_tool_metadata_count_toward_context_limit(tmp_path):
    async def run():
        entry = stored()
        entry["description"] = "目录说明" * 50
        entry["note"] = "目录注释" * 50
        star, ev, _, _ = configured_plugin(
            tmp_path,
            [plan(invoke()), final()],
            query_agent_custom_tools=[entry],
            query_agent_context_tokens=32000,
        )
        assert_final_only(await star.query_rtlink(ev, "查六天的段位"))
        for call in star.context.calls:
            assert (
                token_upper_bound(
                    call["system_prompt"], call["prompt"], call["max_tokens"]
                )
                <= 32000
            )
        assert entry["description"] in star.context.calls[0]["prompt"]

    asyncio.run(run())


def test_final_round_drops_tool_definitions_and_retains_complete_evidence(tmp_path):
    async def run():
        star, ev, backend, _ = configured_plugin(
            tmp_path,
            [plan(invoke()), final()],
            query_agent_custom_tools=[stored()],
            query_agent_max_rounds=2,
            query_agent_context_tokens=32000,
        )
        batches = []
        original = backend.get_readonly_queries_text

        async def record(*args, **kwargs):
            batch = await original(*args, **kwargs)
            batches.append(copy.deepcopy(batch))
            return batch

        backend.get_readonly_queries_text = record
        assert_final_only(await star.query_rtlink(ev, "六天在哪些区域的段位中？"))
        first = json.loads(star.context.calls[0]["prompt"])
        last = json.loads(star.context.calls[-1]["prompt"])
        assert first["custom_tools"]["tools"][0]["name"] == "custom_song_regions"
        assert last["custom_tools"]["tools"] == []
        assert last["custom_tools"]["total_count"] == 1
        assert last["custom_tools"]["omitted_count"] == 1
        assert last["tool_policy"]["creation_allowed"] is False
        assert len(last["materials"]) == len(batches) == 1
        rows = last["materials"][0]["results"]
        assert len(rows) == 2
        for actual, expected in zip(rows, batches[0]["results"]):
            assert actual["status"] == "completed"
            assert actual["truncated"] is False
            assert actual["data"] == expected["data"]
            assert "第六天魔王" in actual["data"]
        assert len(star.context.calls) == 2

    asyncio.run(run())


@pytest.mark.parametrize(
    "cfg",
    [
        {"query_agent_tools_enabled": "false"},
        {"query_agent_tools_per_session": 0},
        {"query_agent_tools_per_session": 4},
        {"query_agent_tools_per_session": True},
        {"query_agent_tools_total": 0},
        {"query_agent_tools_total": 101},
    ],
)
def test_custom_tool_configuration_limits_are_validated(cfg):
    with pytest.raises(ValueError):
        AgentSettings.from_config(cfg)
