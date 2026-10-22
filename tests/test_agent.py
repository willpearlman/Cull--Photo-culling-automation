"""Agent provider tests. A fake client stands in for the Anthropic API (no network, no key)."""
import json
from types import SimpleNamespace

import pytest

from cull import agent, config

IMAGES = [{"path": f"shoot/{i}.ARW", "group_id": f"G{i % 3}", "scene_tags": ["candid"],
           "burst_id": f"B{i}", "sharpness": 500.0, "exposure_flags": [], "eyes_closed_count": 0}
          for i in range(20)]


class FakeMessages:
    """Replies with `text`, or with each item of a list in turn (the last one repeats)."""

    def __init__(self, text, stop_reason="end_turn"):
        self.texts = text if isinstance(text, list) else [text]
        self.stop_reason, self.calls = stop_reason, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        text = self.texts[min(len(self.calls), len(self.texts)) - 1]
        return SimpleNamespace(stop_reason=self.stop_reason,
                               content=[SimpleNamespace(type="thinking", thinking=""),
                                        SimpleNamespace(type="text", text=text)])


def _raw(target=10, rules=None, user_set_cap=False, unsupported=()):
    return json.dumps({"target": target, "user_set_cap": user_set_cap,
                       "unsupported": list(unsupported),
                       "rules": rules if rules is not None else [
                           {"type": "dedupe_bursts", "keep": 1},
                           {"type": "coverage", "by": "group_id", "min_per_group": 1},
                           {"type": "cap", "by": "group_id", "max_per_group": 3}]})


@pytest.fixture
def fake(monkeypatch):
    def install(text, stop_reason="end_turn"):
        messages = FakeMessages(text, stop_reason)
        monkeypatch.setattr(config, "LLM_PROVIDER", "anthropic")
        monkeypatch.setattr(config, "ANTHROPIC_AGENT_MODEL", "claude-opus-5-5")
        monkeypatch.setattr(agent, "_client", SimpleNamespace(beta=SimpleNamespace(messages=messages)))
        return messages
    return install


def test_presets_provider_raises_so_server_falls_back(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "presets")
    with pytest.raises(agent.ProviderUnavailable):
        agent.make_plan("about 30", IMAGES)
    with pytest.raises(agent.ProviderUnavailable):
        agent.explain({"target": 1}, {"picks": [], "report": []})


def test_anthropic_plan_is_parsed_and_validated(fake):
    messages = fake(_raw(999, [{"type": "dedupe_bursts", "keep": 1},
                               {"type": "cap", "by": "group_id", "max_per_group": 2}], True))
    plan = agent.make_plan("keep about 999, max 2 per moment", IMAGES)

    assert plan["target"] == len(IMAGES)  # clamped to the shoot size
    assert any("only 20" in w for w in plan["warnings"])
    assert [r["type"] for r in plan["rules"]] == ["filter", "dedupe_bursts", "cap"]
    call = messages.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"]["format"] == {
        "type": "json_schema", "schema": agent.plan_schema(agent.tag_vocab())}
    assert call["output_config"]["effort"] == config.ANTHROPIC_EFFORT
    assert "tool_choice" not in call  # forced tool use is a 400 on current models
    assert call["fallbacks"] == "default"


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_unusable_stop_reason_raises(fake, stop_reason):
    fake('{"target": 5, "rules": []}', stop_reason)
    with pytest.raises(agent.ProviderUnavailable):
        agent.make_plan("about 5", IMAGES)


def test_non_json_reply_is_retried_once_then_raises(fake):
    messages = fake("Sure! Here is your plan.")
    with pytest.raises(agent.ProviderUnavailable):
        agent.make_plan("about 5", IMAGES)
    assert len(messages.calls) == 2


def test_retry_recovers_from_one_bad_reply(fake):
    messages = fake(["not json", _raw(6)])
    assert agent.make_plan("about 6", IMAGES)["target"] == 6
    assert len(messages.calls) == 2


