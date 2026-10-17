# Requirements: Cull

Pre-written. Do not regenerate. Steering files hold the contracts.

## 1. Ingest

1.1 WHEN the pipeline runs on `CULL_ROOT/shoot/*.ARW` THEN it SHALL extract each embedded preview to `previews/` and rotate it upright using the EXIF Orientation.
1.2 The pipeline SHALL read capture time with subseconds, exposure time, ISO, focal length, and camera model in one exiftool batch.
1.3 Frames within 2.0 seconds of the previous frame AND with perceptual hash distance of 10 or less SHALL share a `burst_id`.

## 2. Scoring

2.1 Each frame SHALL get `sharpness` (variance of the Laplacian on a 1000px grayscale preview) and `exposure_flags` (more than 5% of pixels at 0 or 255).
2.2 Each frame SHALL get face count, eyes-closed count, and smile count from Rekognition DetectFaces, ignoring faces narrower than `config.MIN_FACE_WIDTH` (default 0.025 of frame width).
2.3 Each frame SHALL get `scene_tags` from Rekognition DetectLabels, mapped to the contract vocabulary.
2.4 Frames SHALL be grouped into moments (`group_id`, `group_label`).
2.5 Only finalists SHALL be sent to Claude for `claude_score`, `claude_reason`, `candid`, and `intentional_eyes_closed`.
2.6 Every stage SHALL cache results and re-running SHALL make zero API calls for cached frames.

## 3. Solver

3.1 `run_plan` and `top_n` SHALL pass every test in `tests/test_solver.py`.
3.2 Coverage SHALL be satisfied before filling to the target.
3.3 Every image SHALL receive a decision with a reason.

## 4. Agent

4.1 WHEN the user submits an instruction THEN the agent SHALL return a valid plan using one Bedrock Converse call with a forced `submit_plan` tool.
4.2 The agent SHALL return a 2 to 3 sentence explanation of the result.
4.3 IF Bedrock fails THEN the server SHALL fall back to `fixtures/preset_plans.json`.

## 5. Review UI

5.1 The grid SHALL group frames by moment with a pick count per moment.
5.2 Hovering a frame SHALL show its decision reason.
5.3 Clicking a frame SHALL cycle override: force pick, force reject, clear.
5.4 The rule report SHALL show each rule as met or unmet.
5.5 A toggle SHALL switch between Cull picks and the top-N baseline at the same target, highlighting moments with zero picks.
5.6 Editing the target or cap SHALL re-run the solver without an LLM call.

## 6. Export

6.1 Export SHALL write `XMP-xmp:Rating`, `XMP-xmp:Label`, and `XMP-dc:Subject` keywords to `shoot/<basename>.xmp` in one exiftool batch.
6.2 Export SHALL never modify ARW files.
