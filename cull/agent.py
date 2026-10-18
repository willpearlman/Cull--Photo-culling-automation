"""Instruction -> plan agent. AWS and logic lane (Teammate 3), task 10.

make_plan(instruction, images): one Bedrock Converse call with a forced submit_plan tool.
explain(plan, result): one short call summarising the result in 2 to 3 sentences.
Plan shape: .kiro/steering/contracts.md.
"""
import copy
import json
import re
import sys
import threading
from collections import Counter

import boto3
from botocore.config import Config

from cull import config

PRESETS_PATH = config.REPO_ROOT / "fixtures" / "preset_plans.json"
TAG_VOCAB = ["group", "couple", "candid", "dance floor", "food", "indoor", "outdoor",
             "portrait", "detail"]
RULE_TYPES = ["filter", "dedupe_bursts", "coverage", "cap", "prefer"]
# Words that mean the user is asking about the sharpness threshold itself.
SHARPNESS_WORDS = re.compile(r"sharp|blur|focus|soft|crisp", re.IGNORECASE)

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "target": {"type": "integer", "description": "Number of frames to keep."},
        "rules": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": RULE_TYPES},
                    "max_eyes_closed": {"type": "integer", "description": "filter"},
                    "allow_intentional": {"type": "boolean", "description": "filter"},
                    "min_sharpness": {"type": "number", "description": "filter"},
                    "drop_exposure_flags": {"type": "boolean", "description": "filter"},
                    "keep": {"type": "integer", "description": "dedupe_bursts"},
                    "by": {"type": "string", "enum": ["group_id"],
                           "description": "coverage and cap"},
                    "min_per_group": {"type": "integer", "description": "coverage"},
                    "max_per_group": {"type": "integer", "description": "cap"},
                    "tags": {"type": "array", "items": {"type": "string", "enum": TAG_VOCAB},
                             "description": "prefer"},
                    "weight": {"type": "number", "description": "prefer"},
                },
                "required": ["type"],
            },
        },
    },
    "required": ["target", "rules"],
}

SYSTEM_TEMPLATE = """You turn a photographer's culling instruction into a plan for a rule solver.
Always answer by calling submit_plan exactly once. Never ask questions.

Plan = {{"target": int, "rules": [rule, ...]}}. Rule types (use only these):
- filter: max_eyes_closed (int, faces allowed with eyes closed, 0 = no blinks),
  allow_intentional (bool, true keeps frames where closed eyes look deliberate, e.g. a kiss
  or laughing), min_sharpness (number, default {min_sharp:g}; only change it if the user
  asks for a sharpness threshold), drop_exposure_flags (bool, drop under/overexposed).
- dedupe_bursts: keep (int, frames kept per burst, normally 1).
- coverage: by "group_id", min_per_group (int). "At least one of every group/moment/table"
  means min_per_group 1; "two of every group" means 2.
- cap: by "group_id", max_per_group (int). Caps are per moment. Cull never identifies
  people, so "max 3 of the same couple/person/table" means a per-moment cap of 3.
- prefer: tags (from {tags}), weight (number > 1, 1.5 for "favor", 2 for "strongly favor").

Guidance:
- Always include filter and dedupe_bursts. "No blinks except intentional moments" means
  max_eyes_closed 0 with allow_intentional true. "Strict on blinks" or "no blinks at all"
  means max_eyes_closed 0 with allow_intentional false.
- target: the number the user asks for ("about 30" -> 30). If none, use about half the frames.
- Include coverage (min_per_group 1) unless the user says otherwise. Include a cap when the
  user asks for one; otherwise, if coverage is present, cap at max(3, min_per_group + 2).
- "Group" in an instruction means a moment (group_id), not only frames tagged "group".
- Include prefer only when the user asks to favor something.

Shoot summary:
{summary}"""

_client = None
_client_lock = threading.Lock()


def _bedrock():
    global _client
    with _client_lock:
        if _client is None:
            _client = boto3.client(
                "bedrock-runtime", region_name=config.AWS_REGION,
                config=Config(retries={"mode": "adaptive", "max_attempts": 6}))
    return _client


def _defaults():
    """Rule defaults by type, from the first plan in fixtures/preset_plans.json."""
    presets = json.loads(PRESETS_PATH.read_text(encoding="utf-8"))
    first = next(iter(presets.values()))
    return {r["type"]: r for r in first["rules"]}


def shoot_summary(images):
    moments = {}
    for img in images:
        g = img.get("group_id") or "none"
        label, n = moments.get(g, (img.get("group_label") or g, 0))
        moments[g] = (label, n + 1)
    tags = Counter(t for img in images for t in (img.get("scene_tags") or []))
    lines = [f"Frames: {len(images)}", f"Moments ({len(moments)}):"]
    lines += [f"- {g}: {label} ({n} frames)" for g, (label, n) in sorted(moments.items())]
    lines.append("Tag counts: " + (", ".join(f"{t} {n}" for t, n in tags.most_common()) or "none"))
    return "\n".join(lines)


