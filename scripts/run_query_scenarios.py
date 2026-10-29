"""Exercise the real public-data query path with externally supplied model actions.

No model/provider API or player account is accessed. Only the AstrBot host and
message transport are stubbed. A separate model reads requests/*.json and writes
one protocol JSON action to responses/<same-name>.json. --replay reuses previously
captured actions while all queries, persistence, validation and rendering rerun.

Example:
    python scripts/run_query_scenarios.py --output D:/tmp/rtlink-scenarios
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "test"))

import mock_astrbot as mock

mock.install()

import main
from query_agent import token_upper_bound

CASES = {
    "simple": "六天在哪个段位？只查归属。",
    "create": (
        "我会连续整理不同歌曲的段位归属和里谱配置；希望把这套查询保存为可复用的参数化工具。"
        "这次先查六天，列年度区域曲序，以及里谱音符数、平均密度、两秒峰值密度和主要配置。"
    ),
    "reuse": (
        "用现有的相同查询工具，查 The Future of the 太鼓ドラム 的段位归属和里谱配置。"
    ),
    "missing": "按同样方式查彁的段位归属和里谱配置，没收录的内容请直说。",
    "simple_after": "北埼玉属于哪些段位？只查段位归属。",
}


def write_json(path, value):
    """Replace complete JSON atomically so the external worker never sees half."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


class SavedConfig(dict):
    def __init__(self, path):
        self.path = path
        defaults = {
            "query_agent_output_mode": "image",
            "query_agent_context_tokens": 200000,
            "query_agent_max_rounds": 4,
            "query_agent_timeout": 600,
            "query_agent_tools_enabled": True,
            "query_agent_tools_per_session": 3,
            "query_agent_tools_total": 20,
            "query_agent_custom_tools": [],
            "chart_library_auto_install": True,
            "chart_library_download_url": "",
        }
        if path.exists():
            defaults.update(json.loads(path.read_text(encoding="utf-8")))
        super().__init__(defaults)
        self.save_count = 0
        write_json(self.path, dict(self))

    def save_config(self):
        write_json(self.path, dict(self))
        self.save_count += 1


class BrokerContext:
    def __init__(self, output, replay=None):
        self.output = output
        self.replay = replay
        self.case = ""
        self.calls = []
        self.actions = []

    def begin(self, case):
        self.case = case
        self.calls = []
        self.actions = []

    async def get_current_chat_provider_id(self, umo):
        if umo != "local-scenario:group":
            raise AssertionError("unexpected test conversation")
        return "independent-model-file-broker"

    async def llm_generate(self, **kwargs):
        if kwargs["contexts"] or kwargs["tools"] or kwargs["image_urls"]:
            raise AssertionError("child context must remain independent")
        if kwargs["chat_provider_id"] != "independent-model-file-broker":
            raise AssertionError("unexpected model route")
        self.calls.append(kwargs)
        name = f"{self.case}-{len(self.calls)}.json"
        request_path = self.output / "requests" / name
        response_path = self.output / "responses" / name
        if response_path.exists() and self.replay is None:
            raise FileExistsError(f"Refusing a stale broker response: {name}")
        write_json(request_path, kwargs)
        print(f"MODEL_REQUEST {request_path}", flush=True)
        if self.replay is not None:
            raw = (self.replay / name).read_text(encoding="utf-8-sig")
            write_json(response_path, json.loads(raw))
        else:
            deadline = time.monotonic() + 180
            while not response_path.exists():
                if time.monotonic() >= deadline:
                    raise TimeoutError("model broker response timed out")
                await asyncio.sleep(0.2)
            raw = response_path.read_text(encoding="utf-8-sig")
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = {"action": "malformed"}
        self.actions.append(parsed)
        return SimpleNamespace(completion_text=raw)


class ScenarioEvent(mock.AstrMessageEvent):
    def __init__(self, question):
        super().__init__("local-public-data-only", False, False, question)
        self.unified_msg_origin = "local-scenario:group"
        self.sent = []

    async def send(self, result):
        path = Path(result)
        if not path.is_file() or path.suffix != ".png":
            raise AssertionError("image delivery must reference a real PNG")
        self.sent.append(path)


