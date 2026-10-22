---
inclusion: always
---

# Cull: contracts

These shapes are fixed. Code on both lanes builds against them.
`fixtures/fake_scores.json` is a valid example of `scores.json`.

## scores.json

```json
{
  "shoot": "formal-2026-10-10",
  "images": [
    {
      "path": "shoot/DSC01234.ARW",
      "preview": "previews/DSC01234.jpg",
      "capture_time": "2026-10-10T21:42:17.340",
      "burst_id": "B017",
      "group_id": "G05",
      "group_label": "group, 9:40-9:43PM",
      "sharpness": 412.8,
      "exposure_flags": [],
      "face_count": 6,
      "eyes_closed_count": 0,
      "smile_count": 4,
      "scene_tags": ["group", "indoor"],
      "intentional_eyes_closed": false,
      "claude_score": 8,
      "claude_reason": "Everyone looking, best of burst",
      "final_rating": null,
      "final_label": null,
      "decision_reason": null,
      "overridden": false
    }
  ]
}
```

- `path` and `preview` are relative to `CULL_ROOT` (see layout below), forward slashes.
- `exposure_flags`: subset of `["underexposed", "overexposed"]`.
- `scene_tags` vocabulary: `group`, `couple`, `candid`, `dance floor`, `food`,
  `indoor`, `outdoor`, `portrait`, `detail`.
- `claude_score`: number 1 to 10, or null if unscored. The local aesthetic stage scores
  every frame with one decimal. The legacy Claude taste stage gave integers to finalists only.
- `overridden: true` means the user set `final_rating` by hand. Rating 5 forces
  a pick, rating 1 forces a reject.

## Plan (agent output, solver input)

```json
{
  "target": 150,
  "rules": [
    {"type": "filter", "max_eyes_closed": 0, "allow_intentional": true, "min_sharpness": 150, "drop_exposure_flags": true},
    {"type": "dedupe_bursts", "keep": 1},
    {"type": "coverage", "by": "group_id", "min_per_group": 1},
    {"type": "cap", "by": "group_id", "max_per_group": 3},
    {"type": "prefer", "tags": ["candid"], "weight": 1.5}
  ]
}
```

Plans from the agent also carry `unsupported` (requests Cull cannot act on, shown as "Cull
can't detect: ..."), `warnings` (contradictions found before solving) and `target_defaulted`
(true when the instruction gave no number, so the target is `DEFAULT_KEEP_FRACTION` of the
shoot). The solver ignores these fields. When the user named no cap, the agent sizes the cap
from each moment's usable frames so the cap never stops the target being met.

`prefer` tags come from the genre's vocabulary (`scenes.tag_vocab(GENRE)`): the base tags plus
the genre's tags in `fixtures/vocab.json`.

`cap` is per moment, not per person. Cull never identifies people, so "max 3 of
the same couple" maps to a per-moment cap.

## Solver API (`cull/solver.py`)

```python
run_plan(images: list[dict], plan: dict) -> dict
# {
#   "picks": ["shoot/DSC01234.ARW", ...],          # pick order
#   "decisions": {path: {"rating": 5 | 1, "label": str | None, "reason": str}},  # every image
#   "report": [{"type": "coverage" | "cap" | "target" | ..., "met": bool, "detail": str}],
#   "unmet_groups": ["G10"]
# }
top_n(images: list[dict], n: int) -> list[str]
# Baseline score-and-cut: default filter, best frame per burst, top n by claude_score.
```

Reasons start with `Kept:` or `Rejected:` and name the cause, for example
`Rejected: blurry`, `Rejected: eyes closed (1 of 6 faces)`,
`Rejected: weaker frame of burst B017`, `Kept: coverage pick for Table 7`,
`Kept: user override`.

## Stage interface (how stages plug into one pipeline)

`cull/pipeline.py` (Will) owns all cache files and the CLI. Stage modules never
read or write cache files themselves. Each stage module exposes:

```python
def run(images: list[dict], cached: dict) -> dict:
    """images: merged rows so far (contract shape, fields may be null).
    cached: {path: {...}} already in this stage's cache. Skip those paths.
    Returns {path: {field: value}} for newly processed images only."""
```

| Stage | Module | Cache | Fields it returns |
| --- | --- | --- | --- |
| ingest | `ingest.py` | `work/exif.json` | path, preview, capture_time, burst_id, exposure_time, iso, focal_length, model |
| local | `local_scores.py` | `work/local.json` | sharpness, exposure_flags |
| faces | `faces.py` | `work/faces.json` | face_count, eyes_closed_count, smile_count, faces (raw per-face scores) |
| scenes | `scenes.py` | `work/scenes.json` | scene_tags, scene_scores, embedding (needs faces) |
| moments | `moments.py` | `work/moments.json` | group_id, group_label (recomputes all images, ignores `cached`) |
| aesthetic | `aesthetic.py` | `work/aesthetic.json` | claude_score, claude_reason, intentional_eyes_closed, candid (needs faces, scenes) |

Every stage runs locally with no network (models download once on first use). The old AWS
stages (rekog, taste) are removed. Their caches, `work/rekog.json` and `work/taste.json`,
stay on disk as benchmark and training labels and are never merged.

Merge order: ingest, local, faces, scenes, moments, aesthetic. If `candid` is true, merge
adds `"candid"` to `scene_tags`. A stage module that does not exist yet is
skipped with a one-line message.

## Label map (Lightroom default label set)

`group` Green, `dance floor` Blue, `candid` Yellow, `couple` Purple, `food` Red.
First matching tag wins. No match: no label.

## HTTP API (`cull/server.py`)

| Method | Path | Body | Returns |
| --- | --- | --- | --- |
| GET | `/api/scores` | none | `{"images": [...], "groups": [{"group_id", "group_label", "count"}]}` |
| POST | `/api/plan` | `{"instruction": str}` | `{"plan", "result", "explanation"}` |
| POST | `/api/run` | `{"plan": {...}}` | `{"result", "warnings"}` (no LLM call; warnings re-checked for the edited plan) |
| GET | `/api/baseline?n=150` | none | `{"picks": [...]}` |
| POST | `/api/override` | `{"path": str, "rating": 1 | 5 | null}` | `{"ok": true}` (null clears). Saved to `config.OVERRIDES_PATH` as `{path: rating}`, applied in memory. Never written into scores.json |
| POST | `/api/export` | `{"picks": [...], "decisions": {...}}` | `{"written": int}` |
| GET | `/thumb/{name}` | none | 400px JPEG, cached in `work/thumbs/` |
| GET | `/preview/{name}` | none | Full-resolution preview JPEG from `previews/`, served as-is (read only). Used for grid tiles at 3 columns or fewer |

## Work folder layout

`CULL_ROOT` is an environment variable pointing at one shoot's working folder.

```
<CULL_ROOT>/
  shoot/*.ARW           originals, never written
  shoot/*.xmp           sidecars written by export, same basename as the ARW
  previews/*.jpg        extracted embedded previews, rotated upright
  work/exif.json        stage caches (written only by pipeline.py)
  work/local.json
  work/rekog.json
  work/moments.json
  work/taste.json
  work/scores.json      merged output, the file the server reads
  work/thumbs/*.jpg
```
