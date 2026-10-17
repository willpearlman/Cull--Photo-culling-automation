# Tasks: Cull

Pre-written. Run tasks only through the lane prompts in `kiro-prompts/`.
Do not tick boxes in this file (three people editing it causes merge
conflicts). Post "pushed task N" in the group chat instead.

Lanes: [P] Pipeline (Will) · [U] UI (Partner) · [A] AWS and logic (Teammate 3)

## Setup (done by hand, no credits)

- [x] 0.1 `cull/__init__.py`, `cull/config.py`, `cull/solver.py` stub, `requirements.txt`, fixtures, tests.

## [P] Pipeline: Will

- [ ] 1. `ingest.py` + `local_scores.py` + `pipeline.py` (stage runner for all five stages, caches, merge, `--limit`).
  - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.6_
- [ ] 2. `xmp.py`: `export(decisions, images) -> int` and CLI.
  - _Requirements: 6.1, 6.2_
- [ ] 3. `moments.py`: `run()` returning group_id and group_label.
  - _Requirements: 2.4_

## [U] UI: Partner

- [ ] 4. `server.py`: all endpoints in contracts.md on `fixtures/fake_scores.json`.
- [ ] 5. `static/`: grid by moment, thumbnails or grey filename tiles, reason on hover, override click cycle.
  - _Requirements: 5.1, 5.2, 5.3_
- [ ] 6. UI wiring: instruction to `/api/plan`, rule report, editable target and cap, Re-plan via `/api/run`.
  - _Requirements: 5.4, 5.6_
- [ ] 7. Cull vs Top-N toggle with zero-pick moments in red. Export button.
  - _Requirements: 5.5, 6.1_

## [A] AWS and logic: Teammate 3

- [ ] 8. `solver.py`: `run_plan` and `top_n` until `pytest tests/test_solver.py -q` passes. Push immediately.
  - _Requirements: 3.1, 3.2, 3.3_
- [ ] 9. `rekog.py`: `run()` with faces, labels, size threshold, tag mapping.
  - _Requirements: 2.2, 2.3_
- [ ] 10. `agent.py`: `make_plan(instruction, images)`, `explain(plan, result)`, CLI.
  - _Requirements: 4.1, 4.2, 4.3_
- [ ] 11. `taste.py`: `run()` on finalists only, forced `submit_score` tool.
  - _Requirements: 2.5_

## Together

- [ ] 12. Full pipeline run on the demo shoot, freeze `work/scores.json`, end-to-end test into Lightroom.
