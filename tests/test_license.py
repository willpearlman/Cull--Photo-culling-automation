"""License key and the proxy provider, against a fake proxy on localhost (no network)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from cull import agent, config, license, settings

GOOD, SPENT = "CULL-GOOD1-GOOD1-GOOD1-GOOD1", "CULL-SPENT-SPENT-SPENT-SPENT"
IMAGES = [{"path": f"shoot/{i}.ARW", "group_id": "G001", "burst_id": f"B{i}", "sharpness": 500.0,
           "exposure_flags": [], "scene_tags": [], "claude_score": 5.0} for i in range(20)]
PLAN = {"target": 5, "user_set_cap": False, "unsupported": [],
        "rules": [{"type": "dedupe_bursts", "keep": 1}]}


class FakeProxy(BaseHTTPRequestHandler):
    calls = []  # (path, license key) of every request

    def _send(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.send_header("x-should-retry", "false")
        self.end_headers()
        self.wfile.write(data)

    def _answer(self):
        key = self.headers.get("x-api-key")
        FakeProxy.calls.append((self.path.split("?")[0], key))
        if key == SPENT and self.command == "POST":
            return self._send(429, {"type": "error", "error": {
                "type": "rate_limit_error",
                "message": "This license has used all 1000 instruction calls for 2026-11."}})
        if key not in (GOOD, SPENT):
            return self._send(401, {"type": "error", "error": {
                "type": "authentication_error", "message": "This license key is not recognized."}})
        if self.command == "GET":
            return self._send(200, {"valid": True, "used": 3, "limit": 1000, "month": "2026-11"})
        self.rfile.read(int(self.headers.get("content-length", 0)))
        self._send(200, {"id": "msg_1", "type": "message", "role": "assistant",
                         "model": "claude-opus-5-5", "stop_reason": "end_turn",
                         "content": [{"type": "text", "text": json.dumps(PLAN)}],
                         "usage": {"input_tokens": 1, "output_tokens": 1}})

    do_GET = do_POST = _answer

    def log_message(self, *args):
        pass


@pytest.fixture
def proxy(tmp_path, monkeypatch):
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeProxy)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    FakeProxy.calls = []
    monkeypatch.setenv("CULL_SETTINGS", str(tmp_path / "settings.json"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(config, "LLM_PROVIDER", "license")
    monkeypatch.setattr(config, "PROXY_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setattr(agent, "_client", None)
    yield server
    server.shutdown()


def test_a_valid_key_is_checked_saved_and_never_sent_to_the_page(proxy):
    from cull.server import app
    client = TestClient(app)
    assert client.get("/api/settings").json()["license"] == {"set": False, "hint": None, "needed": True}
    res = client.post("/api/license", json={"key": " cull-good1-good1 -good1-good1\n"})
    assert res.status_code == 200
    assert res.json() == {"set": True, "hint": "GOOD1", "needed": True,
                          "used": 3, "limit": 1000, "month": "2026-11"}
    assert settings.load()["license_key"] == GOOD
    for url in ("/api/settings", "/api/license"):
        assert GOOD not in client.get(url).text
    assert client.post("/api/settings", json={"license_key": "x"}).status_code == 400
    assert client.post("/api/license", json={"key": None}).json()["set"] is False
    assert settings.load()["license_key"] is None


def test_a_bad_key_is_refused_with_the_proxys_message_and_not_saved(proxy):
    from cull.server import app
    res = TestClient(app).post("/api/license", json={"key": "CULL-NOPE"})
    assert res.status_code == 400
    assert res.json()["detail"] == "This license key is not recognized."
    assert settings.load()["license_key"] is None


def test_an_unreachable_proxy_gives_a_plain_message(proxy, monkeypatch):
    monkeypatch.setattr(config, "PROXY_URL", "http://127.0.0.1:9")
    with pytest.raises(license.LicenseError, match="could not reach"):
        license.check(GOOD)


def test_plans_go_through_the_proxy_with_the_license_key(proxy):
    settings.update({"license_key": GOOD})
    plan = agent.make_plan("keep 5", IMAGES)
    assert plan["target"] == 5
    assert FakeProxy.calls == [("/v1/messages", GOOD)]


def test_no_key_bad_key_and_spent_key_tell_the_user_what_to_do(proxy):
    with pytest.raises(agent.ProviderUnavailable) as exc:
        agent.make_plan("keep 5", IMAGES)
    assert "Enter your license key" in exc.value.user_message
    assert FakeProxy.calls == []

    settings.update({"license_key": "CULL-NOPE"})
    with pytest.raises(agent.ProviderUnavailable) as exc:
        agent.make_plan("keep 5", IMAGES)
    assert exc.value.user_message == "This license key is not recognized."

    settings.update({"license_key": SPENT})
    with pytest.raises(agent.ProviderUnavailable) as exc:
        agent.make_plan("keep 5", IMAGES)
    assert "used all 1000" in exc.value.user_message
    # One call each: these are not retried.
    assert [key for _, key in FakeProxy.calls] == ["CULL-NOPE", SPENT]


def test_the_plan_endpoint_explains_why_it_fell_back_to_a_preset(proxy, monkeypatch):
    from cull import server
    monkeypatch.setattr(server, "_images_with_overrides", lambda: [dict(i) for i in IMAGES])
    res = TestClient(server.app).post("/api/plan", json={"instruction": "keep 5"}).json()
    assert res["plan"]["warnings"] == [
        "Enter your license key to use typed instructions. Cull used a preset plan."]
