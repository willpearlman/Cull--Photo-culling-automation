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
    assert settings.load() == {"lightroom": None}
    settings.update({"lightroom": "cloud"})
    assert store.exists()
    assert settings.load()["lightroom"] == "cloud"


def test_bad_values_are_rejected_and_corrupt_files_ignored(store):
    with pytest.raises(ValueError):
        settings.update({"lightroom": "photoshop"})
    with pytest.raises(ValueError):
        settings.update({"theme": "dark"})
    store.parent.mkdir(parents=True)
    store.write_text("{not json", encoding="utf-8")
    assert settings.load() == {"lightroom": None}


def test_each_mode_has_a_complete_guide():
    for mode in settings.LIGHTROOM_MODES:
        g = lightroom.guide(mode)
        assert g["name"] and g["when"] and g["before_export"] and g["after_export"]
    assert "Read Metadata from Files" in " ".join(lightroom.guide("classic")["after_export"])
    assert "Add Photos" in " ".join(lightroom.guide("cloud")["after_export"])
    assert lightroom.guide(None) is None


def test_settings_api_round_trip(store):
    from cull import server
    client = TestClient(server.app)
    assert client.get("/api/settings").json()["lightroom"] is None
    r = client.post("/api/settings", json={"lightroom": "classic"})
    assert r.status_code == 200 and r.json()["guide"]["name"] == "Lightroom Classic"
    assert client.post("/api/settings", json={"lightroom": "nope"}).status_code == 400
    assert client.get("/api/settings").json()["lightroom"] == "classic"
