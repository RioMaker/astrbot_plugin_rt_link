"""Deterministic per-measure reference metrics; not a player prediction model."""

from __future__ import annotations

from bisect import bisect_left
from collections import Counter
from itertools import pairwise


def peak_density(times, width):
    """Maximum notes in a half-open fixed-width window, divided by width."""
    left = maximum = 0
    for right, time in enumerate(times):
        while time - times[left] >= width - 1e-9:
            left += 1
        maximum = max(maximum, right - left + 1)
    return maximum / width


def metrics(taps, start, end, states, rolls):
    times = sorted(t["time"] for t in taps)
    gaps = [b - a for a, b in pairwise(times) if b - a > 1e-9]
    transitions = sum(a["color"] != b["color"] for a, b in pairwise(taps))
    # A continuous run is explicitly defined by <= 250 ms between hits.
    longest = current = 1 if taps else 0
    run_start = times[0] if times else start
    longest_seconds = 0.0
    for a, b in pairwise(times):
        if b - a <= 0.25 + 1e-9:
            current += 1
        else:
            current, run_start = 1, b
        longest = max(longest, current)
        longest_seconds = max(longest_seconds, b - run_start)
    active = [s for s in states if s["start"] < end and s["end"] > start]

    def seconds_where(predicate):
        return round(
            sum(
                min(end, s["end"]) - max(start, s["start"])
                for s in active
                if predicate(s)
            ),
            6,
        )

    def effective_scroll(state):
        return (
            1 + 0j
            if state["scrollMode"] == "bmscroll"
            else complex(state["scrollX"], state["scrollY"])
        )

    bpms = [abs(s["bpm"]) for s in active]
    visual = [
        abs(s["bpm"])
        * (
            1
            if s["scrollMode"] == "bmscroll"
            else abs(complex(s["scrollX"], s["scrollY"]))
        )
        for s in active
    ]
    yellow = sum(
        max(0, min(end, r["end"]) - max(start, r["start"]))
        for r in rolls
        if r["type"] in "56"
    )
    balloons = [
        {
            "start": round(r["start"], 6),
            "end": round(r["end"], 6),
            "requiredHits": r.get("requiredHits"),
        }
        for r in rolls
        if r["type"] in "79D" and start <= r["start"] < end
    ]
    sequences = Counter(
        "".join(
            "d" if t["color"] == "don" else "k" if t["color"] == "ka" else "b"
            for t in taps[i : i + 3]
        )
        for i in range(max(0, len(taps) - 2))
        if taps[i + 2]["time"] - taps[i]["time"] <= 0.5 + 1e-9
    )
    subdivisions = Counter()
    for a, b in pairwise(taps):
        quarter_gap = float(b["quarter"] - a["quarter"])
        if quarter_gap > 0:
            division = 4 / quarter_gap
            nearest = min(
                (4, 8, 12, 16, 24, 32, 48, 64), key=lambda n: abs(n - division)
            )
            subdivisions[
                str(nearest) if abs(division - nearest) < 0.01 else "other"
            ] += 1
    return {
        "notes": len(taps),
        "durationSeconds": round(end - start, 6),
        "notesPerSecond": round(len(taps) / (end - start), 4) if end > start else None,
        "peak2sNotesPerSecond": peak_density(times, 2) if taps else 0,
        "minGapSeconds": round(min(gaps), 6) if gaps else None,
        "maxTapFreeSeconds": round(
            max(
                [max(0, end - start)]
                if not times
                else [max(0, times[0] - start), max(0, end - times[-1]), *gaps]
            ),
            6,
        ),
        "maxEquivalent16Bpm": round(15 / min(gaps), 3) if gaps else None,
        "bpmMin": min(bpms) if bpms else None,
        "bpmMax": max(bpms) if bpms else None,
        "visualSpeedMin": round(min(visual), 3) if visual else None,
        "visualSpeedMax": round(max(visual), 3) if visual else None,
        "stateChanges": max(0, len(active) - 1),
        "reverseSeconds": seconds_where(
            lambda s: s["bpm"] * effective_scroll(s).real < 0
        ),
        "stoppedScrollSeconds": seconds_where(
            lambda s: abs(effective_scroll(s)) < 1e-9
        ),
        "complexScrollSeconds": seconds_where(
            lambda s: abs(effective_scroll(s).imag) > 1e-9
        ),
        "delaySeconds": seconds_where(lambda s: s["visualQuarterSlope"] == 0),
        "colorSwitches": transitions,
        "colorSwitchRatio": round(transitions / (len(taps) - 1), 4)
        if len(taps) > 1
        else None,
        "longestRunNotes": longest,
        "longestRunSeconds": round(longest_seconds, 6),
        "yellowRollSeconds": round(yellow, 6),
        "balloons": balloons,
        "gapSubdivisions": dict(subdivisions),
        "topTriplets": [
            {"pattern": k, "count": v} for k, v in sequences.most_common(5)
        ],
    }


def summarize_route(timeline):
    taps, states, rolls = timeline["taps"], timeline["states"], timeline["rolls"]
    # Negative delay can make a chart non-monotonic. Keep a warning and skip
    # time-based derived claims rather than return a plausible false curve.
    invalid_time = "negative-delay" in timeline["warnings"]
    measures = []
    times = sorted(t["time"] for t in taps)
    for span in timeline["measures"]:
        local = taps[span["firstTap"] : span["lastTap"]]
        item = {
            "measure": span["measure"],
            "startSeconds": round(span["start"], 6),
            "endSeconds": round(span["end"], 6),
        }
        item.update(metrics(local, span["start"], span["end"], states, rolls))
        # Include neighboring measures in the 2-second load window, so a bar
        # boundary does not hide a burst. This is separate from local metrics.
        center = (span["start"] + span["end"]) / 2
        item["centered2sNotesPerSecond"] = (
            bisect_left(times, center + 1) - bisect_left(times, center - 1)
        ) / 2
        item["preceding10sNotes"] = bisect_left(times, span["start"]) - bisect_left(
            times, span["start"] - 10
        )
        measures.append(item)
    summary = metrics(taps, 0, timeline["duration"], states, rolls)
    hotspots = {}
    for label, field in (
        ("density", "peak2sNotesPerSecond"),
        ("continuousRun", "longestRunSeconds"),
        ("colorSwitches", "colorSwitches"),
    ):
        hotspots[label] = (
            [
                m["measure"]
                for m in sorted(
                    (m for m in measures if (m[field] or 0) > 0),
                    key=lambda m: (-(m[field] or 0), m["measure"]),
                )[:3]
            ]
            if not invalid_time
            else []
        )
    if invalid_time:
        for item in [summary, *measures]:
            for field in (
                "startSeconds",
                "endSeconds",
                "durationSeconds",
                "notesPerSecond",
                "peak2sNotesPerSecond",
                "centered2sNotesPerSecond",
                "minGapSeconds",
                "maxEquivalent16Bpm",
                "longestRunSeconds",
                "longestRunNotes",
                "yellowRollSeconds",
                "maxTapFreeSeconds",
                "reverseSeconds",
                "stoppedScrollSeconds",
                "complexScrollSeconds",
                "delaySeconds",
                "preceding10sNotes",
            ):
                if field in item:
                    item[field] = None
            item["balloons"] = []
    return {
        "summary": summary,
        "measures": measures,
        "hotspots": hotspots,
        "warnings": timeline["warnings"],
        "timeReliable": not invalid_time,
        "specialNoteCount": timeline["specialCount"],
    }
