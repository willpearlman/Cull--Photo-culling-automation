# Cull: team build kit

Three people, three lanes, one GitHub repo. Every lane owns its own files,
every lane builds against the same contracts, and every Kiro session reads
those contracts automatically. That is what makes the pieces fit.

## Start here (everyone)

1. Read this file.
2. Open your lane file in `kiro-prompts/` and do segment 0.
3. Skim `.kiro/steering/contracts.md`. It is the agreement between lanes.

| Lane | Person | Prompt file | Owns |
| --- | --- | --- | --- |
| Pipeline | Will | `kiro-prompts/lane-pipeline-will.md` | `ingest.py`, `local_scores.py`, `pipeline.py`, `moments.py`, `xmp.py` |
| UI | Partner | `kiro-prompts/lane-ui-partner.md` | `server.py`, `static/*` |
| AWS and logic | Teammate 3 | `kiro-prompts/lane-aws-teammate3.md` | `solver.py`, `rekog.py`, `agent.py`, `taste.py`, `fixtures/preset_plans.json` |
| Shared | all three agree first | none | `config.py`, `.kiro/*`, `tests/*`, `fixtures/fake_scores.json`, `requirements.txt` |

## How the pieces mesh

| Mechanism | What it prevents |
| --- | --- |
| **File ownership** (table above, also in `tech.md`) | Two people editing one file. Each Kiro prompt names the only files it may touch |
| **Contracts** (`contracts.md`) | Pieces that don't fit. scores.json shape, plan shape, solver API, HTTP API, and the stage interface are fixed |
| **Stage interface** | Teammate 3's `rekog.py` and `taste.py` plug into Will's `pipeline.py` without either editing the other's file |
| **Fake data** (`fixtures/fake_scores.json`) | Waiting. The UI and agent build against fake scores before real ones exist |
| **Tests** (`tests/test_solver.py`) | A solver that compiles but breaks the demo. 14 tests define it |
| **Fallbacks in the server** | Startup crashes when another lane isn't done. Missing agent uses presets, missing export returns 0 |
| **Checkpoints** at 8:15PM and 12:00AM | Late surprises. Everyone integrates and tests together |

## Repo setup (Will, once, 5 minutes)

1. Create a private GitHub repo named `cull`.
2. Unzip the kit into it, then:

```powershell
git init
git add .
git commit -m "Cull build kit"
git branch -M main
git remote add origin https://github.com/<you>/cull.git
git push -u origin main
```

3. Settings > Collaborators: add both teammates.

## Machine setup (everyone, Windows, PowerShell)

```powershell
winget install Python.Python.3.11
winget install Git.Git
winget install Amazon.AWSCLI
winget install OliverBetz.ExifTool
exiftool -ver
```

If the ExifTool winget package fails, download the Windows executable from
exiftool.org, rename `exiftool(-k).exe` to `exiftool.exe`, keep its
`exiftool_files` folder beside it, and add that folder to PATH.

```powershell
git clone https://github.com/<will>/cull.git
cd cull
py -3.11 -m venv .venv
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned   # only if activation is blocked
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env      # fill in CULL_ROOT and model IDs
aws configure               # sponsor credentials, same region as .env
pytest -q                   # fails until the solver lands. Expected
```

Model IDs: in the Bedrock console model catalog, copy IDs for Claude models
your account can use. A strong one for `BEDROCK_AGENT_MODEL_ID`, a fast cheap
one for `BEDROCK_TASTE_MODEL_ID`.

The partner sets `SCORES_PATH=fixtures/fake_scores.json` in `.env` until real
scores exist.

## Git workflow

Everyone commits straight to `main`. File ownership means pushes don't
collide, and branches plus pull requests cost time you don't have.

```powershell
git pull --rebase            # before every segment
# ... run the segment, check it ...
git add <your files only>
git commit -m "task N: <what>"
git pull --rebase
git push
```

Then post **"pushed task N"** in the group chat. That is the status board.
Don't tick boxes in `tasks.md`. Three people editing it causes conflicts.

**Changing a shared file:** say it in chat, wait for both thumbs up, one person
edits and pushes, everyone pulls before their next segment.

**Never commit** `.env`, ARW files, previews, or `work/`. `.gitignore` handles
it. Use `git add <files>` rather than `git add .` to be safe.

## Schedule

| Time | Will (pipeline) | Partner (UI) | Teammate 3 (AWS) |
| --- | --- | --- | --- |
| 4:45 to 5:45PM | W0 XMP round trip, demo shoot | P1 server | joins 5:15, A0 setup |
| 5:45 to 7:00PM | W1 ingest, local, runner | P1, then P2 grid | A1 solver, push by 6:45 |
| 7:00 to 8:15PM | W1 (to 7:30), W2 export | P2 grid | A2 Rekognition |
| **8:15PM** | **Checkpoint 1:** local pipeline on real shoot, XMP works, solver passes, grid on fake data. Dinner | | |
| 8:45 to 11:00PM | W3 moments (to 9:45), then product work | P3 plan wiring | A2 (to 9:00), A3 agent |
| 11:00PM to 1:00AM | Run rekog on full shoot, find demo moment, slides | P4 Top-N toggle, export | A4 taste pass |
| **12:00AM** | **Checkpoint 2:** real scores in UI, Top-N drops a moment, Cull restores it, agent works | | |
| 1:00 to 3:00AM | W4 full run and freeze (from 2:00) | P5 polish | A5 support |
| 3:00 to 6:30AM | Metrics, backup video | Rehearse | Rehearse |

## Credits (1,000 each)

| Person | Planned | Reserve |
| --- | --- | --- |
| Will | ~400 | ~600 |
| Partner | ~550 | ~450 |
| Teammate 3 | ~600 | ~400 |

Caps per segment are in each lane file. They are estimates. Kiro's cost per
request varies with the model and how much it reads, so check the dashboard
after your first segment and rescale.

Will has the most reserve. If a lane falls behind, Will's Kiro can run that
lane's next segment, but only after the owner posts "Will, your turn on
<file>" in chat. Ownership of that file moves to Will until he posts it back.

**Credit rules**

1. Never ask Kiro to generate the spec. It already exists and generating one is the most expensive thing Kiro does.
2. One segment = one fresh session. Long sessions re-read a growing history every turn.
3. Paste prompts exactly. Each names its files and its stop point.
4. Skip agent hooks. A save hook runs the agent on every save. Run `pytest -q` yourself.
5. Paste the last 20 lines of an error, never the full log.
6. Two failed attempts on one error: stop Kiro, fix by hand or ask Claude chat (no Kiro credits).
7. Tune prompts in `agent.py` and `taste.py` by hand. They're plain text.

## Kill criteria

| By | If | Then |
| --- | --- | --- |
| 5:30PM | XMP round trip fails in Lightroom | Export a CSV plus a folder of copies of the picks |
| 8:30PM | Rekognition throttled or not covered | Skip A2. Taste pass flags blinks on finalists only |
| 12:00AM | Agent misparses instructions | Demo with the 3 presets. Claude only writes the explanation |
| 12:00AM | Moments are messy | Time-gap rule only (edit the number in `moments.py` by hand) |
| 1:00AM | Taste pass not done | Score from sharpness and smile count in merge. Drop intentional blinks |
