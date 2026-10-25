"""Task-level tools, bounded recommendations, evidence and request isolation."""

import asyncio
import copy
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mock_astrbot as mock

mock.install()
import main
import ai_coach as coach
from service import MemoryBindingsStore, ScoreService


def material():
    charts, rows = {}, []
    cell = {"pattern": "16-3", "bpmBand": "150_179", "noteRatio": .3}
    for song_id in range(1, 15):
        charts[song_id, 4] = {
            "id": song_id, "level": 4, "title": f"歌曲{song_id}", "genre": "test",
            "totalNotes": 1000,
            "feature": {"aiConstant": 10.0, "rhythmProfile": {"cells": [dict(cell)]}},
        }
        if song_id <= 8:
            rows.append({
                "id": song_id, "level": 4, "title": f"歌曲{song_id}",
                "aiConstant": 10., "constant": 10., "accuracy": .98, "rating": 12.,
                "goodCount": 965, "okCount": 30, "ngCount": 5, "poundCount": 0,
                "highScore": 790000, "bestScoreRank": 4,
                "fullComboCount": 0, "dondafulComboCount": 0,
            })
    weak = {**cell, "charts": 8, "rarity": "common", "score": 12.}
    analysis = {
        "records": rows, "summary": {"rating": 12., "hitPrecision": 11.5},
        "meta": {"provider": "菌菌", "server": "cn"},
        "profileSyncedAt": "2026-10-25T00:00:00+00:00",
        "featureAbility": {"strengths": [], "weaknesses": []},
        "rhythmAbility": {"weakest": [weak], "best": [weak]},
        "profileScoreRows": [{"id": 9, "level": 4}],
        "unrated": [{"id": 10, "level": 4, "reason": "谱面版本不匹配"}],
    }
    return analysis, charts


def recommend(goal="general", **kwargs):
    analysis, charts = material()
    return coach.recommendations(analysis, charts, {}, {}, goal=goal, **kwargs)


@pytest.mark.parametrize("goal", ["general", "weakness", "accuracy", "full_combo", "score_rank"])
def test_recommend_five_with_self_contained_evidence(goal):
    text = recommend(goal)
    assert len(re.findall(r"^\d\. ", text, re.M)) == 5
    assert "本次返回 5 首" in text
    assert "Rating 12.0" in text and "同步时间 2026-10-25" in text
    assert "依据" in text and "目标" in text
    assert "过关概率" in text
    assert len(text) <= coach.MAX_CHARS


def test_unplayed_excludes_raw_and_unrated_and_requires_comparable_evidence():
    text = recommend("explore")
    assert "本次返回 4 首" in text and "不足 5 首" in text
    assert "ID 9·" not in text and "ID 10·" not in text
    assert "已玩参考" in text and "配置音符占比" in text
    assert "当前同步数据无游玩记录" in text


@pytest.mark.parametrize("goal", ["general", "score_rank"])
def test_recommend_five_distinct_songs_instead_of_counting_two_difficulties_twice(goal):
    analysis, charts = material()
    charts[1, 5] = {**charts[1, 4], "level": 5}
    analysis["records"].insert(0, {**analysis["records"][0], "level": 5})
    text = coach.recommendations(analysis, charts, {}, {}, goal)
    ids = re.findall(r"^\d\. .*?ID (\d+)·", text, re.M)
    assert len(ids) == len(set(ids)) == 5


def test_do_not_fabricate_weakness_or_new_song_evidence():
    analysis, charts = material()
    analysis["rhythmAbility"] = {"weakest": [], "best": []}
    for goal in ("weakness", "explore"):
        assert "样本不足" in coach.recommendations(analysis, charts, {}, {}, goal)
    text = coach.recommendations(analysis, charts, {}, {}, "general", scope="unplayed")
    assert "本次返回 0 首" in text


def test_full_combo_and_accuracy_exclude_already_completed_charts():
    analysis, charts = material()
    for row in analysis["records"][:6]:
        row["fullComboCount"] = row["dondafulComboCount"] = 1
        row["accuracy"] = 1
    for goal in ("full_combo", "accuracy"):
        text = coach.recommendations(analysis, charts, {}, {}, goal)
        assert "本次返回 2 首" in text
        assert "ID 1·" not in text


def test_difficulty_and_difficulty_band_are_respected():
    analysis, charts = material()
    for row in analysis["records"][2:]:
        row["aiConstant"] = 30.
        row["rating"] = 0
    text = coach.recommendations(analysis, charts, {}, {}, "general", level=4)
    # Median of top played constants is 30: only charts near that median qualify.
    assert "ID 1·" not in text and "ID 2·" not in text
    assert "暂无已评级成绩" in coach.recommendations(analysis, charts, {}, {}, level=5)


def test_branch_route_not_replaced_by_master_features():
    analysis, charts = material()
    row = analysis["records"][0]
    row["branchProfile"] = "normal"
    charts[1, 4]["branchProfiles"] = [{
        "key": "normal", "paths": ["N"], "totalNotes": 900,
        "feature": {"aiConstant": 10., "rhythmProfile": {"cells": []}},
        "configurationRhythmProfile": {},
    }]
    text = coach.recommendations(analysis, charts, {}, {}, "weakness")
    assert "ID 1·" not in text
    charts[11, 4]["branchProfiles"] = charts[1, 4]["branchProfiles"]
    text = coach.recommendations(analysis, charts, {}, {}, "explore")
    assert "ID 11·" not in text
    text = coach.song_brief(charts, 1, 4, analysis)
    assert "normal" in text and "音符 900" in text
    assert "谱面参考：" not in text


