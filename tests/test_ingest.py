"""Ingest fast path: previews copied straight out of the RAW, with a safe fallback."""
from cull import ingest

JPEG = b"\xff\xd8" + b"preview-bytes" + b"\xff\xd9"


def _raw(tmp_path, body=JPEG):
    src = tmp_path / "DSC0001.ARW"
    src.write_bytes(b"H" * 100 + body + b"raw sensor data")
    return src


def test_preview_is_copied_from_the_offsets_exiftool_reports(tmp_path):
    src, dst = _raw(tmp_path), tmp_path / "DSC0001.jpg"
    tags = {"MakerNotes:PreviewImageStart": 100, "MakerNotes:PreviewImageLength": len(JPEG)}
    assert ingest._copy_preview(src, tags, dst) is True
    assert dst.read_bytes() == JPEG
    assert not list(tmp_path.glob("*.part"))


def test_copy_refuses_anything_that_is_not_a_whole_jpeg(tmp_path):
    src, dst = _raw(tmp_path), tmp_path / "DSC0001.jpg"
    for tags in ({},                                                     # no offsets
                 {"PreviewImageStart": 50, "PreviewImageLength": 20},    # not a JPEG there
                 {"PreviewImageStart": 100, "PreviewImageLength": 10**6},  # runs past the file
                 {"PreviewImageStart": "x", "PreviewImageLength": None}):
        assert ingest._copy_preview(src, tags, dst) is False
        assert not dst.exists()  # the caller falls back to exiftool


def test_tag_is_found_under_any_group():
    assert ingest._tag({"EXIF:Model": "A", "MakerNotes:PreviewImageStart": 7}, "PreviewImageStart") == 7
    assert ingest._tag({"PreviewImageStart": 9}, "PreviewImageStart") == 9
    assert ingest._tag({"EXIF:Model": "A"}, "PreviewImageStart") is None
