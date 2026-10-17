# UI lane (Partner): server and review grid

Your files: `cull/server.py`, `static/*`. Nothing else.

Each segment = one NEW Kiro session. Pull first, paste the prompt, run the
check yourself, commit, push, post "pushed task N" in the group chat, close the
session.

Budget: about 550 planned, 450 reserve.

Work on fake data (`SCORES_PATH=fixtures/fake_scores.json` in `.env`) until
Will's real `scores.json` exists. The fake shoot has 10 moments, and Table 7
(G07) is the one a plain top-10 cut drops.

Dependencies: the solver arrives from Teammate 3 around 6:45PM (stub until
then). `agent.py` arrives around 11:00PM (presets until then). `xmp.export`
arrives from Will around 8:15PM.

---

## P1. Server on fake data (4:45 to 6:15PM, cap 120)

```
Execute task 4 in .kiro/specs/cull/tasks.md. Build cull/server.py with every
endpoint in the HTTP API table in contracts.md, following the server.py notes
in design.md.

Files you may create or edit: cull/server.py only.

Import cull.agent, cull.xmp, and cull.solver inside the handlers so a missing
module never breaks startup. /api/plan calls cull.agent.make_plan(instruction,
images) and cull.agent.explain(plan, result); if cull.agent is missing or
raises, use the best-matching plan in fixtures/preset_plans.json and
explanation "Preset plan". /api/export calls cull.xmp.export(decisions,
images); if missing, return {"written": 0}. Overrides persist to
config.OVERRIDES_PATH, never to SCORES_PATH (the fixture must stay unchanged
for the solver tests). /thumb/{name} returns 404 when the preview is missing.

Run with: uvicorn cull.server:app --reload. Stop when every endpoint returns
valid JSON on fixtures/fake_scores.json. Reply in 6 lines max.
```

**Check:** open `http://127.0.0.1:8000/docs` and try each endpoint.

---

## P2. Review grid (6:15 to 8:15PM, cap 150)

```
Execute task 5 in .kiro/specs/cull/tasks.md. Build static/index.html,
static/app.js, and static/style.css following the static/ notes in design.md.
Plain HTML, CSS, and vanilla JS. No frameworks, no build step, no CDN imports.

Files you may create or edit: static/* only.

On load, GET /api/scores, then POST /api/run with a default plan (copy the
first plan in fixtures/preset_plans.json into app.js as DEFAULT_PLAN, with
target set to 10 while on fake data), and
render moments as rows (header: group_label and pick count). Each tile shows
/thumb/<basename> or, on 404, a grey tile with the filename. Picked tiles get a
green border. Hover shows the decision reason in an overlay. Click cycles
override: force pick (POST /api/override rating 5), force reject (rating 1),
clear (null), then re-runs the current plan through /api/run. Keep all state
in one JS object.

Leave space for a left panel and a top bar. Those come in P3. Stop when the
grid renders the fake shoot. Reply in 6 lines max.
```

**Check:** 10 moment rows, 60 grey tiles, hover and click work. Once the
solver lands, picks show green borders and Table 7 has one.

**8:15PM checkpoint 1.** Eat. Check credits.

---

## P3. Plan wiring and rule panel (8:45 to 10:45PM, cap 120)

```
Execute task 6 in .kiro/specs/cull/tasks.md.

Files you may edit: static/* only.

Top bar: instruction textarea, Run button (POST /api/plan, show a spinner),
Export button (wired in P4). Left panel: the current plan's target and cap as
number inputs, allow_intentional as a checkbox, a Re-plan button that edits
the plan object in place and POSTs /api/run (no LLM). Below that, the rule
report: one row per report entry, green check when met, red X with detail
when not. Show the explanation text under the report. Re-render the grid from
each result. Stop when Run and Re-plan both update the grid on fake data.
Reply in 6 lines max.
```

**Check:** Run returns a preset until Teammate 3's agent lands. Then retest
with a real instruction.

---

## P4. Top-N toggle and export (10:45PM to 12:45AM, cap 100)

```
Execute task 7 in .kiro/specs/cull/tasks.md.

Files you may edit: static/* only.

Add a two-way toggle in the left panel: "Cull" and "Top-N". Top-N calls
GET /api/baseline?n=<current target> and marks those paths as picked. In both
views, a moment header with 0 picks turns red and shows "0 picks". Switching
views keeps the scroll position. Export button POSTs /api/export with the
current Cull result's picks and decisions, then shows "Wrote N sidecars".
Stop when toggling on fake data shows Table 7 red in Top-N and covered in
Cull. Reply in 6 lines max.
```

**Check:** this toggle is the center of the demo. The red should be obvious
from across a room.

**12:00AM checkpoint 2** (all three): real scores in the UI, Top-N drops a
moment, Cull restores it.

---

## P5. Demo polish (12:45 to 3:00AM, cap 60)

Switch `.env` to the real scores (remove `SCORES_PATH`). No new features. Kiro
only for visual fixes you can describe in one sentence:

```
In static/style.css only: <one specific change, e.g. 6 tile columns at 1440px
and an 18px red "0 picks" header>. Do not change JS or HTML.
```

Then rehearse the demo twice with the team.