async def make_plugin(output, context, network_attempts):
    config = SavedConfig(output / "config.json")
    main.StarTools.get_data_dir = staticmethod(lambda _: str(output / "runtime"))
    plugin = main.RTLinkPlugin(context, config)

    def forbidden_client(*_args, **_kwargs):
        network_attempts.append("player_api")
        raise AssertionError("public-data scenarios must not access player APIs")

    for backend in plugin.service.services.values():
        backend._client_factory = forbidden_client
    if plugin.chart_installer._task is not None:
        await plugin.chart_installer._task
    library = plugin.service.services["kinoko"].chart_library
    status = await asyncio.to_thread(library.status)
    if not status.get("available"):
        await plugin.terminate()
        raise RuntimeError("bundled chart library failed to install")
    return plugin, status


def tool_definitions(config):
    result = []
    for entry in config.get("query_agent_custom_tools", []):
        row = dict(entry)
        row["definition"] = json.loads(row["definition"])
        result.append(row)
    return result


def assess(case, metrics, result):
    checks = {
        "one_main_call": metrics["main_calls"] == 1,
        "image_delivered": metrics["image_count"] == 1,
        "main_final_only": set(result) <= {"summary", "delivery", "message"}
        and result.get("delivery") == "image_sent",
        "context_within_limit": metrics["max_context_bound"] <= 200000,
        "has_final_action": "final" in metrics["actions"],
        "validated_final_report": metrics["validated_final_report"],
        "all_queries_completed": bool(metrics["query_results"])
        and all(row["status"] == "completed" for row in metrics["query_results"]),
        "short_main_summary": len(result.get("summary", "")) <= 160,
    }
    if case in ("simple", "simple_after", "missing", "reuse"):
        checks["no_new_tools"] = metrics["tools_before"] == metrics["tools_after"]
        checks["no_saves"] = metrics["saves_count"] == 0
    if case == "create":
        checks["created_bounded_tools"] = (
            1 <= metrics["tools_after"] - metrics["tools_before"] <= 3
        )
        checks["used_custom_tool"] = metrics["used_custom_tool"]
    if case == "reuse":
        checks["used_custom_tool"] = metrics["used_custom_tool"]
        checks["reloaded_config"] = metrics["reloaded"]
    if case in ("create", "reuse"):
        checks["combined_queries_completed"] = {
            "query_dan_course",
            "get_chart_analysis",
        } <= {
            row["tool"]
            for row in metrics["query_results"]
            if row["status"] == "completed"
        }
    return checks


