"""Agent provider tests. A fake client stands in for the Anthropic API (no network, no key)."""
import json
from types import SimpleNamespace

import pytest

from cull import agent, config

IMAGES = [{"path": f"shoot/{i}.ARW", "group_id": f"G{i % 3}", "scene_tags": ["candid"]}
          for i in range(20)]


class FakeMessages:
    def __init__(self, text, stop_reason="end_turn"):
        self.text, self.stop_reason, self.calls = text, stop_reason, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason=self.stop_reason,
                               content=[SimpleNamespace(type="thinking", thinking=""),
                                        SimpleNamespace(type="text", text=self.text)])


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
    raw = {"target": 999, "rules": [{"type": "dedupe_bursts", "keep": 1},
                                    {"type": "cap", "by": "group_id", "max_per_group": 2}]}
    messages = fake(json.dumps(raw))
    plan = agent.make_plan("keep about 999, max 2 per moment", IMAGES)

    assert plan["target"] == len(IMAGES)  # clamped to the shoot size
    assert [r["type"] for r in plan["rules"]] == ["filter", "dedupe_bursts", "cap"]
    call = messages.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"]["format"] == {"type": "json_schema", "schema": agent.PLAN_SCHEMA}
    assert call["output_config"]["effort"] == config.ANTHROPIC_EFFORT
    assert "tool_choice" not in call  # forced tool use is a 400 on current models
    assert call["fallbacks"] == "default"


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_unusable_stop_reason_raises(fake, stop_reason):
    fake('{"target": 5, "rules": []}', stop_reason)
    with pytest.raises(agent.ProviderUnavailable):
        agent.make_plan("about 5", IMAGES)


def test_non_json_reply_raises(fake):
    fake("Sure! Here is your plan.")
    with pytest.raises(agent.ProviderUnavailable):
        agent.make_plan("about 5", IMAGES)


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
    walk(agent.PLAN_SCHEMA)


def test_agent_does_not_import_boto3():
    assert "boto3" not in agent.__dict__
    src = (config.REPO_ROOT / "cull" / "agent.py").read_text(encoding="utf-8")
    assert "boto3" not in src and "bedrock" not in src.lower()
