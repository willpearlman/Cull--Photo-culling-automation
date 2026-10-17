"""Moment grouping (no API).

Sort frames by capture time, then split into moments:
- a gap of more than 90 s from the previous frame starts a new moment, and
- a change of primary tag starts a new moment, but only once the new tag holds
  for 3 frames in a row (ignores one-frame tag flickers).

Primary tag = first of group, couple, dance floor, food, detail, portrait in a
frame's scene_tags. When scene_tags is null (rekog not run yet), only the
90 s gap rule applies.

run(images, cached) recomputes every image and ignores cached, returning
{path: {"group_id": ..., "group_label": ...}} for all images.
"""
from __future__ import annotations

from datetime import datetime

GAP_SECONDS = 90.0
TAG_CONFIRM = 3  # a new primary tag must hold this many frames to split
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


def _tag_change_confirmed(rows, idx, current):
    """True when rows[idx] onward hold the same new primary tag for TAG_CONFIRM
    frames, confirming a real moment change rather than a one-frame flicker."""
    new_tag = rows[idx].get("_primary")
    if new_tag is None or new_tag == current:
        return False
    run = 0
    for j in range(idx, len(rows)):
        if rows[j].get("_primary") == new_tag:
            run += 1
            if run >= TAG_CONFIRM:
                return True
        else:
            break
    return False


def run(images: list[dict], cached: dict) -> dict:
    rows = [dict(img) for img in images]
    for row in rows:
        row["_time"] = _parse_time(row.get("capture_time"))
        row["_primary"] = _primary_tag(row)

    # Sort by capture time, then path for stable order within the same second.
    rows.sort(key=lambda r: (r["_time"] or datetime.min, r.get("path") or ""))

    moments = []  # list of lists of rows
    current = []
    current_tag = None
    for idx, row in enumerate(rows):
        if not current:
            current = [row]
            current_tag = row["_primary"]
            continue

        prev = current[-1]
        split = False

        # Time-gap rule.
        if row["_time"] and prev["_time"]:
            if (row["_time"] - prev["_time"]).total_seconds() > GAP_SECONDS:
                split = True

        # Primary-tag change rule, confirmed over 3 frames.
        if not split and _tag_change_confirmed(rows, idx, current_tag):
            split = True

        if split:
            moments.append(current)
            current = [row]
            current_tag = row["_primary"]
        else:
            current.append(row)
            if current_tag is None:
                current_tag = row["_primary"]

    if current:
        moments.append(current)

    out = {}
    for i, moment in enumerate(moments, start=1):
        group_id = f"G{i:03d}"
        primary = None
        for row in moment:
            if row["_primary"]:
                primary = row["_primary"]
                break
        times = [r["_time"] for r in moment if r["_time"]]
        start = min(times) if times else None
        end = max(times) if times else None
        label = _label(primary, start, end)
        for row in moment:
            out[row["path"]] = {"group_id": group_id, "group_label": label}
    return out