def test_rank_recommendation_preserves_real_thresholds_and_branch_exclusion():
    analysis, charts = material()
    analysis["records"][0]["branchProfile"] = "normal"
    rank_data = {"songs": {f"{i}|4": {"ceiling": 1000000, "top": 1000000, "rolls": 0}
                           for i in range(1, 9)}}
    text = coach.recommendations(analysis, charts, rank_data, {}, "score_rank", target_rank=5)
    assert "ID 1·" not in text and "分支成绩不参与" in text
    assert "790000 → 800000" in text and "实测门槛" in text
    assert "缺少该谱连打秒数资料" in text


def test_missing_and_unrated_song_are_not_presented_as_unplayed():
    analysis, charts = material()
    text = coach.song_brief(charts, 10, 4, analysis)
    assert "已玩但未评级" in text and "版本不匹配" in text
    text = coach.song_brief(charts, 11, 4, None, "当前数据源尚未绑定")
    assert "不能判断是否游玩" in text and "尚未绑定" in text
    assert "公共谱面库" in text


def test_response_stays_bounded_and_keeps_five_candidates_with_long_titles():
    analysis, charts = material()
    for row in [*analysis["records"], *charts.values()]:
        row["title"] = "长标题" * 1000
    for goal in ("general", "explore", "score_rank"):
        text = coach.recommendations(analysis, charts, {}, {}, goal)
        assert len(text) <= coach.MAX_CHARS
        assert len(re.findall(r"^\d\. ", text, re.M)) == (4 if goal == "explore" else 5)
        assert coach.LIMITATION in text


def test_exactly_four_tools_are_registered():
    tools = {getattr(method, "_llm_tool_name") for method in vars(main.RTLinkPlugin).values()
             if hasattr(method, "_llm_tool_name")}
    assert tools == {"get_player_overview", "recommend_practice", "query_song_brief", "evaluate_player_dan"}


def test_request_budget_deduplicates_concurrent_calls_and_resets_per_message():
    async def run():
        calls = []

        class Service:
            async def get_ai_overview_text(self, qq):
                calls.append(qq)
                await asyncio.sleep(0)
                return "概览材料"

            async def recommend_practice_text(self, *args):
                calls.append(args)
                return "推荐材料"

            async def get_song_brief_text(self, *args):
                raise AssertionError("budget must prevent this work")

        plugin = object.__new__(main.RTLinkPlugin)
        plugin.service = Service()
        event = mock.AstrMessageEvent("qq", True, False, "")
        results = await asyncio.gather(plugin.get_player_overview(event), plugin.get_player_overview(event))
        assert results[0] == "概览材料" and "复用已有结果" in results[1]
        assert len(calls) == 1
        assert await plugin.recommend_practice(event) == "推荐材料"
        assert "预算已用完" in await plugin.query_song_brief(event, "夏祭")
        next_event = mock.AstrMessageEvent("qq", True, False, "")
        assert await plugin.get_player_overview(next_event) == "概览材料"
        assert len(calls) == 3
    asyncio.run(run())


@pytest.mark.parametrize("args", [
    {"level": "3"}, {"level": "不认识"}, {"target_rank": "不存在"},
    {"goal": "oops"}, {"scope": "oops"}, {"goal": "accuracy", "scope": "unplayed"},
    {"goal": "explore", "scope": "played"}, {"goal": "general", "target_rank": "金雅"},
])
def test_invalid_args_do_not_sync(args):
    service = object.__new__(ScoreService)
    asyncio.run(service.recommend_practice_text("qq", **args))


def test_service_recommendation_uses_one_snapshot_without_secondary_queries():
    async def run():
        service = ScoreService(MemoryBindingsStore(), lambda _: None, material()[1])
        count = 0

        async def snapshot(qq):
            nonlocal count
            count += 1
            return copy.deepcopy(material()[0]), ""

        service._get_analysis = snapshot
        text = await service.recommend_practice_text("qq")
        assert count == 1 and "本次返回 5 首" in text
        text = await service.recommend_practice_text("qq", "score_rank", "4", "金雅")
        assert count == 2 and "目标评价：金雅" in text
    asyncio.run(run())


def test_single_song_alias_and_unbound_public_data():
    async def run():
        analysis, charts = material()
        service = ScoreService(MemoryBindingsStore(), lambda _: None, charts)
        text = await service.get_song_brief_text("qq", "1", "4")
        assert "ID 1·鬼" in text and "尚未绑定" in text and "谱面参考" in text
        assert "难度冲突" in await service.get_song_brief_text("qq", "鬼歌曲1", "里")
        assert "请提供单首" in await service.get_song_brief_text("qq", "")
        service._builtin_alias_map = {"测试别名": 1}
        text = await service.get_song_brief_text("qq", "测试别名", "鬼")
        assert "ID 1·鬼" in text
    asyncio.run(run())