_INT_FIELDS = {"max_eyes_closed", "keep", "min_per_group", "max_per_group"}
_FLOAT_FIELDS = {"min_sharpness", "weight"}
_BOOL_FIELDS = {"allow_intentional", "drop_exposure_flags"}


def _clean_rule(rule, defaults):
    rtype = rule.get("type")
    if rtype not in defaults:
        return None
    out = copy.deepcopy(defaults[rtype])
    for key in defaults[rtype]:
        val = rule.get(key)
        if val is None:
            continue
        try:
            if key in _INT_FIELDS:
                out[key] = max(0, int(val))
            elif key in _FLOAT_FIELDS:
                out[key] = float(val)
            elif key in _BOOL_FIELDS:
                out[key] = val if isinstance(val, bool) else str(val).lower() == "true"
            elif key == "tags":
                out[key] = [t for t in val if t in TAG_VOCAB] or out[key]
        except (TypeError, ValueError):
            pass  # keep the default for unparseable values
    if "by" in out:
        out["by"] = "group_id"  # cap and coverage are always per moment
    if rtype in ("dedupe_bursts", "coverage", "cap"):
        key = {"dedupe_bursts": "keep", "coverage": "min_per_group", "cap": "max_per_group"}[rtype]
        out[key] = max(1, out[key])
    return out


def validate(raw, images, instruction=""):
    """Clamp target, drop unknown rule types, fill missing fields from the first preset."""
    defaults = _defaults()
    try:
        target = int(raw.get("target"))
    except (TypeError, ValueError):
        target = len(images) // 2
    rules = [r for r in (_clean_rule(r, defaults) for r in raw.get("rules") or []
                         if isinstance(r, dict)) if r]
    if not any(r["type"] == "filter" for r in rules):
        rules.insert(0, copy.deepcopy(defaults["filter"]))
    if not SHARPNESS_WORDS.search(instruction or ""):
        for r in rules:
            if r["type"] == "filter":
                r["min_sharpness"] = config.MIN_SHARPNESS  # matches the top_n baseline
    return {"target": max(1, min(target, len(images))) if images else 1, "rules": rules}


def _converse(**kwargs):
    if not config.BEDROCK_AGENT_MODEL_ID:
        raise RuntimeError("BEDROCK_AGENT_MODEL_ID is not set")
    return _bedrock().converse(modelId=config.BEDROCK_AGENT_MODEL_ID, **kwargs)


def make_plan(instruction, images):
    system = SYSTEM_TEMPLATE.format(min_sharp=config.MIN_SHARPNESS, tags=", ".join(TAG_VOCAB),
                                    summary=shoot_summary(images))
    resp = _converse(
        system=[{"text": system}],
        messages=[{"role": "user", "content": [{"text": instruction}]}],
        toolConfig={
            "tools": [{"toolSpec": {"name": "submit_plan",
                                    "description": "Submit the culling plan for the solver.",
                                    "inputSchema": {"json": PLAN_SCHEMA}}}],
            "toolChoice": {"tool": {"name": "submit_plan"}},
        },
        inferenceConfig={"maxTokens": 800},
    )
    content = resp["output"]["message"]["content"]
    raw = next((c["toolUse"]["input"] for c in content if "toolUse" in c), None)
    if raw is None:
        raise RuntimeError("model did not call submit_plan")
    return validate(raw, images, instruction)


def explain(plan, result):
    """2 to 3 sentences on the result, naming any unmet rule."""
    report = result.get("report", [])
    prompt = ("Summarise this photo cull for the photographer in 2 to 3 short sentences, "
              "under 60 words total. Name every unmet rule and why; skip rules that were met. "
              "Plain text, no preamble.\n"
              f"Plan: {json.dumps(plan)}\nPicks: {len(result.get('picks', []))}\n"
              f"Report: {json.dumps(report)}\nUnmet moments: {result.get('unmet_groups', [])}")
    resp = _converse(messages=[{"role": "user", "content": [{"text": prompt}]}],
                     inferenceConfig={"maxTokens": 120})
    parts = resp["output"]["message"]["content"]
    return " ".join(p["text"] for p in parts if "text" in p).strip()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit('usage: python -m cull.agent "<instruction>"')
    fake = config.REPO_ROOT / "fixtures" / "fake_scores.json"
    rows = json.loads(fake.read_text(encoding="utf-8"))["images"]
    print(json.dumps(make_plan(" ".join(sys.argv[1:]), rows), indent=2))
