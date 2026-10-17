---
inclusion: always
---

# Cull: product rules

Cull culls an event photo shoot from a plain-English instruction. It scores every
frame once, groups frames into moments, turns the instruction into a rule list,
and picks frames so every rule is met. Ratings go back to Lightroom Classic as
.xmp sidecars. The original photos are never modified.

## The differentiator

Competitors rank by score and cut at N. That can drop a whole moment. Cull
guarantees coverage rules ("at least one of every group") and reports any rule
it could not meet. Every frame gets a readable reason.

## In scope (hackathon build)

- Ingest Sony ARW files, extract embedded previews, read EXIF
- Local scoring: blur, exposure clipping, bursts
- Rekognition faces and labels, moment grouping
- Claude taste pass on finalists only
- Solver with filter, dedupe_bursts, coverage, cap, prefer, target
- Agent: instruction to rule list (one Bedrock call), short explanation
- Plain HTML review grid with reasons, overrides, rule report, top-N baseline view
- XMP export

## Out of scope (do not build)

Face identity or face collections, client galleries, Lightroom plugin, free-text
search, taste learning, S3, Lambda, user accounts, databases, React or any
frontend build step.

## Privacy

Detect faces, never identify them. Never call IndexFaces, SearchFaces, or
CreateCollection.