async def run(output, cases, replay):
    if output.exists() and any(output.iterdir()):
        raise ValueError("--output must be empty to avoid reusing stale tool state")
    output.mkdir(parents=True, exist_ok=True)
    (output / "responses").mkdir(exist_ok=True)
    context = BrokerContext(output, replay)
    attempts = []
    plugin, library_status = await make_plugin(output, context, attempts)
    manifest = {
        "mode": "replay" if replay else "external-independent-model-broker",
        "boundaries": [
            "Real RTLinkPlugin query, registry, gateway, bundled data and renderer.",
            "AstrBot host/events and message delivery are local adapters.",
            "No production AstrBot provider, QQ delivery or player API validation.",
            "Broker actions are supplied by a separate model; no expected actions are injected.",
        ],
        "library_status": library_status,
        "resource_sha256": {
            name: hashlib.sha256((ROOT / "resource" / name).read_bytes()).hexdigest()
            for name in (
                "charts.v1.json.gz",
                "dan_courses.v1.json.gz",
                "aliases.v1.json.gz",
            )
        },
        "cases": [],
    }
    try:
        for case in cases:
            reloaded = case == "reuse"
            if reloaded:
                await plugin.terminate()
                plugin, _ = await make_plugin(output, context, attempts)
            context.begin(case)
            folder = output / case
            folder.mkdir(exist_ok=True)
            before = len(plugin.cfg.get("query_agent_custom_tools", []))
            saves_before = plugin.cfg.save_count
            captured = []
            successful_custom_calls = []
            original_deliver = plugin._deliver_query_report
            store = plugin._query_tool_store
            original_expand, original_apply = store.expand, store.apply

            def record_custom(queries, recorded=successful_custom_calls):
                for query in queries if isinstance(queries, list) else []:
                    if isinstance(query, dict) and str(
                        query.get("tool", "")
                    ).startswith("custom_"):
                        recorded.append(query["tool"])

            def capture_expand(
                queries, *args, expand=original_expand, record=record_custom
            ):
                result = expand(queries, *args)
                record(queries)
                return result

            async def capture_apply(
                *args, apply=original_apply, record=record_custom, **kwargs
            ):
                result = await apply(*args, **kwargs)
                record(kwargs.get("queries"))
                return result

            async def capture(
                event, report, settings, deliver=original_deliver, reports=captured
            ):
                reports.append(report)
                return await deliver(event, report, settings)

            plugin._deliver_query_report = capture
            store.expand, store.apply = capture_expand, capture_apply
            event = ScenarioEvent(CASES[case])
            started = time.monotonic()
            raw = await plugin.query_rtlink(event, CASES[case])
            plugin._deliver_query_report = original_deliver
            store.expand, store.apply = original_expand, original_apply
            result = json.loads(raw)
            if captured:
                write_json(folder / "final-report.json", captured[-1])
            write_json(folder / "main-return.json", result)
            if event.sent:
                shutil.copy2(event.sent[-1], folder / "final.png")
            actions = [a for a in context.actions if isinstance(a, dict)]
            last_prompt = (
                json.loads(context.calls[-1]["prompt"]) if context.calls else {}
            )
            query_results = [
                {"tool": row.get("tool"), "status": row.get("status")}
                for batch in last_prompt.get("materials", [])
                for row in batch.get("results", [])
            ]
            metrics = {
                "case": case,
                "question": CASES[case],
                "model_rounds": len(context.calls),
                "main_calls": event._rtlink_ai_state["calls"],
                "tools_before": before,
                "tools_after": len(plugin.cfg.get("query_agent_custom_tools", [])),
                "saves_count": plugin.cfg.save_count - saves_before,
                "actions": [a.get("action") for a in actions],
                "used_custom_tool": bool(successful_custom_calls),
                "successful_custom_calls": successful_custom_calls,
                "query_results": query_results,
                "validated_final_report": bool(captured and "source" in captured[-1]),
                "image_count": len(event.sent),
                "reloaded": reloaded,
                "max_context_bound": max(
                    (
                        token_upper_bound(
                            c["system_prompt"], c["prompt"], c["max_tokens"]
                        )
                        for c in context.calls
                    ),
                    default=0,
                ),
                "elapsed_seconds": round(time.monotonic() - started, 3),
            }
            checks = assess(case, metrics, result)
            checks["no_player_api_access"] = not attempts
            metrics["checks"] = checks
            metrics["passed"] = all(checks.values())
            write_json(folder / "metrics.json", metrics)
            manifest["cases"].append(metrics)
            manifest["passed"] = all(row["passed"] for row in manifest["cases"])
            write_json(output / "manifest.json", manifest)
            write_json(output / "tools.json", tool_definitions(plugin.cfg))
            print(f"CASE_COMPLETE {case} passed={metrics['passed']}", flush=True)
        return manifest["passed"]
    finally:
        await plugin.terminate()


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", default=",".join(CASES))
    parser.add_argument("--replay", type=Path)
    args = parser.parse_args()
    if not args.output.is_absolute():
        parser.error("--output must be an absolute, isolated test directory")
    cases = args.cases.split(",")
    if not cases or len(set(cases)) != len(cases) or set(cases) - set(CASES):
        parser.error("--cases must contain unique names from: " + ",".join(CASES))
    replay = args.replay.resolve() if args.replay else None
    if replay is not None and not replay.is_dir():
        parser.error("--replay must be the directory containing response JSON files")
    raise SystemExit(0 if asyncio.run(run(args.output.resolve(), cases, replay)) else 1)


if __name__ == "__main__":
    cli()
