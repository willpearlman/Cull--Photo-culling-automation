# Design: Cull

Pre-written. Do not regenerate.

## Data flow

```
shoot/*.ARW
  -> ingest.py        previews/, work/exif.json (capture time, bursts)
  -> local_scores.py  work/local.json (sharpness, exposure)
  -> rekog.py         work/rekog.json (faces, labels -> scene_tags)
  -> moments.py       group_id, group_label (no API)
  -> taste.py         work/taste.json (finalists only)
  -> pipeline.py      merges all caches -> work/scores.json
  -> server.py        reads scores.json, calls solver.py and agent.py
  -> static/          grid, rule report, baseline toggle, export button
  -> xmp.py           shoot/*.xmp
```

`python -m cull.pipeline --stage all|ingest|local|rekog|moments|taste|merge [--limit N]`

Every stage module exposes `run(images, cached) -> {path: {fields}}` (see
"Stage interface" in contracts.md). `pipeline.py` alone reads and writes the
cache files, applies `--limit`, and skips modules that do not exist yet. This
is what lets three people build stages without touching each other's files.

## Module notes

**config.py** reads `.env` via python-dotenv: `CULL_ROOT`, `AWS_REGION`,
`BEDROCK_AGENT_MODEL_ID`, `BEDROCK_TASTE_MODEL_ID`, `MAX_WORKERS=6`,
`MIN_FACE_WIDTH=0.025`, `SCORES_PATH` (defaults to `CULL_ROOT/work/scores.json`).
`SCORES_PATH=fixtures/fake_scores.json` runs the server on fake data.

**ingest.py**
- `exiftool -b -PreviewImage -w <CULL_ROOT>/previews/%f.jpg -ext ARW <CULL_ROOT>/shoot` through ExifToolHelper.execute.
- Rotate previews with Pillow using the ARW's Orientation tag (1, 3, 6, 8).
- Capture time = `DateTimeOriginal` + `SubSecTimeOriginal` when present. Will's Sony files have no `SubSecTimeOriginal`, so times are whole seconds.
- Bursts: sort by capture time, then by filename (Sony numbers frames in shot order, so this orders frames within the same second). New burst when gap > 2.0 s or phash distance > 10 from the previous frame.

**local_scores.py**: grayscale preview resized to 1000px long edge. Sharpness = `cv2.Laplacian(img, cv2.CV_64F).var()`. Underexposed if more than 5% of pixels are 0, overexposed if more than 5% are 255.

**rekog.py**
- Resize preview to 1600px long edge, JPEG quality 85 (stays under the 5 MB byte limit).
- `detect_faces(Image={"Bytes": b}, Attributes=["ALL"])`. Keep faces with `BoundingBox.Width >= MIN_FACE_WIDTH` and `>= 0.25 × the largest face width in the frame` (drops background bystanders). Eyes closed = `EyesOpen.Value is False and EyesOpen.Confidence >= 80`. Smile likewise.
- `detect_labels(Image={"Bytes": b}, MaxLabels=25, MinConfidence=70)`. Map:
  - `group`: kept face_count >= 4, or labels Crowd, Audience, Team
  - `couple`: kept face_count == 2
  - `portrait`: kept face_count == 1
  - `dance floor`: Dance Pose, Night Life, Party, Disco, Club, Dancing
  - `food`: Food, Meal, Dinner, Dish, Cake
  - `detail`: no faces and labels Flower, Jewelry, Decoration, Table Setting
  - `indoor` / `outdoor`: Indoors / Outdoors, Nature, Sky
- Skip blurry frames (sharpness below `config.MIN_SHARPNESS`, default 170 on the max-tile scale) to save calls. They get face_count 0 and no tags.

**moments.py** (no API): sort by capture time. Primary tag = first of
`group, couple, dance floor, food, detail, portrait`. Start a new moment when the
gap from the previous frame is more than 90 s, or when the primary tag changes and
stays changed for the next 3 frames. Label = `"{primary tag}, {start}-{end}"`
with times like `9:40-9:43PM`.

**taste.py**
- Finalists = sharp, no exposure flag, top 2 per burst by sharpness, plus any
  frame with eyes_closed_count > 0 and face_count <= 2 (possible intentional moment).
- Bedrock Converse with the preview (1024px JPEG bytes) and a forced tool
  `submit_score` returning `{score: 1-10, reason: <= 12 words, candid: bool, intentional_eyes_closed: bool}`.
- `candid: true` adds the `candid` tag.

**solver.py**: pure Python, no pandas. Order: overrides, filter, dedupe_bursts
(keep best by score then sharpness), coverage (best frame of each moment until
`min_per_group`), fill to target by score with prefer weight, respect cap.
Ties break by sharpness, then path, so results are deterministic. Must pass
`tests/test_solver.py`.

**agent.py**
- System prompt includes the rule schema and a shoot summary (frame count,
  moment list with labels, tag counts) so one call is enough.
- Converse with `toolConfig` holding one tool, `submit_plan`, whose input schema
  is the plan schema, and `toolChoice={"tool": {"name": "submit_plan"}}`.
- Validate the plan. Clamp target to 1..len(images). Drop unknown rule types.
- `explain(plan, result)`: second short call, max 120 tokens, 2 to 3 sentences
  naming unmet rules.

**server.py**: FastAPI. Holds scores in memory. Overrides are saved to
`config.OVERRIDES_PATH` and applied in memory (`overridden`, `final_rating`)
before every solver call. Never write to `SCORES_PATH`. Mounts `static/` at `/` and `previews/` at `/previews`.
`/thumb/{name}` makes 400px JPEGs on first request and caches them. On Bedrock
error in `/api/plan`, use the preset whose key best matches the instruction
(lowercase substring match), else the first preset.

**static/**: `index.html`, `app.js`, `style.css`. Layout: top bar (instruction
box, Run, Export), left panel (editable target and cap, allow-intentional toggle,
Re-plan button, rule report, Cull vs Top-N toggle), main area (moments as rows,
header shows label and pick count, red when 0). Tiles: thumbnail, green border
when picked, override badge, reason in a hover overlay. Missing thumbnail shows
the filename on a grey tile, so fake data works.

**xmp.py**: open one `ExifToolHelper` (stay-open process) and, per image, call
`et.execute("-XMP-xmp:Rating=5", "-XMP-xmp:Label=Green", "-XMP-dc:Subject+=group", "-overwrite_original", str(xmp_path))`
where `xmp_path = shoot/<basename>.xmp`. Writing to a missing .xmp makes
exiftool create it. Use `execute` with raw args, not `set_tags`, so a missing
file is not treated as an error. Labels with no match send `-XMP-xmp:Label=`
(empty clears it).

## Error handling

Network errors: retry via botocore adaptive mode, then mark the image with
`"error": "<short>"` in the stage cache and continue. A failed image never
stops a stage.
