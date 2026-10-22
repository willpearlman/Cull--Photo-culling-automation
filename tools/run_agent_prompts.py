"""Run tests/agent_prompts.json against the live agent and report pass/fail per case.

    python tools/run_agent_prompts.py [--only id1,id2]

Uses a synthetic wedding shoot so results do not depend on which shoot is loaded. Every case
is one live plan call (about 1.2 cents each with claude-opus-5-5). Run after every agent change.
"""
import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cull import agent, config  # noqa: E402

CASES = config.REPO_ROOT / "tests" / "agent_prompts.json"
PRICE_IN, PRICE_OUT = 4.00 / 1e6, 20.00 / 1e6  # claude-opus-5-5, $ per token
MOMENTS = [("getting ready", 50), ("getting ready", 40), ("details", 30), ("ceremony", 80),
           ("first kiss", 20), ("family formals", 70), ("couple portraits", 60), ("reception", 60),
           ("first dance", 30), ("reception", 70), ("rings", 20), ("reception", 70)]


def wedding_shoot():
    images, n = [], 0
    for g, (label, size) in enumerate(MOMENTS, 1):
        for i in range(size):
            tags = [label, "candid" if i % 3 else "portrait", "group" if i % 4 == 0 else "couple"]
            images.append({"path": f"shoot/W{n:04d}.ARW", "group_id": f"G{g:03d}",
                           "group_label": f"{label}, part {g}", "burst_id": f"B{n:04d}",
                           "sharpness": 400.0, "exposure_flags": [], "eyes_closed_count": 0,
                           "scene_tags": tags, "claude_score": 5.0})
            n += 1
    return images


def _cmp(got, want):
    if isinstance(want, list) and len(want) == 2 and want[0] in ("<", ">", "<=", ">="):
        op, n = want
        return got is not None and {"<": got < n, ">": got > n, "<=": got <= n, ">=": got >= n}[op]
    return got == want


def check(plan, expect, images):
    """List of failure messages for one plan (empty = pass)."""
    fails, rules = [], {r["type"]: r for r in plan["rules"]}
    want = expect.get("target")
    if want == "default":
        if not plan["target_defaulted"] or plan["target"] != agent.default_target(images):
            fails.append(f"target {plan['target']} (defaulted={plan['target_defaulted']}), want default")
    elif isinstance(want, list):
        if not want[0] <= plan["target"] <= want[1]:
            fails.append(f"target {plan['target']} not in {want}")
    elif want is not None and plan["target"] != want:
        fails.append(f"target {plan['target']}, want {want}")
    for rtype, fields in expect.get("rules", {}).items():
        if rtype not in rules:
            fails.append(f"missing {rtype} rule")
            continue
        for field, w in fields.items():
            if not _cmp(rules[rtype].get(field), w):
                fails.append(f"{rtype}.{field} = {rules[rtype].get(field)}, want {w}")
    for rtype in expect.get("absent", []):
        if rtype in rules:
            fails.append(f"{rtype} rule should be absent")
    if "prefer_tags" in expect:
        have = set(rules.get("prefer", {}).get("tags", []))
        if not set(expect["prefer_tags"]) <= have:
            fails.append(f"prefer tags {sorted(have)}, want {expect['prefer_tags']}")
    want = expect.get("unsupported")
    got = plan["unsupported"]
    if want is True and not got or want is False and got:
        fails.append(f"unsupported {got}, want {'some' if want else 'none'}")
    elif isinstance(want, list) and not any(w in u.lower() for u in got for w in want):
        fails.append(f"unsupported {got}, want one mentioning {want}")
    want = expect.get("warnings")
    if want is not None and bool(plan["warnings"]) != want:
        fails.append(f"warnings {plan['warnings']}, want {'some' if want else 'none'}")
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    if config.LLM_PROVIDER != "anthropic":
        sys.exit("LLM_PROVIDER is not anthropic (set ANTHROPIC_API_KEY in .env)")
    config.GENRE = "wedding"
    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    if args.only:
        cases = [c for c in cases if c["id"] in args.only.split(",")]
    images = wedding_shoot()

    usage = []
    client = agent._anthropic()
    original = client.beta.messages.create

    def recording(**kw):
        resp = original(**kw)
        usage.append((resp.usage.input_tokens, resp.usage.output_tokens))
        return resp
    client.beta.messages.create = recording

    def run(case):
        try:
            plan = agent.make_plan(case["instruction"], images)
            return case, plan, check(plan, case["expect"], images)
        except Exception as exc:
            return case, None, [f"{type(exc).__name__}: {exc}"]

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(run, cases))
    passed = 0
    for case, plan, fails in results:
        if fails:
            print(f"FAIL {case['id']}: {case['instruction']!r}")
            for f in fails:
                print(f"     - {f}")
            if plan:
                print(f"     plan: target {plan['target']} | " + " | ".join(
                    f"{r['type']} " + ",".join(f"{k}={v}" for k, v in r.items() if k not in ("type", "by"))
                    for r in plan["rules"]) + f" | unsupported {plan['unsupported']}")
        else:
            passed += 1
    cost = sum(i * PRICE_IN + o * PRICE_OUT for i, o in usage)
    print(f"\n{passed} of {len(cases)} passed | {len(usage)} calls | ${cost:.3f} | {time.time() - t0:.0f} s")
    sys.exit(0 if passed == len(cases) else 1)


if __name__ == "__main__":
    main()
