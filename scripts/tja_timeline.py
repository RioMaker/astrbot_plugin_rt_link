"""Offline TJA timeline extraction, adapted from Taiko Trace parser-v4.

Source: taiko_model/tja_features.py from the 2026-10-14 maintenance snapshot.
Source SHA256: 542dabe2f530a5f97061c936ba2762800f50ce7dbb801c271d6a87fef71195f6
Retains timing semantics; exports events instead of computing model features.
No trained model is loaded and no Rating formula is changed.
"""

from __future__ import annotations

import math
import re
from fractions import Fraction
from pathlib import Path
from typing import Any

SUPPORTED_COURSES = {"oni": 4, "edit": 5}
TAP_NOTES = "1234ABG"
LONG_NOTE_STARTS = "5679D"
SPECIAL_NOTES = "CF"
SUPPORTED_NOTES = f"0{TAP_NOTES}{LONG_NOTE_STARTS}8{SPECIAL_NOTES}"


def _read_tja(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp932"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("unsupported-encoding")


def _strip_comment(line: str) -> str:
    return line.split("//", 1)[0].strip()


def _course_name(value: str) -> str:
    normalized = value.strip().lower()
    numeric = {"3": "oni", "4": "edit"}
    return numeric.get(normalized, normalized)


def _float(value: str, field: str) -> float:
    try:
        number = float(value.strip())
    except ValueError as error:
        raise ValueError(f"invalid-{field}") from error
    if not math.isfinite(number):
        raise ValueError(f"invalid-{field}")
    return number


def _scroll(value: str) -> tuple[float, float]:
    normalized = re.sub(r"\s+", "", value.strip().lower()).replace("i", "j")
    try:
        parsed = complex(normalized)
    except ValueError as error:
        raise ValueError("invalid-scroll") from error
    if not math.isfinite(parsed.real) or not math.isfinite(parsed.imag):
        raise ValueError("invalid-scroll")
    return float(parsed.real), float(parsed.imag)


def _select_routes(
    lines: list[str], requested: str
) -> tuple[list[str], int, str | None, list[str]]:
    selected: list[str] = []
    branch_count = 0
    warnings: list[str] = []
    selected_route: str | None = None
    index = 0
    while index < len(lines):
        line = _strip_comment(lines[index])
        if not line.upper().startswith("#BRANCHSTART"):
            selected.append(line)
            index += 1
            continue

        branch_count += 1
        index += 1
        routes: dict[str, list[str]] = {"N": [], "E": [], "M": []}
        prelude: list[str] = []
        route: str | None = None
        implicit_end = False
        while index < len(lines) and not _strip_comment(
            lines[index]
        ).upper().startswith("#BRANCHEND"):
            marker = _strip_comment(lines[index]).upper()
            if route is not None and marker.startswith("#BRANCHSTART"):
                implicit_end = True
                break
            if marker in ("#N", "#E", "#M"):
                route = marker[1]
            elif route is None:
                prelude.append(lines[index])
            else:
                routes[route].append(lines[index])
            index += 1
        if index >= len(lines):
            implicit_end = True
        if implicit_end:
            warnings.append("implicit-branch-end")
        chosen = (
            requested
            if routes[requested]
            else "M"
            if routes["M"]
            else "E"
            if routes["E"]
            else "N"
        )
        if selected_route is not None and chosen != selected_route:
            warnings.append("mixed-branch-route-fallback")
        selected_route = chosen
        if chosen != requested:
            warnings.append(f"branch-fallback-{chosen.lower()}")
        selected.extend(prelude)
        selected.extend(routes[chosen])
        if index < len(lines) and _strip_comment(lines[index]).upper().startswith(
            "#BRANCHEND"
        ):
            index += 1
    return selected, branch_count, selected_route, warnings


def _split_measures(lines: list[str]) -> list[list[tuple[str, str]]]:
    measures: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    for raw_line in lines:
        line = _strip_comment(raw_line)
        if not line:
            continue
        if line.startswith("#"):
            current.append(("command", line))
            continue
        fragment = ""
        for character in re.sub(r"\s+", "", line):
            if character == ",":
                if fragment:
                    current.append(("notes", fragment))
                    fragment = ""
                measures.append(current)
                current = []
            else:
                fragment += character
        if fragment:
            current.append(("notes", fragment))
    if current and any(kind == "notes" for kind, _value in current):
        measures.append(current)
    return measures


def _parse_chart(
    body: list[str],
    initial_bpm: float,
    initial_scroll: tuple[float, float],
    balloon_values: list[int],
    branch_count: int,
) -> dict:
    measures = _split_measures(body)
    measure_spans = []
    bpm = initial_bpm
    scroll_x, scroll_y = initial_scroll
    measure = Fraction(4, 4)
    time = 0.0
    taps: list[dict[str, Any]] = []
    objects: list[tuple[float, str]] = []
    state_segments: list[dict[str, Any]] = []
    roll_starts: list[tuple[float, Fraction, str]] = []
    rolls: list[dict[str, Any]] = []
    balloon_index = 0
    balloons: list[tuple[float, int, str]] = []
    measure_colors: dict[int, set[str]] = {}
    subdivision_categories: list[str] = []
    offbeat = 0
    triplets = 0
    absolute_quarter = Fraction(0)
    visual_quarter = 0.0
    phrase_epoch = 0
    scroll_mode = "normal"
    gogo = False
    gogo_changes = 0
    adlib_count = 0
    mine_count = 0
    special_events: list[dict[str, Any]] = []
    warnings: list[str] = []

    def append_state_segment(
        start: float, end: float, quarter_start: float, quarter_slope: float
    ) -> None:
        if end <= start:
            return
        segment = {
            "start": start,
            "end": end,
            "bpm": bpm,
            "scrollX": scroll_x,
            "scrollY": scroll_y,
            "scrollMode": scroll_mode,
            "visualQuarterStart": quarter_start,
            "visualQuarterSlope": quarter_slope,
        }
        if state_segments:
            previous = state_segments[-1]
            expected_quarter = float(previous["visualQuarterStart"]) + (
                float(previous["end"]) - float(previous["start"])
            ) * float(previous["visualQuarterSlope"])
            same_state = all(
                previous[key] == segment[key]
                for key in (
                    "bpm",
                    "scrollX",
                    "scrollY",
                    "scrollMode",
                    "visualQuarterSlope",
                )
            )
            if (
                same_state
                and abs(float(previous["end"]) - start) < 1e-9
                and abs(expected_quarter - quarter_start) < 1e-9
            ):
                previous["end"] = end
                return
        state_segments.append(segment)

    def apply_command(command: str, measure_boundary: bool) -> None:
        nonlocal bpm, scroll_x, scroll_y, measure, time, phrase_epoch, visual_quarter
        nonlocal scroll_mode, gogo, gogo_changes
        parts = command.split(maxsplit=1)
        name = parts[0]
        argument = parts[1] if len(parts) > 1 else ""
        upper = name.upper()
        if upper == "#BPMCHANGE":
            new_bpm = _float(argument, "bpm-change")
            if abs(new_bpm) < 1e-9:
                raise ValueError("invalid-bpm-change")
            bpm = new_bpm
        elif upper == "#SCROLL":
            new_scroll_x, new_scroll_y = _scroll(argument)
            scroll_x, scroll_y = new_scroll_x, new_scroll_y
        elif upper == "#MEASURE":
            if not measure_boundary:
                raise ValueError("mid-measure-time-signature")
            numerator, separator, denominator = argument.partition("/")
            try:
                new_measure = Fraction(int(numerator), int(denominator))
            except (ValueError, ZeroDivisionError) as error:
                raise ValueError("invalid-measure") from error
            if not separator or new_measure <= 0:
                raise ValueError("invalid-measure")
            measure = new_measure
        elif upper == "#DELAY":
            delay = _float(argument, "delay")
            if delay > 0:
                append_state_segment(time, time + delay, visual_quarter, 0.0)
            elif delay < 0:
                warnings.append("negative-delay")
            time += delay
            phrase_epoch += delay > 0
        elif upper in ("#BMSCROLL", "#HBSCROLL", "#NMSCROLL"):
            scroll_mode = "normal" if upper == "#NMSCROLL" else upper[1:].lower()
        elif upper == "#GOGOSTART":
            if not gogo:
                gogo_changes += 1
            gogo = True
        elif upper == "#GOGOEND":
            if gogo:
                gogo_changes += 1
            gogo = False
        elif upper not in (
            "#BARLINEON",
            "#BARLINEOFF",
            "#SECTION",
            "#LEVELHOLD",
            "#SENOTECHANGE",
        ):
            warnings.append(f"unsupported-{upper[1:].lower()}")

    for measure_index, parts in enumerate(measures):
        measure_start = time
        first_tap = len(taps)
        note_count = sum(len(value) for kind, value in parts if kind == "notes")
        slots = max(1, note_count)
        commands: dict[int, list[str]] = {}
        notes: list[str] = []
        for kind, value in parts:
            if kind == "command":
                commands.setdefault(len(notes), []).append(value)
            else:
                notes.extend(value)
        if not notes:
            notes = ["0"]

        measure_commands = []
        for command_slot, command_values in list(commands.items()):
            retained = []
            for command in command_values:
                if command.split(maxsplit=1)[0].upper() == "#MEASURE":
                    measure_commands.append((command_slot, command))
                else:
                    retained.append(command)
            if retained:
                commands[command_slot] = retained
            else:
                commands.pop(command_slot, None)
        for command_slot, command in measure_commands:
            if command_slot:
                warnings.append("mid-measure-time-signature-applied-to-whole-measure")
            apply_command(command, True)

        for slot, note in enumerate(notes):
            for command in commands.get(slot, []):
                apply_command(command, slot == 0)

            if note.upper() not in SUPPORTED_NOTES:
                raise ValueError("invalid-note")
            note = note.upper()
            quarter_length = Fraction(
                4 * measure.numerator, measure.denominator * slots
            )
            slot_duration = 60.0 * float(quarter_length) / abs(bpm)
            segment_start = time
            segment_end = time + slot_duration
            append_state_segment(segment_start, segment_end, visual_quarter, bpm / 60.0)

            if note in TAP_NOTES:
                color = "dual" if note == "G" else "don" if note in "13A" else "ka"
                position = Fraction(
                    slot * 4 * measure.numerator, measure.denominator * slots
                )
                if position.denominator != 1:
                    offbeat += 1
                if position.denominator % 3 == 0:
                    triplets += 1
                denominator = quarter_length.denominator
                category = (
                    str(denominator)
                    if denominator in (1, 2, 3, 4, 6, 8, 12)
                    else "other"
                )
                subdivision_categories.append(category)
                taps.append(
                    {
                        "time": time,
                        "end": segment_end,
                        "note": note,
                        "color": color,
                        "big": note in "34ABG",
                        "joint": note in "AB",
                        "dual": note == "G",
                        "measure": measure_index,
                        "quarter": absolute_quarter,
                        "visualQuarter": visual_quarter,
                        "measurePosition": position,
                        "bpm": bpm,
                        "scroll": scroll_x,
                        "scrollY": scroll_y,
                        "scrollMagnitude": abs(complex(scroll_x, scroll_y)),
                        "effectiveScrollMagnitude": 1.0
                        if scroll_mode == "bmscroll"
                        else abs(complex(scroll_x, scroll_y)),
                        "visualSpeed": abs(bpm)
                        * (
                            1.0
                            if scroll_mode == "bmscroll"
                            else abs(complex(scroll_x, scroll_y))
                        ),
                        "scrollMode": scroll_mode,
                        "gogo": gogo,
                        "phraseEpoch": phrase_epoch,
                    }
                )
                if color in ("don", "ka"):
                    measure_colors.setdefault(measure_index, set()).add(color)
                objects.append((time, note))
            elif note in LONG_NOTE_STARTS:
                if roll_starts:
                    warnings.append("repeated-long-note-head")
                else:
                    roll_starts.append((time, absolute_quarter, note))
                objects.append((time, note))
            elif note == "8":
                if not roll_starts:
                    warnings.append("orphan-roll-end")
                else:
                    started, started_quarter, roll_type = roll_starts.pop()
                    rolls.append(
                        {
                            "start": started,
                            "end": time,
                            "startQuarter": started_quarter,
                            "endQuarter": absolute_quarter,
                            "type": roll_type,
                        }
                    )
                    if roll_type in "79D":
                        balloon_count = (
                            balloon_values[balloon_index]
                            if balloon_index < len(balloon_values)
                            else 0
                        )
                        if not balloon_count:
                            warnings.append("missing-balloon-value")
                        duration = max(time - started, 1e-9)
                        balloons.append((duration, balloon_count, roll_type))
                        rolls[-1]["requiredHits"] = balloon_count or None
                        balloon_index += 1
                    objects.append((time, note))
            elif note in SPECIAL_NOTES:
                adlib_count += note == "F"
                mine_count += note == "C"
                special_events.append(
                    {
                        "time": time,
                        "end": segment_end,
                        "quarter": absolute_quarter,
                        "note": note,
                    }
                )
                objects.append((time, note))
            time = segment_end
            absolute_quarter += quarter_length
            visual_quarter += math.copysign(float(quarter_length), bpm)

        for command in commands.get(len(notes), []):
            apply_command(command, True)

        measure_spans.append(
            {
                "measure": measure_index + 1,
                "start": measure_start,
                "end": time,
                "firstTap": first_tap,
                "lastTap": len(taps),
            }
        )

    if roll_starts:
        started, started_quarter, roll_type = roll_starts.pop()
        if time > started:
            rolls.append(
                {
                    "start": started,
                    "end": time,
                    "startQuarter": started_quarter,
                    "endQuarter": absolute_quarter,
                    "type": roll_type,
                }
            )
        warnings.append("unclosed-roll")
    if not taps or not objects:
        raise ValueError("empty-chart")

    if balloon_index < len(balloon_values):
        warnings.append("unused-balloon-values")
    return {
        "taps": taps,
        "rolls": rolls,
        "states": state_segments,
        "measures": measure_spans,
        "warnings": sorted(set(warnings)),
        "duration": time,
        "specialCount": len(special_events),
    }


def parse_timelines(path: Path) -> list[dict]:
    """Export single-player Oni/Edit timelines, keeping each branch separately.

    Times are seconds from #START, not audio timestamps. OFFSET is retained as
    metadata only. A branch request that must fall back is explicitly warned.
    """
    lines = _read_tja(path).splitlines()
    global_meta, chart_meta, result = {}, {}, []
    course = ""
    index = 0
    while index < len(lines):
        line = _strip_comment(lines[index])
        if line.upper().startswith("#START"):
            suffix = line[6:].strip().upper()
            index += 1
            body = []
            while index < len(lines) and not _strip_comment(
                lines[index]
            ).upper().startswith("#END"):
                body.append(lines[index])
                index += 1
            if index >= len(lines):
                raise ValueError("unclosed-chart")
            meta = {**global_meta, **chart_meta}
            if (
                course in SUPPORTED_COURSES
                and suffix not in ("P1", "P2")
                and meta.get("STYLE", "single").lower() != "double"
            ):
                bpm = _float(meta.get("BPM", ""), "bpm")
                if abs(bpm) < 1e-9:
                    raise ValueError("invalid-bpm")
                branches = any(
                    _strip_comment(v).upper().startswith("#BRANCHSTART") for v in body
                )
                routes = {}
                for requested in ("N", "E", "M") if branches else ("single",):
                    selected, count, route, warnings = _select_routes(
                        body, requested if branches else "M"
                    )
                    balloon_key = {
                        "N": "BALLOONNOR",
                        "E": "BALLOONEXP",
                        "M": "BALLOONMAS",
                    }.get(route, "")
                    values = meta.get(balloon_key) or meta.get("BALLOON", "")
                    balloons = [int(v.strip()) for v in values.split(",") if v.strip()]
                    timeline = _parse_chart(
                        selected,
                        bpm,
                        _scroll(meta.get("HEADSCROLL", "1")),
                        balloons,
                        count,
                    )
                    timeline["warnings"] = sorted(set(timeline["warnings"] + warnings))
                    routes[requested] = timeline
                occurrence = 1 + sum(c["course"] == course for c in result)
                result.append(
                    {
                        "course": course,
                        "courseOccurrence": occurrence,
                        "level": SUPPORTED_COURSES[course],
                        "stars": meta.get("LEVEL"),
                        "offset": _float(meta.get("OFFSET", "0"), "offset"),
                        "routes": routes,
                    }
                )
        elif ":" in line and not line.startswith("#"):
            key, value = line.split(":", 1)
            key, value = key.strip().upper(), value.strip()
            if key == "COURSE":
                course, chart_meta = _course_name(value), {"COURSE": value}
            elif course and key in {
                "LEVEL",
                "BALLOON",
                "BALLOONNOR",
                "BALLOONEXP",
                "BALLOONMAS",
                "STYLE",
                "BPM",
                "HEADSCROLL",
                "OFFSET",
            }:
                chart_meta[key] = value
            elif not course:
                global_meta[key] = value
        index += 1
    return result
