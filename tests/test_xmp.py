"""XMP export: re-exporting must not duplicate keywords. Needs exiftool on PATH."""
import shutil

import pytest

from cull import config, xmp

pytestmark = pytest.mark.skipif(shutil.which("exiftool") is None, reason="exiftool not on PATH")


def _subjects(et, path):
    tags = et.get_tags([str(path)], ["XMP-dc:Subject"])[0]
    val = tags.get("XMP:Subject", [])
    return val if isinstance(val, list) else [val]


def test_reexport_keeps_one_copy_of_each_keyword(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SHOOT_DIR", tmp_path)
    image = {"path": "shoot/A.ARW", "scene_tags": ["group", "candid"]}
    decisions = {"shoot/A.ARW": {"rating": 5, "label": "Green", "reason": "Kept"}}

    for _ in range(3):
        assert xmp.export(decisions, [image]) == 1

    from exiftool import ExifToolHelper
    with ExifToolHelper() as et:
        assert sorted(_subjects(et, tmp_path / "A.xmp")) == ["candid", "group"]


def test_reexport_drops_stale_cull_keywords_but_keeps_the_users(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SHOOT_DIR", tmp_path)
    from exiftool import ExifToolHelper
    with ExifToolHelper() as et:
        # An earlier export tagged portrait and group; the user added their own keyword.
        et.execute("-XMP-dc:Subject+=portrait", "-XMP-dc:Subject+=group",
                   "-XMP-dc:Subject+=Smith wedding", str(tmp_path / "C.xmp"))
    image = {"path": "shoot/C.ARW", "scene_tags": ["couple", "ceremony"]}
    xmp.export({"shoot/C.ARW": {"rating": 5, "label": None, "reason": "Kept"}}, [image])
    with ExifToolHelper() as et:
        assert sorted(_subjects(et, tmp_path / "C.xmp")) == ["Smith wedding", "ceremony", "couple"]


def test_reexport_collapses_existing_duplicates(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SHOOT_DIR", tmp_path)
    from exiftool import ExifToolHelper
    with ExifToolHelper() as et:
        # Simulate a sidecar written by the old += export, run three times.
        et.execute(*["-XMP-dc:Subject+=group"] * 3, str(tmp_path / "B.xmp"))
        assert _subjects(et, tmp_path / "B.xmp") == ["group"] * 3

    image = {"path": "shoot/B.ARW", "scene_tags": ["group"]}
    xmp.export({"shoot/B.ARW": {"rating": 1, "label": None, "reason": "Rejected"}}, [image])

    with ExifToolHelper() as et:
        assert _subjects(et, tmp_path / "B.xmp") == ["group"]
