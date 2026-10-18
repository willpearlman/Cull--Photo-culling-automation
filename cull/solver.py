"""Rule solver. AWS and logic lane (Teammate 3), task 8. Contract: .kiro/steering/contracts.md.

Pure Python. Order: overrides, filter, dedupe_bursts, coverage, fill (prefer weight), cap.
Ties break by sharpness, then path, so results are deterministic. Input is never mutated.
"""
from cull import config

DEFAULT_FILTER = {"type": "filter", "max_eyes_closed": 0, "allow_intentional": True,
                  "min_sharpness": config.MIN_SHARPNESS, "drop_exposure_flags": True}


def _score(img):
    s = img.get("claude_score")
    return float(s) if s is not None else 0.0


def _sharp(img):
    return float(img.get("sharpness") or 0.0)


def _rank_key(score_fn):
    """Sort key: highest score, then highest sharpness, then path."""
    return lambda img: (-score_fn(img), -_sharp(img), img["path"])


def _rules(plan, rtype):
    return [r for r in plan.get("rules", []) if r.get("type") == rtype]


def _filter_failures(img, rule):
    """Every check of one filter rule the image fails: [(kind, short name, reason text)]."""
    out = []
    min_sharp = rule.get("min_sharpness")
    if min_sharp is not None and _sharp(img) < min_sharp:
        out.append(("blur", "blurry", f"blurry (sharpness {_sharp(img):.0f} < {min_sharp:g})"))
    flags = img.get("exposure_flags") or []
    if rule.get("drop_exposure_flags", True) and flags:
        out.append(("exposure", ", ".join(flags), ", ".join(flags)))
    max_closed = rule.get("max_eyes_closed")
    closed = img.get("eyes_closed_count") or 0
    if max_closed is not None and closed > max_closed:
        if not (rule.get("allow_intentional", False) and img.get("intentional_eyes_closed")):
            out.append(("eyes", "eyes closed",
                        f"eyes closed ({closed} of {img.get('face_count') or 0} faces)"))
    return out


def _filter_reason(img, rule):
    """Return a rejection reason (first failed check), or None if the image passes."""
    fails = _filter_failures(img, rule)
    return f"Rejected: {fails[0][2]}" if fails else None


def _all_failures(img, rules):
    """{kind: short name} across every filter rule, first occurrence wins."""
    seen = {}
    for rule in rules:
        for kind, short, _ in _filter_failures(img, rule):
            seen.setdefault(kind, short)
    return seen


def _fallback_key(img, fails):
    """Fewest failures, exposure-only before blur or eyes, then score, sharpness, path."""
    return (len(fails), set(fails) != {"exposure"}, -_score(img), -_sharp(img), img["path"])


def _apply_filters(pool, rules, reasons):
    for rule in rules:
        kept = []
        for img in pool:
            why = _filter_reason(img, rule)
            if why:
                reasons[img["path"]] = why
            else:
                kept.append(img)
        pool = kept
    return pool


def _dedupe(pool, keep, reasons):
    bursts = {}
    for img in pool:
        bursts.setdefault(img.get("burst_id") or img["path"], []).append(img)
    kept = []
    for bid, frames in bursts.items():
        frames.sort(key=_rank_key(_score))
        kept.extend(frames[:keep])
        for img in frames[keep:]:
            reasons[img["path"]] = f"Rejected: weaker frame of burst {bid}"
    return kept


def _group_label(images, by):
    labels = {}
    for img in images:
        g = img.get(by)
        if g is not None and g not in labels:
            labels[g] = img.get("group_label") or g
    return labels


def _cause(reason):
    """Short cause for a frame that coverage could not use, from its reason."""
    if reason is None:
        return "cap reached"  # passed every filter but the moment hit its cap
    text = reason.removeprefix("Rejected: ")
    for cause in ("blurry", "eyes closed", "overexposed", "underexposed"):
        if text.startswith(cause):
            return cause
    if text.startswith("weaker frame of burst"):
        return "burst duplicate"
    if text == "user override":
        return "rejected by user"
    return text


def _unmet_reason(images, by, g, picked, reasons):
    """'all overexposed', or a count mix like '3 overexposed, 1 eyes closed'."""
    causes = {}
    for img in images:
        if img.get(by) == g and img["path"] not in picked:
            c = _cause(reasons.get(img["path"]))
            causes[c] = causes.get(c, 0) + 1
    if not causes:
        return "not enough frames"
    if len(causes) == 1:
        return f"all {next(iter(causes))}"
    ranked = sorted(causes.items(), key=lambda kv: (-kv[1], kv[0]))
    return ", ".join(f"{n} {c}" for c, n in ranked)


