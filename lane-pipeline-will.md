# Pipeline lane (Will): ingest, local scores, stage runner, moments, export

Your files: `cull/ingest.py`, `cull/local_scores.py`, `cull/pipeline.py`,
`cull/moments.py`, `cull/xmp.py`. Nothing else.

Each segment = one NEW Kiro session. Pull first, paste the prompt, run the
check yourself, commit, push, post "pushed task N" in the group chat, close the
session.

Budget: about 400 planned. You have the most spare credits on the team. If
another lane falls behind, your Kiro can run their next segment, but only after
they say "your turn on <file>" in chat so two people never edit one file.

---

## W0. XMP round trip and demo shoot (4:45 to 5:30PM, no Kiro)

This decides go or no-go.

1. Copy 5 ARW files into `C:\cull-demo\shoot\` and import that folder into Lightroom Classic.
2. PowerShell, with your real filenames (.xmp basename must match the .ARW):

```powershell
cd C:\cull-demo\shoot
exiftool -XMP-xmp:Rating=5 -XMP-xmp:Label=Green -XMP-dc:Subject+=group DSC00001.xmp
exiftool -XMP-xmp:Rating=1 DSC00002.xmp
```

3. Lightroom: select the 5, Metadata > Read Metadata from Files.
4. Pass: 5 stars and green label on the first, 1 star on the second.

Fail by 5:30PM: export becomes a CSV plus a folder of copies (kill criterion).

Then copy the demo shoot (300 to 500 frames with clear groups or tables) into
`C:\cull-demo\shoot\`. Write down [N] frames, [K] delivered, [X] hours.

---

## W1. Ingest, local scores, stage runner (5:30 to 7:30PM, cap 180)

```
Execute task 1 in .kiro/specs/cull/tasks.md. Follow design.md, the Stage
interface section of contracts.md, and the steering files exactly.

Files you may create or edit: cull/ingest.py, cull/local_scores.py,
cull/pipeline.py. Do not create or edit any other file, including
cull/rekog.py, cull/moments.py, and cull/taste.py.

ingest.py and local_scores.py each expose run(images, cached) as defined in
contracts.md. pipeline.py is the only code that reads or writes cache files.
CLI: python -m cull.pipeline --stage all|ingest|local|rekog|moments|taste|merge
[--limit N]. For each stage it imports cull.<module>.run; if the module or run
does not exist, print "skipping <stage>: not built yet" and continue. merge
overlays caches in the order in contracts.md, adds "candid" to scene_tags when
candid is true, fills missing contract fields with null, and writes
config.SCORES_PATH. Until moments exists, set group_id to burst_id and
group_label to "Burst <burst_id>".

Test only with --limit 10. Stop when python -m cull.pipeline --stage all
--limit 10 writes a valid scores.json. Reply in 6 lines max.
```

**Check:** open `work\scores.json`. 10 entries, sharp frames above 150, bursts
look right, previews upright. Then run `--stage ingest` and `--stage local` on
the full shoot (no API cost). Push. Teammate 3 tests rekog through your runner.

---

## W2. XMP export (7:30 to 8:15PM, cap 60)

```
Execute task 2 in .kiro/specs/cull/tasks.md. Follow the xmp.py notes in
design.md exactly: one ExifToolHelper, et.execute with raw args, never
set_tags, never touch .ARW files.

Files you may create or edit: cull/xmp.py only.

Expose export(decisions: dict, images: list[dict]) -> int, where decisions is
the solver's decisions map (rating 1 or 5, label, reason). Scene tags go in
XMP-dc:Subject. Also a CLI: python -m cull.xmp --from <scores.json> that writes
each image's final_rating and final_label, skipping nulls.

Stop when the CLI writes sidecars for a 5-image test file. Reply in 6 lines max.
```

**Check:** Read Metadata from Files in Lightroom shows the ratings. Push. The
partner's Export button calls this.

**8:15PM checkpoint 1** (all three): local pipeline on the real shoot, XMP
works, solver tests pass, server and grid work on fake data. Eat. Check credits.

---

## W3. Moments (8:45 to 9:45PM, cap 80)

```
Execute task 3 in .kiro/specs/cull/tasks.md. Follow the moments.py notes in
design.md exactly: 90-second gap rule, primary tag rule with the 3-frame
confirmation, label format like "group, 9:40-9:43PM".

Files you may create or edit: cull/moments.py only. Expose run(images,
cached) per contracts.md. It recomputes every image and ignores cached. When
scene_tags is null (rekog not run yet), use only the time-gap rule.

Stop when python -m cull.pipeline --stage moments then --stage merge gives
sensible moments on the full shoot. Reply in 6 lines max.
```

**Check:** scroll moments in the grid (partner's UI on real scores). Too many
tiny moments: raise the gap. Too few: lower it. Edit the number by hand.

---

## Product work (9:45PM to 2:00AM, no Kiro)

- Run `--stage rekog` and later `--stage taste` on the full shoot when Teammate 3 says they're ready.
- Find the moment a plain top-N cut drops at your demo target. That is the demo's center. Lower the target until one drops if needed.
- Build the agreement metric: compare Cull's picks with your real delivered picks from this shoot.
- Write the slides. Fill the real numbers.

**12:00AM checkpoint 2** (all three): real scores in the UI, Top-N drops a
moment, Cull restores it, the agent turns an instruction into a plan.

---

## W4. Full run and freeze (2:00 to 3:00AM, cap 80)

```powershell
python -m cull.pipeline --stage all
copy C:\cull-demo\work\scores.json C:\cull-demo\work\scores.frozen.json
```

Kiro only to fix a crash in your own files, with the last 20 lines of the error:

```
The full pipeline run crashed. Fix only the cause shown below. Do not
refactor. Files you may edit: <the file in the traceback, only if it is in
the pipeline lane>.

<paste last 20 lines>
```

A crash in rekog.py or taste.py goes to Teammate 3.

Then record the backup video and rehearse.
