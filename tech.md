---
inclusion: always
---

# Cull: tech rules

## Stack

- Python 3.11 on Windows. Use `pathlib` for every path. Never hardcode `/` or `\`.
- boto3 for Rekognition and Bedrock (Converse API). Region and model IDs come
  from environment variables in `cull/config.py`. Never hardcode model IDs.
- exiftool via the PyExifTool package (`exiftool.ExifToolHelper`), one
  long-running process per batch. Never spawn exiftool once per image.
- OpenCV (`opencv-python-headless`), imagehash, Pillow for local scoring.
- FastAPI + uvicorn. Frontend is plain HTML, CSS, and vanilla JS in `static/`,
  served by FastAPI. No npm, no bundler, no framework.
- pytest for tests. No other test tools.

## File ownership (three lanes, never edit another lane's files)

| Lane | Owner | Files |
| --- | --- | --- |
| Pipeline | Will | `cull/ingest.py`, `cull/local_scores.py`, `cull/moments.py`, `cull/pipeline.py`, `cull/xmp.py` |
| UI | Partner | `cull/server.py`, `static/*` |
| AWS and logic | Teammate 3 | `cull/solver.py`, `cull/rekog.py`, `cull/taste.py`, `cull/agent.py`, `fixtures/preset_plans.json` |
| Shared, change only after all three agree | everyone | `cull/config.py`, `.kiro/steering/*`, `.kiro/specs/*`, `tests/*`, `fixtures/fake_scores.json`, `requirements.txt` |

If a task seems to need a file outside your lane, stop and say which file and
why. Do not edit it.

## Conventions

- Functions take and return plain dicts matching `contracts.md`. No classes
  unless a library requires one.
- Every network call: retries with backoff (`botocore.config.Config(retries={"mode": "adaptive", "max_attempts": 6})`),
  thread pool of `config.MAX_WORKERS` (default 6).
- Every pipeline stage caches its output to `work/<stage>.json` and skips
  images already in the cache. Re-running a stage must cost zero API calls.
- Log one line per batch, not per image.
- Keep files under 250 lines.

## How to work (keeps credit use low)

- Do only the task you were given. Touch only the files listed in the prompt.
- Do not create README, docs, examples, or extra test files unless asked.
- Do not refactor code outside the task.
- Do not run the pipeline on the full shoot. Use `--limit 10` when testing.
- Do not install packages that are not in `requirements.txt`. Ask first.
- When done, reply with at most 6 lines: what changed, how to run it, what is untested.
