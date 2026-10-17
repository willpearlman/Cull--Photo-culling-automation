"""Generate fixtures/fake_scores.json so the UI, agent, and solver can be built
before real scores exist. Run: python scripts/make_fake_scores.py

Fixture design (tests/test_solver.py depends on it, do not change casually):
- 10 moments G01-G10, 2 bursts each, 3 frames per burst = 60 frames.
- Paths: shoot/IMG_{1000 + group_index*6 + burst*3 + frame}.ARW
- Frame 0 is sharp. Frame 1 is sharp but blinks in burst 2. Frame 2 is blurry.
- G05 burst 2 frame 0 is overexposed.
- G07 ("Table 7") scores lowest, so a plain top-N cut drops it.
- G08 is candid. G09 burst 2 frame 1 is an intentional eyes-closed moment.
- G10 is entirely blurry, so coverage cannot be met there.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

GROUPS = [
    ("G01", 9, ["group", "indoor"], "Full chapter group"),
    ("G02", 8, ["group", "indoor"], "Table 2"),
    ("G03", 8, ["dance floor", "indoor"], "Dance floor, early"),
    ("G04", 7, ["group", "indoor"], "Table 4"),
    ("G05", 7, ["food", "indoor"], "Dinner service"),
    ("G06", 7, ["dance floor", "indoor"], "Dance floor, late"),
    ("G07", 5, ["group", "indoor"], "Table 7"),
    ("G08", 6, ["candid", "indoor"], "Candids at the bar"),
    ("G09", 6, ["couple", "indoor"], "First dance"),
    ("G10", 7, ["group", "outdoor"], "Patio group"),
]

START = datetime(2026, 10, 10, 21, 0, 0)


def frame(gi, gid, base, tags, label, b, f):
    t = START + timedelta(minutes=6 * gi, seconds=20 * b, milliseconds=200 * f)
    blurry = f == 2 or gid == "G10"
    blink = f == 1 and b == 1
    intentional = gid == "G09" and blink
    overexposed = gid == "G05" and b == 1 and f == 0

    if blurry:
        score, reason = None, None
    elif intentional:
        score, reason = base + 1, "Eyes closed mid-dance, reads as emotion"
    elif blink:
        score, reason = base - 2, "One subject blinking"
    elif f == 0:
        score, reason = base - b, "Clean frame, everyone engaged"
    else:
        score, reason = base - 1 - b, "Good, slightly weaker expression"

    faces = 2 if gid in ("G08", "G09") else 6
    return {
        "path": f"shoot/IMG_{1000 + gi * 6 + b * 3 + f}.ARW",
        "preview": f"previews/IMG_{1000 + gi * 6 + b * 3 + f}.jpg",
        "capture_time": t.isoformat(timespec="milliseconds"),
        "burst_id": f"B{gi * 2 + b + 1:02d}",
        "group_id": gid,
        "group_label": label,
        "sharpness": 90.0 if blurry else (420.0 - gi if f == 0 else 380.0 - gi),
        "exposure_flags": ["overexposed"] if overexposed else [],
        "face_count": faces,
        "eyes_closed_count": 1 if blink else 0,
        "smile_count": faces - 1,
        "scene_tags": list(tags),
        "intentional_eyes_closed": intentional,
        "claude_score": score,
        "claude_reason": reason,
        "final_rating": None,
        "final_label": None,
        "decision_reason": None,
        "overridden": False,
    }


def main():
    images = [
        frame(gi, gid, base, tags, label, b, f)
        for gi, (gid, base, tags, label) in enumerate(GROUPS)
        for b in range(2)
        for f in range(3)
    ]
    out = Path(__file__).resolve().parent.parent / "fixtures" / "fake_scores.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"shoot": "fake-formal", "images": images}, indent=2))
    print(f"Wrote {len(images)} images to {out}")


if __name__ == "__main__":
    main()
