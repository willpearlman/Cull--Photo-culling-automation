"""User settings store, Lightroom guides, and the settings/export API."""
import pytest
from fastapi.testclient import TestClient

from cull import lightroom, settings


@pytest.fixture
def store(tmp_path, monkeypatch):
    p = tmp_path / "sub" / "settings.json"
    monkeypatch.setenv("CULL_SETTINGS", str(p))
    return p


def test_unset_until_chosen_then_persisted(store):
    assert settings.load() == settings.DEFAULTS
    settings.update({"lightroom": "cloud"})
    assert store.exists()
    assert settings.load()["lightroom"] == "cloud"


def test_bad_values_are_rejected_and_corrupt_files_ignored(store):
    with pytest.raises(ValueError):
        settings.update({"lightroom": "photoshop"})
    with pytest.raises(ValueError):
        settings.update({"theme": "dark"})
    with pytest.raises(ValueError):
        settings.update({"recent_shoots": "C:/one"})
    store.parent.mkdir(parents=True)
    store.write_text("{not json", encoding="utf-8")
    assert settings.load() == settings.DEFAULTS


def test_each_mode_has_a_complete_guide():
    for mode in settings.LIGHTROOM_MODES:
        g = lightroom.guide(mode)
        assert g["name"] and g["when"] and g["before_export"] and g["after_export"]
    assert "Read Metadata from Files" in " ".join(lightroom.guide("classic")["after_export"])
    assert "Add Photos" in " ".join(lightroom.guide("cloud")["after_export"])
    assert lightroom.guide(None) is None


def test_export_records_the_final_selection(store, tmp_path, monkeypatch):
    from cull import config, personal, server, xmp
    monkeypatch.setattr(server, "_images_with_overrides", lambda: [{"path": "a"}, {"path": "b"}])
    monkeypatch.setattr(server, "_load_overrides", lambda: {"b": 1, "c": 5})
    monkeypatch.setattr(xmp, "export", lambda decisions, images: len(decisions))
    seen = {}
    monkeypatch.setattr(personal, "shoot_rows", lambda work: ["rows"])
    monkeypatch.setattr(personal, "record",
                        lambda shoot, rows, sel: seen.update(shoot=shoot, sel=sel) or 9)
    r = TestClient(server.app).post("/api/export", json={"picks": ["a"], "decisions": {"a": {}}})
    assert r.json()["learned_from"] == 9
    # Picks are kept (5); only explicit rejects count as rejects; a forced pick Cull
    # dropped from the picks ("c") is not invented.
    assert seen == {"shoot": str(config.CULL_ROOT), "sel": {"a": 5, "b": 1}}

    # No overrides: the selection is just Cull's own picks, so nothing is learned.
    seen.clear()
    monkeypatch.setattr(server, "_load_overrides", lambda: {})
    r = TestClient(server.app).post("/api/export", json={"picks": ["a"], "decisions": {"a": {}}})
    assert r.json()["learned_from"] == 0 and seen == {}


def test_settings_api_round_trip(store):
    from cull import server
    client = TestClient(server.app)
    assert client.get("/api/settings").json()["lightroom"] is None
    r = client.post("/api/settings", json={"lightroom": "classic"})
    assert r.status_code == 200 and r.json()["guide"]["name"] == "Lightroom Classic"
    assert client.post("/api/settings", json={"lightroom": "nope"}).status_code == 400
    assert client.get("/api/settings").json()["lightroom"] == "classic"
