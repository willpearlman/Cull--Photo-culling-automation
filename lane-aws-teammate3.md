# AWS and logic lane (Teammate 3): solver, Rekognition, agent, taste

Your files: `cull/solver.py`, `cull/rekog.py`, `cull/agent.py`,
`cull/taste.py`, `fixtures/preset_plans.json`. Nothing else.

Each segment = one NEW Kiro session. Pull first, paste the prompt, run the
check yourself, commit, push, post "pushed task N" in the group chat, close the
session.

Budget: about 600 planned, 400 reserve.

Your stage modules (`rekog.py`, `taste.py`) never touch cache files. They
expose `run(images, cached)` and Will's `pipeline.py` calls them. Read the
"Stage interface" section of `.kiro/steering/contracts.md` before A2.

---

## A0. Setup (5:15 to 5:45PM, no Kiro)

Follow the setup in `README-KIRO.md`. Then confirm Bedrock with one call:

```powershell
python -c "import boto3; print(boto3.client('bedrock-runtime').converse(modelId='<agent model id>', messages=[{'role':'user','content':[{'text':'Say ok'}]}])['output']['message']['content'][0]['text'])"
```

Then 20 quick calls in a loop. Any throttling: tell the team and ask the
sponsor about per-minute limits and whether Rekognition is covered.

---

## A1. Solver (5:45 to 6:45PM, cap 100)

No AWS needed. The tests define the whole job.

```
Execute task 8 in .kiro/specs/cull/tasks.md. Replace the stub in
cull/solver.py with a real implementation of run_plan and top_n that passes
every test in tests/test_solver.py. Follow the solver notes in design.md and
the reason wording in contracts.md.

Files you may edit: cull/solver.py only. Do not edit tests or fixtures.

Pure Python, no pandas. Run pytest tests/test_solver.py -q after each change.
Stop when all tests pass. Reply in 6 lines max.
```

**Check:** `pytest -q` shows 14 passed. Push right away and post in chat. The
partner's grid shows real picks the moment this lands.

---

## A2. Rekognition (7:00 to 9:00PM, cap 150)

```
Execute task 9 in .kiro/specs/cull/tasks.md. Follow the rekog.py notes in
design.md exactly, including the face width threshold, the 80 confidence
cutoff, the label-to-tag map, and skipping frames with sharpness below
config.MIN_SHARPNESS.

Files you may create or edit: cull/rekog.py only. Do not edit pipeline.py.

Expose run(images, cached) per the Stage interface in contracts.md: skip paths
in cached, return {path: {face_count, eyes_closed_count, smile_count,
scene_tags}} for the rest. Read previews from config.CULL_ROOT / image
["preview"]. boto3 rekognition with Image={"Bytes": ...}, the adaptive retry
config from tech.md, ThreadPoolExecutor of config.MAX_WORKERS. Never call
IndexFaces, SearchFaces, or any collection API.

Add a __main__ block that runs run() on the first 5 previews in
config.PREVIEW_DIR and prints the results. Stop when that prints sensible
faces and tags. Reply in 6 lines max.
```

**Check:** look at the 5 frames by eye. Blinks and tags right? False blinks on
small background faces: raise `MIN_FACE_WIDTH` in `.env`. Once Will's runner is
pushed (about 7:30PM), test `python -m cull.pipeline --stage rekog --limit 10`.
Tell Will when it's ready for the full shoot.

---

## A3. Agent (9:00 to 11:00PM, cap 150)

```
Execute task 10 in .kiro/specs/cull/tasks.md. Build cull/agent.py following
the agent.py notes in design.md and the plan schema in contracts.md.

Files you may create or edit: cull/agent.py only.

make_plan(instruction, images) -> plan: one Bedrock Converse call with
config.BEDROCK_AGENT_MODEL_ID, a system prompt holding the rule schema and a
shoot summary (frame count, moments with labels and frame counts, tag counts),
one tool submit_plan whose inputSchema is the plan schema, and
toolChoice {"tool": {"name": "submit_plan"}}. Validate: clamp target to
1..len(images), drop unknown rule types, fill missing rule fields with the
defaults from the first plan in fixtures/preset_plans.json. Map per-person
requests ("max 3 of the same couple") to a per-moment cap.

explain(plan, result) -> str: one short call, max 120 output tokens, 2 to 3
sentences, names any unmet rule.

Add a __main__ block: python -m cull.agent "<instruction>" prints the plan JSON
using fixtures/fake_scores.json. Stop when these give sensible plans:
1. "Cull this formal to about 150. At least one of every group. No blinks
   except intentional moments. Favor candids."
2. "Keep 40, max 2 per moment, strict on blinks."
3. "Two of every group, around 200."
Reply in 6 lines max.
```

**Check:** read the three plans. Wrong mapping: edit the system prompt text
yourself, not through Kiro. Push and tell the partner. Their Run button
switches from presets to the real agent with no UI change.

**12:00AM checkpoint 2** (all three).

---

## A4. Taste pass (11:00PM to 1:00AM, cap 120)

```
Execute task 11 in .kiro/specs/cull/tasks.md. Follow the taste.py notes in
design.md exactly: finalists only, 1024px JPEG bytes, Bedrock Converse with
config.BEDROCK_TASTE_MODEL_ID, one forced tool submit_score with the schema in
design.md, reason of 12 words or fewer.

Files you may create or edit: cull/taste.py only. Do not edit pipeline.py.

Expose run(images, cached) per the Stage interface in contracts.md. Select
finalists from images, skip paths in cached, print the finalist count before
calling Bedrock, and return {path: {claude_score, claude_reason,
intentional_eyes_closed, candid}}. Add a __main__ block that scores the first
3 previews. Stop when 3 frames get scores and reasons. Reply in 6 lines max.
```

**Check:** read the reasons. Generic: edit the prompt text yourself. Then
`python -m cull.pipeline --stage taste --limit 10`, then tell Will it's ready.

Not done by 1:00AM: drop it and tell Will. He'll score from sharpness and smile
count in merge.

---

## A5. Support (1:00 to 3:00AM, cap 80)

No new features. Fix crashes in your files during Will's full run, with the
last 20 lines of the error:

```
The full pipeline run crashed in <rekog.py or taste.py>. Fix only the cause
shown below. Do not refactor. Files you may edit: <that file>.

<paste last 20 lines>
```

Then help rehearse. Know the answer to "how does the coverage rule work?"
because it's your code.