def run_plan(images, plan):
    images = sorted(images, key=lambda i: i["path"])  # new list; rows are only read
    target = int(plan.get("target") or 0)
    reasons, picks = {}, []

    cap_rules = _rules(plan, "cap")
    cov_rules = _rules(plan, "coverage")
    by = (cov_rules or cap_rules or [{}])[0].get("by", "group_id")
    max_per = min((r.get("max_per_group", 10 ** 9) for r in cap_rules), default=None)
    labels = _group_label(images, by)
    counts = {}

    def pick(img, reason):
        picks.append(img["path"])
        reasons[img["path"]] = reason
        g = img.get(by)
        counts[g] = counts.get(g, 0) + 1

    def capped(img):
        return max_per is not None and counts.get(img.get(by), 0) >= max_per

    # 1. Overrides
    pool = []
    for img in images:
        if img.get("overridden") and img.get("final_rating") == 5:
            pick(img, "Kept: user override")
        elif img.get("overridden") and img.get("final_rating") == 1:
            reasons[img["path"]] = "Rejected: user override"
        else:
            pool.append(img)

    # 2. Filter, 3. dedupe bursts. Remember filter failures for the coverage fallback.
    filter_rules, unfiltered = _rules(plan, "filter"), pool
    pool = _apply_filters(pool, filter_rules, reasons)
    passed = {i["path"] for i in pool}
    failed = {i["path"]: _all_failures(i, filter_rules) for i in unfiltered
              if i["path"] not in passed}
    for rule in _rules(plan, "dedupe_bursts"):
        pool = _dedupe(pool, int(rule.get("keep", 1)), reasons)

    # Prefer weight applies to fill order
    prefer = _rules(plan, "prefer")

    def weighted(img):
        s = _score(img)
        tags = set(img.get("scene_tags") or [])
        for r in prefer:
            if tags & set(r.get("tags") or []):
                s *= float(r.get("weight", 1.0))
        return s

    # 4. Coverage (moments smaller than min_frames are exempt; fill may still pick them)
    sizes = {}
    for img in images:
        sizes[img.get(by)] = sizes.get(img.get(by), 0) + 1
    report, all_unmet, unmet_reasons = [], set(), {}
    for rule in cov_rules:
        need = int(rule.get("min_per_group", 1))
        min_frames = int(rule.get("min_frames", config.COVERAGE_MIN_FRAMES))
        groups = sorted(g for g in labels if sizes.get(g, 0) >= min_frames)
        exempt = len(labels) - len(groups)
        rule_unmet, rule_fallback = [], []
        for g in groups:
            cands = sorted((i for i in pool if i.get(by) == g and i["path"] not in reasons),
                           key=_rank_key(_score))
            for img in cands:
                if counts.get(g, 0) >= need or capped(img):
                    break
                pick(img, f"Kept: coverage pick for {labels[g]}")
            members = [i for i in images if i.get(by) == g]
            # Fallback: no frame in the moment passed the filters, so take the
            # least-bad one rather than leave the moment uncovered.
            if (counts.get(g, 0) < need and rule.get("fallback", True)
                    and not any(i["path"] in passed for i in members)):
                fb = sorted((i for i in members if i["path"] in failed),
                            key=lambda i: _fallback_key(i, failed[i["path"]]))
                if fb and not capped(fb[0]):
                    why = ", ".join(failed[fb[0]["path"]].values())
                    pick(fb[0], f"Kept: coverage fallback, best available ({why})")
                    rule_fallback.append(g)
            if counts.get(g, 0) < need:
                rule_unmet.append(g)
        rule_unmet = sorted(set(rule_unmet))
        all_unmet.update(rule_unmet)
        for g in rule_unmet:
            unmet_reasons[g] = _unmet_reason(images, by, g, set(picks), reasons)
        detail = (f"All {len(groups)} moments have at least {need} pick(s)"
                  if not rule_unmet else
                  "Unmet: " + ", ".join(f"{g} ({labels[g]}: {unmet_reasons[g]})"
                                        for g in rule_unmet))
        if rule_fallback:
            detail += f"; fallback pick for {', '.join(rule_fallback)}"
        if exempt:
            detail += f" ({exempt} moment(s) under {min_frames} frames exempt)"
        report.append({"type": "coverage", "met": not rule_unmet, "detail": detail})
    unmet = sorted(all_unmet)

    # 5. Fill to target by weighted score, respecting cap
    cap_hit = set()
    for img in sorted((i for i in pool if i["path"] not in reasons), key=_rank_key(weighted)):
        if len(picks) >= target:
            reasons[img["path"]] = f"Rejected: below target cutoff (score {_score(img):g})"
        elif capped(img):
            g = img.get(by)
            cap_hit.add(g)
            reasons[img["path"]] = f"Rejected: cap of {max_per} reached for {labels.get(g, g)}"
        else:
            g = img.get(by)
            pick(img, f"Kept: fill by score ({weighted(img):g}) for {labels.get(g, g)}")

    if cap_rules:
        detail = (f"Max {max_per} per moment; cap reached in " + ", ".join(sorted(cap_hit))
                  if cap_hit else f"Max {max_per} per moment; no moment over cap")
        over = [g for g, c in counts.items() if c > max_per]
        report.append({"type": "cap", "met": not over, "detail": detail +
                       (f"; overrides exceed cap in {', '.join(sorted(over))}" if over else "")})
    n = len(picks)
    detail = f"{n} of {target} picks"
    if n > target:
        # Coverage and overrides are never dropped to hit the target.
        detail += f": overrides and coverage need {n}"
    elif n < target:
        detail += (f": cap reached in {len(cap_hit)} of {len(labels)} moments" if cap_hit
                   else ": ran out of eligible frames")
    report.append({"type": "target", "met": n == target, "detail": detail})

    picked = set(picks)
    decisions = {}
    for img in images:
        p = img["path"]
        if p in picked:
            decisions[p] = {"rating": 5, "label": config.label_for(img.get("scene_tags")),
                            "reason": reasons[p]}
        else:
            decisions[p] = {"rating": 1, "label": None,
                            "reason": reasons.get(p, "Rejected: not selected")}
    return {"picks": picks, "decisions": decisions, "report": report, "unmet_groups": unmet,
            "unmet_reasons": unmet_reasons}


def top_n(images, n):
    """Baseline score-and-cut: default filter, best frame per burst, top n by claude_score."""
    pool = _apply_filters(sorted(images, key=lambda i: i["path"]), [DEFAULT_FILTER], {})
    pool = _dedupe(pool, 1, {})
    pool.sort(key=_rank_key(_score))
    return [i["path"] for i in pool[:n]]
