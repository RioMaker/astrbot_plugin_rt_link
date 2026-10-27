"""Offline child-agent replay; no live model or account credentials are used."""

import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import mock_astrbot as mock
import pytest
from PIL import Image
from test_query_gateway import make_service

import main
import query_gateway as gateway
from query_agent import AgentSettings, QueryAgent, system_prompt, token_upper_bound
from query_result_image import prune_query_results, render_query_result
from service import MemoryBindingsStore
from source_service import MultiSourceService
from storage import load_dan_courses


def final():
    return {
        "action": "final",
        "summary": "六天出现在2024年国服及日版/国际版达人的第3曲。",
        "result": {
            "title": "六天的段位记录",
            "conclusion": "《第六天魔王》出现在2024年达人课程中。",
            "rows": [
                {
                    "label": "2024 国服 / 日版及国际版",
                    "value": "达人 · 第3曲 · 里鬼★10 · ID 765",
                }
            ],
            "limitations": ["同一首歌跨年度是否出现，以已收录的课程资料为准。"],
        },
    }


def plan(*queries):
    return {"action": "query", "queries": list(queries)}


def public_query():
    return {"tool": "query_dan_course", "args": {"song_no": 765}}


class Context:
    def __init__(self, script):
        self.script, self.calls, self.provider_sessions = list(script), [], []

    async def get_current_chat_provider_id(self, umo):
        self.provider_sessions.append(umo)
        return "current-main-provider"

    async def llm_generate(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        response = self.script.pop(0)
        if isinstance(response, BaseException):
            raise response
        if not isinstance(response, str):
            response = json.dumps(response, ensure_ascii=False)
        return SimpleNamespace(
            completion_text=response, reasoning_content="SECRET-CHILD-REASONING"
        )


def plugin(tmp_path, script, **cfg):
    backend, loads = make_service()
    star = object.__new__(main.RTLinkPlugin)
    star.context = Context(script)
    star.cfg = {"query_agent_output_mode": "text", **cfg}
    star.service = MultiSourceService({"kinoko": backend}, MemoryBindingsStore())
    star.data_dir = tmp_path
    star.dan_courses = load_dan_courses(
        Path(__file__).resolve().parents[1] / "resource/dan_courses.v1.json.gz"
    )
    ev = mock.AstrMessageEvent("qq", False, False, "PRIVATE-MAIN-HISTORY")
    ev.unified_msg_origin = "group:123"
    ev.sent = []

    async def send(result):
        ev.sent.append(result)

    ev.send = send
    return star, ev, backend, loads


def test_group_query_uses_same_provider_and_independent_context_final_only(tmp_path):
    async def run():
        star, ev, _, loads = plugin(tmp_path, [plan(public_query()), final()])
        result = json.loads(await star.query_rtlink(ev, "六天在哪个段位？"))
        assert result["summary"] == final()["summary"]
        assert result["result"]["rows"] == final()["result"]["rows"]
        assert len(star.context.calls) == 2
        for call in star.context.calls:
            assert call["chat_provider_id"] == "current-main-provider"
            assert (
                call["contexts"] == []
                and call["tools"] is None
                and call["image_urls"] == []
            )
            assert "PRIVATE-MAIN-HISTORY" not in gateway.dumps(call)
            assert "SECRET-CHILD-REASONING" not in gateway.dumps(call)
            assert (
                token_upper_bound(
                    call["system_prompt"], call["prompt"], call["max_tokens"]
                )
                <= 200000
            )
        assert star.context.provider_sessions == ["group:123"]
        assert not loads  # public records require no player sync
        assert not ev.sent and not list(tmp_path.glob("**/*.json"))
        assert ev._rtlink_ai_state["calls"] == 1
        text = gateway.dumps(result)
        for secret in (
            "queries",
            "query_dan_course",
            "SECRET-CHILD",
            "format_feedback",
            "materials",
        ):
            assert secret not in text
        assert gateway.ANALYSIS_SCOPE.get() is None

    asyncio.run(run())


def test_two_child_batches_share_analysis_and_only_one_parent_call(tmp_path):
    async def run():
        star, ev, _, loads = plugin(
            tmp_path,
            [
                plan({"tool": "get_player_rating"}),
                plan({"tool": "get_rank_distribution"}),
                final(),
            ],
        )
        await star.query_rtlink(ev, "查询我的评级和评价分布")
        assert loads == ["qq"] and len(star.context.calls) == 3
        assert ev._rtlink_ai_state["calls"] == 1
        assert "复用已有结果" in await star.query_rtlink(ev, "查询我的评级和评价分布")
        assert len(star.context.calls) == 3

    asyncio.run(run())


def test_parent_budget_and_fresh_child_state_on_the_next_message(tmp_path):
    async def run():
        star, ev, _, _ = plugin(
            tmp_path,
            [
                plan(public_query()),
                final(),
                plan(public_query()),
                final(),
                plan(public_query()),
                final(),
            ],
        )
        await star.query_rtlink(ev, "查询六天的段位")
        await star.query_rtlink(ev, "再列一下六天的区域")
        assert "预算已用完" in await star.query_rtlink(ev, "补充年份")
        assert len(star.context.calls) == 4
        fresh = mock.AstrMessageEvent("qq", False, False, "ANOTHER-MAIN-HISTORY")
        fresh.unified_msg_origin = ev.unified_msg_origin
        await star.query_rtlink(fresh, "查询六天的段位")
        assert len(star.context.calls) == 6
        assert json.loads(star.context.calls[4]["prompt"])["materials"] == []
        assert fresh._rtlink_ai_state["calls"] == 1

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["image", "both"])
def test_result_image_contains_only_final_report(tmp_path, mode):
    async def run():
        star, ev, _, _ = plugin(
            tmp_path, [plan(public_query()), final()], query_agent_output_mode=mode
        )
        result = json.loads(await star.query_rtlink(ev, "六天段位记录"))
        assert result["delivery"] == "image_sent" and len(ev.sent) == 1
        image = Image.open(ev.sent[0])
        assert (
            image.format == "PNG"
            and image.width == 1440
            and 800 <= image.height <= 10000
        )
        assert ("result" in result) == (mode == "both")
        assert "queries" not in gateway.dumps(result)
        assert not (tmp_path / "query_exports").exists()

    asyncio.run(run())


