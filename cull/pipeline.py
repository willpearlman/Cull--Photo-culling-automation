"""Stage runner and the only owner of the cache files.

CLI:
    python -m cull.pipeline --stage all|ingest|local|faces|scenes|moments|aesthetic|merge [--limit N]

Every stage runs locally with no network. Each stage imports cull.<module>.run(images, cached).
A stage whose module or run function does not exist is skipped with a one-line message.
merge overlays the caches in contract order, derives scene_tags/candid, fills missing
contract fields with null, and writes config.SCORES_PATH.

The old AWS caches (rekog.json, taste.json) are no longer read here. They stay in work/ as
benchmark labels for tools/bench_*.py and tools/train_aesthetic.py.
"""
from __future__ import annotations

import argparse
import importlib
import json
import logging

from . import config

log = logging.getLogger("cull.pipeline")

# Stage name -> (module, cache filename). Order here is the merge/overlay order.
STAGES = [
    ("ingest", "cull.ingest", "exif.json"),
    ("local", "cull.local_scores", "local.json"),
    ("faces", "cull.faces", "faces.json"),
    ("scenes", "cull.scenes", "scenes.json"),      # needs face_count from faces
    ("moments", "cull.moments", "moments.json"),   # labels moments from scene_tags
    ("aesthetic", "cull.aesthetic", "aesthetic.json"),  # needs faces and scenes
]
STAGE_ORDER = [name for name, _, _ in STAGES]
_CACHE = {name: cache for name, _, cache in STAGES}
_MODULE = {name: mod for name, mod, _ in STAGES}

# Every field a scores.json row must carry (contracts.md). Missing -> null.
CONTRACT_FIELDS = [
    "path",
    "preview",
    "capture_time",
    "burst_id",
    "group_id",
    "group_label",
    "sharpness",
    "exposure_flags",
    "face_count",
    "eyes_closed_count",
    "smile_count",
    "scene_tags",
    "intentional_eyes_closed",
    "claude_score",
    "claude_reason",
    "final_rating",
    "final_label",
    "decision_reason",
    "overridden",
]

# Extra ingest fields kept in the exif cache but not required by scores.json.
_EXIF_EXTRA = ["exposure_time", "iso", "focal_length", "model"]


def _cache_path(stage: str):
    return config.WORK_DIR / _CACHE[stage]


def _load_cache(stage: str) -> dict:
    path = _cache_path(stage)
    if path.exists():
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def _save_cache(stage: str, data: dict) -> None:
    config.WORK_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(stage)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False, default=str)


def _load_run(stage: str):
    """Import cull.<module>.run, or None if the module/function is not built."""
    module_name = _MODULE[stage]
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError:
        return None
    return getattr(module, "run", None)


def _merged_rows(limit: int | None, before: str | None = None) -> list[dict]:
    """Build the current merged image list from the ingest cache (the row source).

    Overlays every earlier stage's cache (merge order) so a stage sees fields
    from the stages before it, e.g. faces sees sharpness, aesthetic sees faces and scenes.
    """
    exif = _load_cache("ingest")
    paths = sorted(exif)
    if limit is not None:
        paths = paths[:limit]
    earlier = STAGE_ORDER[1:STAGE_ORDER.index(before)] if before in STAGE_ORDER else []
    caches = [_load_cache(s) for s in earlier]
    rows = []
    for path in paths:
        row = {"path": path}
        row.update(exif[path])
        for cache in caches:
            row.update(cache.get(path) or {})
        rows.append(row)
    return rows


def run_stage(stage: str, limit: int | None) -> None:
    run = _load_run(stage)
    if run is None:
        print(f"skipping {stage}: not built yet")
        return

    cached = _load_cache(stage)
    images = _merged_rows(limit, before=stage)

    # moments recomputes everything and ignores the cache.
    cached_arg = {} if stage == "moments" else cached

    try:
        produced = run(images, cached_arg)
    except Exception as exc:  # a stage failure must not corrupt the cache
        log.error("%s stage raised %s: %s", stage, type(exc).__name__, exc)
        print(f"skipping {stage}: run failed ({type(exc).__name__}: {exc})")
        return

    if stage == "moments":
        merged = dict(produced)  # full recompute replaces the cache
    else:
        merged = dict(cached)
        merged.update(produced)
    _save_cache(stage, merged)
    print(f"{stage}: {len(produced)} new, {len(merged)} cached -> {_CACHE[stage]}")


def _derive_scene(row: dict) -> None:
    """Apply candid -> scene_tags, then null-fill missing contract fields."""
    tags = row.get("scene_tags")
    if row.get("candid") is True:
        tags = list(tags) if tags else []
        if "candid" not in tags:
            tags.append("candid")
        row["scene_tags"] = tags
    row.pop("candid", None)


def merge(limit: int | None) -> dict:
    """Overlay caches in contract order and write scores.json."""
    exif = _load_cache("ingest")
    paths = sorted(exif)
    if limit is not None:
        paths = paths[:limit]

    rows: dict[str, dict] = {p: {"path": p} for p in paths}
    for stage in STAGE_ORDER:
        cache = _load_cache(stage)
        for path in paths:
            fields = cache.get(path)
            if fields:
                rows[path].update(fields)

    out_images = []
    for path in paths:
        row = rows[path]
        _derive_scene(row)
        # Until moments exists, group_id/label fall back to the burst.
        if row.get("group_id") in (None, ""):
            burst = row.get("burst_id")
            row["group_id"] = burst
            row["group_label"] = f"Burst {burst}" if burst else None
        for field in CONTRACT_FIELDS:
            row.setdefault(field, None)
        if row.get("overridden") is None:
            row["overridden"] = False
        clean = {f: row.get(f) for f in CONTRACT_FIELDS}
        for extra in _EXIF_EXTRA:
            if extra in row:
                clean[extra] = row[extra]
        out_images.append(clean)

    scores = {"shoot": config.CULL_ROOT.name, "images": out_images}
    config.SCORES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with config.SCORES_PATH.open("w", encoding="utf-8") as fh:
        json.dump(scores, fh, indent=2, ensure_ascii=False, default=str)
    print(f"merge: {len(out_images)} images -> {config.SCORES_PATH}")
    return scores


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(prog="cull.pipeline")
    parser.add_argument(
        "--stage",
        required=True,
        choices=["all", *STAGE_ORDER, "merge"],
    )
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    if args.stage == "all":
        for stage in STAGE_ORDER:
            run_stage(stage, args.limit)
        merge(args.limit)
    elif args.stage == "merge":
        merge(args.limit)
    else:
        run_stage(args.stage, args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
