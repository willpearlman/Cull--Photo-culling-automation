"""Acceptance tests for cull/solver.py. These define the solver contract.
Kiro implements the solver until every test passes. Do not edit these tests
to make them pass. Run: pytest tests/test_solver.py -q

Fixture: fixtures/fake_scores.json (see scripts/make_fake_scores.py).
"""
import copy
import json
from pathlib import Path

import pytest

from cull.solver import run_plan, top_n

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "fake_scores.json"
LABELS = {"Red", "Yellow", "Green", "Blue", "Purple", None}

TABLE_7_BEST = "shoot/IMG_1036.ARW"   # G07, lowest-scoring moment
G09_INTENTIONAL = "shoot/IMG_1052.ARW"  # eyes closed during first dance
G05_OVEREXPOSED = "shoot/IMG_1027.ARW"
G01_BLURRY = "shoot/IMG_1002.ARW"
G01_BURST_DUP = "shoot/IMG_1001.ARW"   # sharp, no blink, loses its burst
G08_SECOND = "shoot/IMG_1045.ARW"      # candid, wins only with prefer rule


@pytest.fixture
def images():
    return json.loads(FIXTURE.read_text())["images"]


def plan(target, *, cap=3, prefer=None, allow_intentional=True):
    rules = [
        {"type": "filter", "max_eyes_closed": 0, "allow_intentional": allow_intentional,
         "min_sharpness": 150, "drop_exposure_flags": True},
        {"type": "dedupe_bursts", "keep": 1},
        {"type": "coverage", "by": "group_id", "min_per_group": 1},
        {"type": "cap", "by": "group_id", "max_per_group": cap},
    ]
    if prefer:
        rules.append({"type": "prefer", "tags": prefer, "weight": 1.5})
    return {"target": target, "rules": rules}


def group_of(images, path):
    return next(i["group_id"] for i in images if i["path"] == path)


# --- The demo moment: score-and-cut drops a group, coverage restores it ---

def test_top_n_baseline_drops_table_7(images):
    picks = top_n(images, 10)
    assert len(picks) == 10
    assert "G07" not in {group_of(images, p) for p in picks}


def test_coverage_restores_table_7(images):
    result = run_plan(images, plan(10))
    assert len(result["picks"]) == 10
    assert TABLE_7_BEST in result["picks"]
    assert "coverage" in result["decisions"][TABLE_7_BEST]["reason"].lower()


def test_every_coverable_group_has_a_pick(images):
    result = run_plan(images, plan(10))
    covered = {group_of(images, p) for p in result["picks"]}
    assert covered == {f"G0{i}" for i in range(1, 10)}


def test_unmet_group_is_reported(images):
    result = run_plan(images, plan(10))
    assert result["unmet_groups"] == ["G10"]
    coverage = next(r for r in result["report"] if r["type"] == "coverage")
    assert coverage["met"] is False
    assert "G10" in coverage["detail"]


# --- Filters and reasons ---

def test_every_image_gets_a_decision_and_reason(images):
    result = run_plan(images, plan(10))
    assert set(result["decisions"]) == {i["path"] for i in images}
    for d in result["decisions"].values():
        assert d["reason"]
        assert d["rating"] in (1, 5)
        assert d["label"] in LABELS


def test_reject_reasons_name_the_cause(images):
    d = run_plan(images, plan(10))["decisions"]
    assert "blur" in d[G01_BLURRY]["reason"].lower()
    assert "overexposed" in d[G05_OVEREXPOSED]["reason"].lower()
    assert "burst" in d[G01_BURST_DUP]["reason"].lower()


def test_picks_rated_5_rejects_rated_1(images):
    result = run_plan(images, plan(10))
    for path, d in result["decisions"].items():
        assert d["rating"] == (5 if path in result["picks"] else 1)


def test_intentional_eyes_closed_kept_when_allowed(images):
    assert G09_INTENTIONAL in run_plan(images, plan(10))["picks"]


def test_intentional_eyes_closed_rejected_when_not_allowed(images):
    d = run_plan(images, plan(10, allow_intentional=False))["decisions"]
    assert d[G09_INTENTIONAL]["rating"] == 1
    assert "eyes closed" in d[G09_INTENTIONAL]["reason"].lower()


# --- Caps, prefer, target ---

def test_cap_limits_picks_per_group_and_reports_short_target(images):
    result = run_plan(images, plan(17, cap=1))
    groups = [group_of(images, p) for p in result["picks"]]
    assert len(groups) == len(set(groups)) == 9
    target = next(r for r in result["report"] if r["type"] == "target")
    assert target["met"] is False


def test_prefer_changes_fill_order(images):
    assert G08_SECOND not in run_plan(images, plan(11))["picks"]
    assert G08_SECOND in run_plan(images, plan(11, prefer=["candid"]))["picks"]


# --- Overrides and determinism ---

def test_override_forces_pick_and_reject(images):
    imgs = copy.deepcopy(images)
    for i in imgs:
        if i["path"] == G01_BLURRY:
            i.update(overridden=True, final_rating=5)
        if i["path"] == TABLE_7_BEST:
            i.update(overridden=True, final_rating=1)
    result = run_plan(imgs, plan(10))
    assert G01_BLURRY in result["picks"]
    assert TABLE_7_BEST not in result["picks"]
    assert "override" in result["decisions"][G01_BLURRY]["reason"].lower()
    assert len(result["picks"]) == 10


def test_deterministic(images):
    a = run_plan(images, plan(10))
    b = run_plan(copy.deepcopy(images), plan(10))
    assert a["picks"] == b["picks"]


def test_does_not_mutate_input(images):
    before = copy.deepcopy(images)
    run_plan(images, plan(10))
    assert images == before
