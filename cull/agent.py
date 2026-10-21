"""Instruction -> plan agent.

make_plan(instruction, images): one LLM call that returns a plan as structured JSON.
explain(plan, result): one short call summarising the result in 2 to 3 sentences.
Plan shape: .kiro/steering/contracts.md.

Providers (config.LLM_PROVIDER):
- anthropic: Anthropic API, key from ANTHROPIC_API_KEY.
- presets: no LLM. Both calls raise ProviderUnavailable and the server uses
  fixtures/preset_plans.json instead.
"""
import copy
import json
import re
import sys
import threading
from collections import Counter

from cull import config

PRESETS_PATH = config.REPO_ROOT / "fixtures" / "preset_plans.json"
TAG_VOCAB = ["group", "couple", "candid", "dance floor", "food", "indoor", "outdoor",
             "portrait", "detail"]
RULE_TYPES = ["filter", "dedupe_bursts", "coverage", "cap", "prefer"]
# Words that mean the user is asking about the sharpness threshold itself.
SHARPNESS_WORDS = re.compile(r"sharp|blur|focus|soft|crisp", re.IGNORECASE)
# Models that accept the server-side refusal fallback (fallbacks: "default").
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1"}


class ProviderUnavailable(RuntimeError):
    """No LLM is configured, or the call could not produce a usable answer."""


def _rule(rtype, **fields):
    """One rule variant for structured outputs: every field required, nothing extra."""
    return {
        "type": "object",
        "properties": {"type": {"type": "string", "const": rtype}, **fields},
        "required": ["type", *fields],
        "additionalProperties": False,
    }


_GROUP_BY = {"type": "string", "enum": ["group_id"]}

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "target": {"type": "integer", "description": "Number of frames to keep."},
        "rules": {
            "type": "array",
            "items": {"anyOf": [
                _rule("filter",
                      max_eyes_closed={"type": "integer"},
                      allow_intentional={"type": "boolean"},
                      min_sharpness={"type": "number"},
                      drop_exposure_flags={"type": "boolean"}),
                _rule("dedupe_bursts", keep={"type": "integer"}),
                _rule("coverage", by=_GROUP_BY, min_per_group={"type": "integer"}),
                _rule("cap", by=_GROUP_BY, max_per_group={"type": "integer"}),
                _rule("prefer",
                      tags={"type": "array", "items": {"type": "string", "enum": TAG_VOCAB}},
                      weight={"type": "number"}),
            ]},
        },
    },
    "required": ["target", "rules"],
    "additionalProperties": False,
}

SYSTEM_TEMPLATE = """You turn a photographer's culling instruction into a plan for a rule solver.
Answer with the plan JSON only. Never ask questions.

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


def _anthropic():
    """One shared client. Imported lazily so the presets provider needs no SDK."""
    global _client
    with _client_lock:
        if _client is None:
            import anthropic
            _client = anthropic.Anthropic(timeout=60.0, max_retries=2)
    return _client


def _create(max_tokens, **kwargs):
    """One Messages call on the configured provider. Returns the reply text."""
    if config.LLM_PROVIDER != "anthropic":
        raise ProviderUnavailable(f"LLM_PROVIDER={config.LLM_PROVIDER!r}")
    model = config.ANTHROPIC_AGENT_MODEL
    extra = {}
    if model in _FALLBACK_MODELS:
        # On a safety decline the API re-runs the request on a fallback model.
        extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
    output_config = {"effort": config.ANTHROPIC_EFFORT, **kwargs.pop("output_config", {})}
    resp = _anthropic().beta.messages.create(
        model=model, max_tokens=max_tokens, output_config=output_config, **extra, **kwargs)
    if resp.stop_reason in ("refusal", "max_tokens"):
        raise ProviderUnavailable(f"stop_reason={resp.stop_reason}")
    return "".join(b.text for b in resp.content if b.type == "text").strip()


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
    if not images:
        raise ValueError("cannot create a culling plan without images")
    defaults = _defaults()
    try:
        target = int(raw.get("target"))
    except (AttributeError, TypeError, ValueError):
        target = len(images) // 2
    raw_rules = raw.get("rules") if isinstance(raw, dict) else []
    rules = [r for r in (_clean_rule(r, defaults) for r in raw_rules or []
                         if isinstance(r, dict)) if r]
    if not any(r["type"] == "filter" for r in rules):
        rules.insert(0, copy.deepcopy(defaults["filter"]))
    if not SHARPNESS_WORDS.search(instruction or ""):
        for r in rules:
            if r["type"] == "filter":
                r["min_sharpness"] = config.MIN_SHARPNESS  # matches the top_n baseline
    return {"target": max(1, min(target, len(images))), "rules": rules}


def make_plan(instruction, images):
    if not images:
        raise ValueError("cannot create a culling plan without images")
    system = SYSTEM_TEMPLATE.format(min_sharp=config.MIN_SHARPNESS, tags=", ".join(TAG_VOCAB),
                                    summary=shoot_summary(images))
    text = _create(
        max_tokens=8000,
        system=system,
        messages=[{"role": "user", "content": instruction}],
        output_config={"format": {"type": "json_schema", "schema": PLAN_SCHEMA}},
    )
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProviderUnavailable("model reply was not plan JSON") from exc
    return validate(raw, images, instruction)


def _fallback_explanation(plan, result):
    picks = len(result.get("picks", []))
    target = plan.get("target", picks)
    first = f"Selected {picks} of {target} requested frames."
    unmet = [r for r in result.get("report", []) if r.get("met") is False]
    if unmet:
        details = "; ".join(
            f"{r.get('type', 'rule')}: {r.get('detail', 'not satisfied')}" for r in unmet)
        second = f"Unmet rules — {details}."
    else:
        second = "All requested rules were met."
    return f"{first} {second}"


def _valid_explanation(text, result):
    sentences = [part for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part]
    if not 2 <= len(sentences) <= 3:
        return False
    low = text.lower()
    unmet_types = [str(r.get("type", "rule")).lower()
                   for r in result.get("report", []) if r.get("met") is False]
    return all(rtype in low for rtype in unmet_types)


def explain(plan, result):
    """Make one short call, guaranteeing 2 to 3 sentences that name every unmet rule."""
    report = result.get("report", [])
    prompt = ("Summarise this photo cull for the photographer in 2 to 3 short sentences, "
              "under 60 words total. Name every unmet rule and why; skip rules that were met. "
              "Plain text, no preamble.\n"
              f"Plan: {json.dumps(plan)}\nPicks: {len(result.get('picks', []))}\n"
              f"Report: {json.dumps(report)}\nUnmet moments: {result.get('unmet_groups', [])}")
    text = _create(max_tokens=4000, messages=[{"role": "user", "content": prompt}])
    return text if _valid_explanation(text, result) else _fallback_explanation(plan, result)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit('usage: python -m cull.agent "<instruction>"')
    fake = config.REPO_ROOT / "fixtures" / "fake_scores.json"
    rows = json.loads(fake.read_text(encoding="utf-8"))["images"]
    print(json.dumps(make_plan(" ".join(sys.argv[1:]), rows), indent=2))