def test_no_number_gives_default_target_and_a_cap_that_fits(fake, monkeypatch):
    monkeypatch.setattr(config, "DEFAULT_KEEP_FRACTION", 0.5)
    fake(_raw(target=None))
    plan = agent.make_plan("make it look good", IMAGES)
    assert plan["target"] == 10 and plan["target_defaulted"] is True
    cap = next(r for r in plan["rules"] if r["type"] == "cap")
    assert cap["max_per_group"] == 4  # 10 frames over 3 moments, raised from 3
    assert plan["warnings"] == []


def test_automatic_cap_accounts_for_small_moments(fake):
    # G0 has 16 usable frames, G1 and G2 have 2 each: an even split (cap 4) would give 8.
    images = [dict(IMAGES[0], path=f"shoot/a{i}.ARW", burst_id=f"A{i}", group_id="G0")
              for i in range(16)]
    images += [dict(IMAGES[0], path=f"shoot/{g}{i}.ARW", burst_id=f"{g}{i}", group_id=g)
               for g in ("G1", "G2") for i in range(2)]
    fake(_raw(target=12))
    plan = agent.make_plan("12 photos", images)
    assert next(r for r in plan["rules"] if r["type"] == "cap")["max_per_group"] == 8


def test_too_few_usable_frames_is_flagged(fake):
    images = [dict(img, sharpness=50.0) if i < 15 else img for i, img in enumerate(IMAGES)]
    fake(_raw(target=10))
    plan = agent.make_plan("10 photos", images)
    assert any("Only 5 frames pass" in w for w in plan["warnings"])


def test_user_cap_is_kept_and_flagged_when_too_small(fake):
    fake(_raw(target=12, user_set_cap=True))
    plan = agent.make_plan("12 photos, max 3 per moment", IMAGES)
    assert next(r for r in plan["rules"] if r["type"] == "cap")["max_per_group"] == 3
    assert any("allows 9 picks" in w for w in plan["warnings"])


def test_coverage_larger_than_target_is_flagged(fake):
    fake(_raw(target=5, rules=[{"type": "coverage", "by": "group_id", "min_per_group": 2}]))
    plan = agent.make_plan("5 photos, two of every moment", IMAGES)
    assert any("needs 6 picks" in w for w in plan["warnings"])


def test_unsupported_requests_pass_through(fake):
    fake(_raw(target=5, unsupported=["identifying the bride", " "]))
    plan = agent.make_plan("only the bride, 5 photos", IMAGES)
    assert plan["unsupported"] == ["identifying the bride"]


def test_prefer_tags_outside_the_genre_vocab_are_dropped(fake, monkeypatch):
    monkeypatch.setattr(config, "GENRE", "wedding")
    fake(_raw(rules=[{"type": "prefer", "tags": ["first kiss", "sunset"], "weight": 2}]))
    prefer = next(r for r in agent.make_plan("favor the kiss", IMAGES)["rules"]
                  if r["type"] == "prefer")
    assert prefer["tags"] == ["first kiss"]


def test_empty_instruction_is_replaced(fake):
    messages = fake(_raw())
    agent.make_plan("   ", IMAGES)
    assert messages.calls[0]["messages"][0]["content"] == agent.EMPTY_INSTRUCTION


def test_explain_returns_model_text_when_valid(fake):
    fake("Picked 5 frames. The cap held in every moment.")
    out = agent.explain({"target": 5}, {"picks": ["a"] * 5, "report": []})
    assert out == "Picked 5 frames. The cap held in every moment."


def test_plan_schema_is_valid_for_structured_outputs():
    """Every object sets additionalProperties false and requires all its properties."""
    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
                assert set(node["required"]) == set(node["properties"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(agent.plan_schema(agent.tag_vocab()))


def test_agent_does_not_import_boto3():
    assert "boto3" not in agent.__dict__
    src = (config.REPO_ROOT / "cull" / "agent.py").read_text(encoding="utf-8")
    assert "boto3" not in src and "bedrock" not in src.lower()