def test_unsupported_image_transport_falls_back_to_final_text(tmp_path):
    async def run():
        star, ev, _, _ = plugin(
            tmp_path, [plan(public_query()), final()], query_agent_output_mode="image"
        )

        async def fail(_result):
            raise RuntimeError("SECRET-TRANSPORT")

        ev.send = fail
        result = json.loads(await star.query_rtlink(ev, "六天段位记录"))
        assert result["delivery"] == "image_failed_text_fallback"
        assert result["result"] == final()["result"]
        assert "SECRET" not in gateway.dumps(result)

    asyncio.run(run())


@pytest.mark.parametrize(
    "bad",
    [
        "<think>SECRET-THOUGHTS</think>",
        {**final(), "reasoning": "SECRET-THOUGHTS"},
    ],
)
def test_malformed_or_reasoning_output_is_never_returned(tmp_path, bad):
    async def run():
        star, ev, _, _ = plugin(tmp_path, [plan(public_query()), bad, final()])
        result = await star.query_rtlink(ev, "六天段位记录")
        assert json.loads(result)["summary"] == final()["summary"]
        assert "SECRET" not in result
        assert "SECRET" not in star.context.calls[-1]["prompt"]

    asyncio.run(run())


def test_final_without_query_is_rejected_before_evidence(tmp_path):
    async def run():
        star, ev, _, _ = plugin(tmp_path, [final(), plan(public_query()), final()])
        result = await star.query_rtlink(ev, "六天段位记录")
        assert json.loads(result)["summary"] == final()["summary"]
        assert len(star.context.calls) == 3

    asyncio.run(run())


def test_child_cannot_call_write_functions(tmp_path):
    async def run():
        star, ev, backend, _ = plugin(
            tmp_path,
            [
                plan({"tool": "set_song_alias", "args": {"song": "765", "alias": "X"}}),
                final(),
                final(),
                final(),
            ],
        )

        async def forbidden(*_args, **_kwargs):
            pytest.fail("write operation must never execute")

        backend.request_alias = forbidden
        text = await star.query_rtlink(ev, "六天段位记录")
        assert "未能" in text and "queries" not in text and "set_song_alias" not in text

    asyncio.run(run())


def test_context_too_small_stops_before_model_call(tmp_path):
    async def run():
        star, ev, _, _ = plugin(tmp_path, [], query_agent_context_tokens=8192)
        text = await star.query_rtlink(ev, "六天段位记录")
        assert "上下文上限" in text and not star.context.calls

    asyncio.run(run())


def test_large_evidence_is_bounded_and_truncation_is_preserved():
    async def run():
        calls, actions = [], [plan(public_query()), final()]

        async def generate(system, prompt, max_tokens):
            assert token_upper_bound(system, prompt, max_tokens) <= 32000
            calls.append(prompt)
            return gateway.dumps(actions.pop(0))

        async def execute(_queries):
            return {
                "source": "test",
                "snapshot": None,
                "results": [
                    {"index": 1, "status": "completed", "data": "资料" * 100000},
                ],
            }

        result = await QueryAgent(AgentSettings(context_tokens=32000)).run(
            "查询目标", generate, execute, "test"
        )
        assert len(calls) == 2
        assert any("未完整" in note for note in result["result"]["limitations"])
        assert "资料资料" not in gateway.dumps(result)

    asyncio.run(run())


