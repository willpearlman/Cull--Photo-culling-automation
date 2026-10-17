"""Solver stub. AWS and logic lane (Teammate 3), task 8. Contract: .kiro/steering/contracts.md.
Until task 8 lands, the server gets an empty but valid result."""


def run_plan(images, plan):
    return {
        "picks": [],
        "decisions": {i["path"]: {"rating": 1, "label": None, "reason": "Rejected: solver not built yet"}
                      for i in images},
        "report": [{"type": "target", "met": False, "detail": "Solver not built yet"}],
        "unmet_groups": [],
    }


def top_n(images, n):
    return []
