"""Moment grouping (no API).

Sort frames by capture time, then filename. A gap of more than
config.MOMENT_GAP_SECONDS from the previous frame starts a new moment. Time gap
is the only split signal; scene tags only feed the label.

Label = "<dominant tag>, <start>-<end>", where the dominant tag is the most
common primary tag in the moment (first of group, couple, dance floor, food,
detail, portrait in each frame's scene_tags). "moment" when no frame has one.

run(images, cached) recomputes every image and ignores cached, returning
{path: {"group_id": ..., "group_label": ...}} for all images.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import PurePosixPath

from . import config

PRIMARY_TAGS = ["group", "couple", "dance floor", "food", "detail", "portrait"]


def _parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _primary_tag(row):
    tags = row.get("scene_tags")
    if not tags:
        return None
    for tag in PRIMARY_TAGS:
        if tag in tags:
            return tag
    return None


def _dominant_tag(moment):
    """Most common primary tag; ties go to the tag seen first in the moment."""
    counts = Counter(r["_primary"] for r in moment if r["_primary"])
    if not counts:
        return None
    return counts.most_common(1)[0][0]  # Counter keeps first-seen order on ties


def _fmt_clock(dt):
    """9:40AM style, hour with no leading zero, minute zero-padded."""
    hour = dt.hour % 12 or 12
    return f"{hour}:{dt.minute:02d}", "AM" if dt.hour < 12 else "PM"


def _label(primary, start, end):
    name = primary or "moment"
    if start is None:
        return name
    s_time, s_ap = _fmt_clock(start)
    if end is None or end == start:
        return f"{name}, {s_time}{s_ap}"
    e_time, e_ap = _fmt_clock(end)
    if s_ap == e_ap:
        return f"{name}, {s_time}-{e_time}{e_ap}"
    return f"{name}, {s_time}{s_ap}-{e_time}{e_ap}"


def run(images: list[dict], cached: dict) -> dict:
    rows = [dict(img) for img in images]
    for row in rows:
        row["_time"] = _parse_time(row.get("capture_time"))
        row["_primary"] = _primary_tag(row)

    # Sort by capture time, then filename for stable order within the same second.
    rows.sort(key=lambda r: (
        r["_time"] or datetime.min,
        PurePosixPath(r.get("path") or "").name,
    ))

    moments = []  # list of lists of rows
    current = []
    for row in rows:
        prev = current[-1] if current else None
        if (
            prev is not None
            and row["_time"] and prev["_time"]
            and (row["_time"] - prev["_time"]).total_seconds() > config.MOMENT_GAP_SECONDS
        ):
            moments.append(current)
            current = []
        current.append(row)
    if current:
        moments.append(current)

    out = {}
    for i, moment in enumerate(moments, start=1):
        group_id = f"G{i:03d}"
        times = [r["_time"] for r in moment if r["_time"]]
        start = min(times) if times else None
        end = max(times) if times else None
        label = _label(_dominant_tag(moment), start, end)
        for row in moment:
            out[row["path"]] = {"group_id": group_id, "group_label": label}
    return out
