"""The prompt suite file is well-formed and its checker works (no API calls)."""
import importlib.util
import json

from cull import config

spec = importlib.util.spec_from_file_location(
    "run_agent_prompts", config.REPO_ROOT / "tools" / "run_agent_prompts.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

KEYS = {"target", "rules", "absent", "prefer_tags", "unsupported", "warnings"}


def test_cases_are_well_formed():
    cases = json.loads(runner.CASES.read_text(encoding="utf-8"))["cases"]
    assert len(cases) >= 40
    assert len({c["id"] for c in cases}) == len(cases)
    for c in cases:
        assert isinstance(c["instruction"], str)
        assert set(c["expect"]) <= KEYS, c["id"]


def test_checker_passes_a_matching_plan_and_reports_each_mismatch():
    images = runner.wedding_shoot()
    assert len(images) == 600
    plan = {"target": 40, "target_defaulted": False, "unsupported": [], "warnings": [],
            "rules": [{"type": "filter", "max_eyes_closed": 0, "allow_intentional": False},
                      {"type": "cap", "by": "group_id", "max_per_group": 4},
                      {"type": "prefer", "tags": ["candid", "ceremony"], "weight": 2}]}
    ok = {"target": 40, "rules": {"cap": {"max_per_group": [">=", 4]}},
          "prefer_tags": ["ceremony"], "unsupported": False, "warnings": False, "absent": ["coverage"]}
    assert runner.check(plan, ok, images) == []
    bad = {"target": 50, "rules": {"filter": {"allow_intentional": True}}, "absent": ["cap"],
           "prefer_tags": ["rings"], "unsupported": ["bride"], "warnings": True}
    assert len(runner.check(plan, bad, images)) == 6
