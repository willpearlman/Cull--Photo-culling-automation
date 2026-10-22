"""XMP export: keywords in both Lightroom fields, never duplicated. Needs exiftool on PATH."""
import shutil

import pytest

from cull import config, xmp

pytestmark = pytest.mark.skipif(shutil.which("exiftool") is None, reason="exiftool not on PATH")


def _field(et, path, tag, key):
    val = et.get_tags([str(path)], [tag])[0].get(key, [])
    return val if isinstance(val, list) else [val]


def _subjects(et, path):
    """dc:subject keywords, after checking lr:hierarchicalSubject holds the same set."""
    subject = _field(et, path, "XMP-dc:Subject", "XMP:Subject")
    hierarchical = _field(et, path, "XMP-lr:HierarchicalSubject", "XMP:HierarchicalSubject")
    assert sorted(hierarchical) == sorted(subject), "Lightroom reads keywords from both fields"
    return subject


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
        et.execute(*[f"-{f}+={k}" for f in xmp.KEYWORD_FIELDS
                     for k in ("portrait", "group", "Smith wedding")], str(tmp_path / "C.xmp"))
    image = {"path": "shoot/C.ARW", "scene_tags": ["couple", "ceremony"]}
    xmp.export({"shoot/C.ARW": {"rating": 5, "label": None, "reason": "Kept"}}, [image])
    with ExifToolHelper() as et:
        assert sorted(_subjects(et, tmp_path / "C.xmp")) == ["Smith wedding", "ceremony", "couple"]


def test_reexport_collapses_existing_duplicates(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SHOOT_DIR", tmp_path)
    from exiftool import ExifToolHelper
    with ExifToolHelper() as et:
        # Simulate a sidecar written by the old += export, run three times (dc:subject only).
        et.execute(*["-XMP-dc:Subject+=group"] * 3, str(tmp_path / "B.xmp"))
        assert _field(et, tmp_path / "B.xmp", "XMP-dc:Subject", "XMP:Subject") == ["group"] * 3

    image = {"path": "shoot/B.ARW", "scene_tags": ["group"]}
    xmp.export({"shoot/B.ARW": {"rating": 1, "label": None, "reason": "Rejected"}}, [image])

    with ExifToolHelper() as et:
        assert _subjects(et, tmp_path / "B.xmp") == ["group"]
