"""XMP sidecar export (Will's lane).

Writes Lightroom-readable .xmp sidecars next to each ARW. Originals are never
touched. One stay-open ExifToolHelper per batch; per image we call
`et.execute` with raw args so writing to a missing .xmp is not an error.
"""
import argparse
import json
from pathlib import Path

from exiftool import ExifToolHelper

from cull import config


def _xmp_path(image_path: str) -> Path:
    """shoot/<basename>.xmp beside the original ARW."""
    name = Path(image_path).name
    return config.SHOOT_DIR / (Path(name).stem + ".xmp")


def _write_one(et: ExifToolHelper, image: dict, rating, label) -> None:
    args = [f"-XMP-xmp:Rating={rating}"]
    # Empty label clears it; Lightroom default label set otherwise.
    args.append(f"-XMP-xmp:Label={label or ''}")
    # Remove then add, so re-exporting never duplicates a keyword.
    for tag in image.get("scene_tags") or []:
        args.append(f"-XMP-dc:Subject-={tag}")
        args.append(f"-XMP-dc:Subject+={tag}")
    args.append("-overwrite_original")
    args.append(str(_xmp_path(image["path"])))
    et.execute(*args)


def export(decisions: dict, images: list[dict]) -> int:
    """Write a sidecar per decided image. Returns the count written.

    decisions: {path: {"rating": 1|5, "label": str|None, "reason": str}}
    images: contract rows (used for scene_tags).
    """
    by_path = {img["path"]: img for img in images}
    written = 0
    with ExifToolHelper() as et:
        for path, decision in decisions.items():
            rating = decision.get("rating")
            if rating is None:
                continue
            image = by_path.get(path, {"path": path})
            _write_one(et, image, rating, decision.get("label"))
            written += 1
    return written


def _export_from_scores(images: list[dict]) -> int:
    """CLI path: write each image's final_rating/final_label, skip nulls."""
    written = 0
    with ExifToolHelper() as et:
        for image in images:
            rating = image.get("final_rating")
            if rating is None:
                continue
            _write_one(et, image, rating, image.get("final_label"))
            written += 1
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Write XMP sidecars from a scores.json")
    parser.add_argument("--from", dest="src", required=True, help="path to scores.json")
    args = parser.parse_args()

    data = json.loads(Path(args.src).read_text(encoding="utf-8"))
    images = data.get("images", [])
    written = _export_from_scores(images)
    print(f"xmp: wrote {written} sidecar(s) from {args.src}")


if __name__ == "__main__":
    main()
