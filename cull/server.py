"""FastAPI server. UI lane (Partner), task 4. Contract: .kiro/steering/contracts.md.

Holds scores in memory. Overrides persist to config.OVERRIDES_PATH only, never
to SCORES_PATH, so the solver fixture stays clean. Optional modules (agent, xmp)
are imported inside handlers so a missing module never breaks startup.
"""
import json

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from cull import config, solver

app = FastAPI(title="Cull")

_STATIC_DIR = config.REPO_ROOT / "static"


def _load_scores():
    with open(config.SCORES_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _load_overrides():
    path = config.OVERRIDES_PATH
    if path.exists():
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_overrides(overrides):
    config.OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(config.OVERRIDES_PATH, "w", encoding="utf-8") as fh:
        json.dump(overrides, fh, indent=2)


def _images_with_overrides():
    """Fresh copy of fixture images with overrides applied in memory only."""
    data = _load_scores()
    images = data.get("images", [])
    overrides = _load_overrides()
    out = []
    for img in images:
        row = dict(img)
        rating = overrides.get(row["path"])
        if rating in (1, 5):
            row["overridden"] = True
            row["final_rating"] = rating
        out.append(row)
    return out


def _groups(images):
    groups, order = {}, []
    for img in images:
        gid = img.get("group_id")
        if gid is None:
            continue
        if gid not in groups:
            groups[gid] = {"group_id": gid,
                           "group_label": img.get("group_label") or gid,
                           "count": 0}
            order.append(gid)
        groups[gid]["count"] += 1
    return [groups[g] for g in order]


@app.get("/api/scores")
def api_scores():
    images = _images_with_overrides()
    return {"images": images, "groups": _groups(images)}


@app.post("/api/plan")
def api_plan(body: dict):
    instruction = (body or {}).get("instruction", "")
    images = _images_with_overrides()
    plan, explanation = None, None
    try:
        from cull import agent
        plan = agent.make_plan(instruction, images)
    except Exception:
        plan = None
    if plan is None:
        plan = _preset_plan(instruction)
        explanation = "Preset plan"
    result = solver.run_plan(images, plan)
    if explanation is None:
        try:
            from cull import agent
            explanation = agent.explain(plan, result)
        except Exception:
            explanation = "Preset plan"
    return {"plan": plan, "result": result, "explanation": explanation}


def _preset_plan(instruction):
    with open(config.REPO_ROOT / "fixtures" / "preset_plans.json", encoding="utf-8") as fh:
        presets = json.load(fh)
    low = (instruction or "").lower()
    for key, plan in presets.items():
        if key.lower() in low:
            return plan
    return next(iter(presets.values()))


@app.post("/api/run")
def api_run(body: dict):
    plan = (body or {}).get("plan") or {}
    images = _images_with_overrides()
    return {"result": solver.run_plan(images, plan)}


@app.get("/api/baseline")
def api_baseline(n: int = 150):
    images = _images_with_overrides()
    return {"picks": solver.top_n(images, n)}


@app.post("/api/override")
def api_override(body: dict):
    body = body or {}
    path = body.get("path")
    rating = body.get("rating")
    if not path:
        raise HTTPException(status_code=400, detail="path required")
    overrides = _load_overrides()
    if rating is None:
        overrides.pop(path, None)
    elif rating in (1, 5):
        overrides[path] = rating
    else:
        raise HTTPException(status_code=400, detail="rating must be 1, 5, or null")
    _save_overrides(overrides)
    return {"ok": True}


@app.post("/api/export")
def api_export(body: dict):
    body = body or {}
    decisions = body.get("decisions") or {}
    images = _images_with_overrides()
    try:
        from cull import xmp
        written = xmp.export(decisions, images)
    except Exception:
        return {"written": 0}
    return {"written": written}


@app.get("/thumb/{name}")
def thumb(name: str):
    src = config.PREVIEW_DIR / name
    if not src.exists():
        raise HTTPException(status_code=404, detail="preview not found")
    config.THUMB_DIR.mkdir(parents=True, exist_ok=True)
    dst = config.THUMB_DIR / name
    if not dst.exists():
        try:
            from PIL import Image
            with Image.open(src) as im:
                im.thumbnail((400, 400))
                im.convert("RGB").save(dst, "JPEG")
        except Exception:
            return FileResponse(src)
    return FileResponse(dst, media_type="image/jpeg")


if _STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")
