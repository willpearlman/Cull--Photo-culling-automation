"""Opening a shoot: folder checks, cache location, background processing and progress."""
import time

import pytest
from fastapi.testclient import TestClient

from cull import config, pipeline, shoots


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("CULL_SETTINGS", str(tmp_path / "settings.json"))
    monkeypatch.setattr(config, "APP_DATA", tmp_path / "appdata")
    monkeypatch.setattr(shoots, "_status", dict(shoots._status, state="idle", folder=None))
    yield tmp_path
    config.set_shoot(config.REPO_ROOT / "demo")


def _raw_folder(tmp_path, n=3):
    d = tmp_path / "card"
    d.mkdir()
    for i in range(n):
        (d / f"DSC{i:04d}.ARW").write_bytes(b"x")
    (d / "notes.txt").write_text("not a raw")
    return d


def test_raw_folder_caches_outside_itself_and_keeps_sidecars_beside_raws(isolated):
    card = _raw_folder(isolated)
    config.set_shoot(card)
    assert config.SHOOT_DIR == card.resolve()
    assert config.CULL_ROOT.parent == isolated / "appdata" / "shoots"
    assert config.SCORES_PATH == config.CULL_ROOT / "work" / "scores.json"
    assert config.cache_root(card) == config.cache_root(str(card).upper())  # Windows paths


def test_bad_folders_are_rejected(isolated):
    with pytest.raises(ValueError, match="Not a folder"):
        shoots.open_folder(isolated / "missing")
    empty = isolated / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="No Sony RAW"):
        shoots.open_folder(empty)


def test_processing_runs_every_stage_reports_progress_and_remembers_the_folder(isolated, monkeypatch):
    ran = []
    monkeypatch.setattr(pipeline, "run_stage", lambda stage, limit, raise_errors: ran.append(stage))
    monkeypatch.setattr(pipeline, "merge", lambda limit: ran.append("merge"))
    card = _raw_folder(isolated)
    shoots.open_folder(card)
    for _ in range(100):
        if shoots.status()["state"] != "running":
            break
        time.sleep(0.02)
    s = shoots.status()
    assert s["state"] == "ready" and s["progress"] == 1.0 and s["frames"] == 3
    assert ran == [*pipeline.STAGE_ORDER, "merge"]
    from cull import settings
    assert settings.load()["recent_shoots"] == [str(card)]


def test_a_failing_stage_ends_in_error_not_ready(isolated, monkeypatch):
    def boom(stage, limit, raise_errors):
        if stage == "faces":
            raise OSError("disk full")
    monkeypatch.setattr(pipeline, "run_stage", boom)
    shoots.open_folder(_raw_folder(isolated))
    for _ in range(100):
        if shoots.status()["state"] != "running":
            break
        time.sleep(0.02)
    s = shoots.status()
    assert s["state"] == "error" and "Finding faces" in s["message"] and "disk full" in s["message"]


def test_api_reports_no_shoot_and_empty_scores_until_one_is_ready(isolated):
    from cull import server
    client = TestClient(server.app)
    assert client.get("/api/shoot").json()["state"] == "idle"
    assert client.get("/api/scores").json()["images"] == []
    assert client.post("/api/shoot", json={"folder": str(isolated / "nope")}).status_code == 400