def test_source_switch_waits_for_entire_child_and_cancellation_cleans_scope(tmp_path):
    async def run():
        star, ev, _, _ = plugin(tmp_path, [])
        other, _ = make_service()
        other.store = MemoryBindingsStore(
            {"qq": {"player_id": "other", "server": "cn"}}
        )
        star.service.services["sakura"] = other
        started = asyncio.Event()

        async def waiting(**_kwargs):
            started.set()
            await asyncio.Event().wait()

        star.context.llm_generate = waiting
        child = asyncio.create_task(star.query_rtlink(ev, "查询目标"))
        await started.wait()
        switch = asyncio.create_task(star.service.source_text("qq", "sakura"))
        await asyncio.sleep(0)
        assert not switch.done()
        child.cancel()
        with pytest.raises(asyncio.CancelledError):
            await child
        await asyncio.wait_for(switch, 1)
        assert await star.service.current_source("qq") == "sakura"
        assert gateway.ANALYSIS_SCOPE.get() is None and not ev.sent

    asyncio.run(run())


@pytest.mark.parametrize(
    "cfg",
    [
        {"query_agent_context_tokens": False},
        {"query_agent_context_tokens": 100},
        {"query_agent_context_tokens": 10000.1},
        {"query_agent_max_rounds": 1},
        {"query_agent_timeout": -1},
        {"query_agent_output_mode": "invalid"},
        {"query_agent_image_template": "../../custom"},
    ],
)
def test_invalid_config_is_rejected(cfg):
    with pytest.raises(ValueError):
        AgentSettings.from_config(cfg)


def test_provider_error_and_timeout_do_not_reveal_private_process(tmp_path):
    async def run():
        star, ev, _, _ = plugin(tmp_path, [RuntimeError("SECRET-PROVIDER-PAYLOAD")])
        text = await star.query_rtlink(ev, "六天段位记录")
        assert "不可用" in text and "SECRET" not in text
        star, ev, _, _ = plugin(tmp_path, [])

        async def timeout(*_args):
            raise TimeoutError("SECRET")

        star._run_query_agent = timeout
        text = await star.query_rtlink(ev, "六天段位记录")
        assert "超时" in text and "SECRET" not in text

    asyncio.run(run())


def test_template_wraps_long_result_without_clipping(tmp_path):
    report = {
        "summary": "概述",
        "result": {
            "title": "较长标题" * 12,
            "conclusion": "结论" * 450,
            "rows": [{"label": "项目" * 24, "value": "值" * 200} for _ in range(12)],
            "limitations": ["限制" * 80] * 4,
        },
        "source": "菌菌",
    }
    path = tmp_path / "long.png"
    render_query_result(report, path)
    image = Image.open(path)
    assert image.width == 1440 and 3000 < image.height < 12000


def test_only_owned_generated_result_images_are_rotated(tmp_path):
    owner = "0" * 16
    paths = []
    for index in range(8):
        path = tmp_path / f"query-{owner}-{index:032x}.png"
        path.write_bytes(b"owned-output")
        paths.append(path)
    unrelated = tmp_path / f"query-{owner}-user-upload.png"
    unrelated.write_bytes(b"user-data")
    other = tmp_path / f"query-{'1' * 16}-{'a' * 32}.png"
    other.write_bytes(b"other-user")
    prune_query_results(tmp_path, owner, paths[-1])
    assert len(list(tmp_path.glob(f"query-{owner}-*.png"))) == 6
    assert unrelated.exists() and other.exists() and paths[-1].exists()


def test_prompt_contains_domain_knowledge_and_all_read_capabilities():
    text = system_prompt()
    for name in gateway.OPERATIONS:
        assert name in text
    for word in ("魂槽", "分支", "年度", "不是段位", "未绑定", "失误小节"):
        assert word in text


def test_astrbot_injected_plugin_config_takes_precedence_over_global_config(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(main.StarTools, "get_data_dir", lambda _: str(tmp_path))
    config = {"chart_library_auto_install": False, "query_agent_context_tokens": 32000}

    async def run():
        star = main.RTLinkPlugin(
            mock.Context({"query_agent_context_tokens": 8192}), config
        )
        try:
            assert star.cfg is config
            assert AgentSettings.from_config(star.cfg).context_tokens == 32000
        finally:
            await star.terminate()

    asyncio.run(run())
