// Cull review grid. UI lane. Vanilla JS, no framework, no build step.
// Load scores, run DEFAULT_PLAN, render moments. Toggle Cull / Top-N baseline.

// First plan from fixtures/preset_plans.json ("cull this shoot to about 30").
const DEFAULT_PLAN = {
  target: 26,
  rules: [
    { type: "filter", max_eyes_closed: 0, allow_intentional: true, min_sharpness: 150, drop_exposure_flags: true },
    { type: "dedupe_bursts", keep: 1 },
    { type: "coverage", by: "group_id", min_per_group: 1 },
    { type: "cap", by: "group_id", max_per_group: 6 },
    { type: "prefer", tags: ["candid"], weight: 1.5 }
  ]
};

// All state in one object.
const state = {
  plan: DEFAULT_PLAN,
  images: [],        // rows from /api/scores, in file order
  groups: [],        // [{group_id, group_label, count}]
  picks: new Set(),  // picked paths from the latest run
  decisions: {},     // path -> {rating, label, reason}
  overrides: {},     // path -> 5 | 1 (local cycle tracking)
  report: [],        // [{type, met, detail}] from the latest run
  unmetReasons: {},  // group_id -> why coverage found no usable frame
  explanation: "",   // text from the latest /api/plan
  view: "cull",      // "cull" | "topn"
  baseline: new Set(), // top-N paths from /api/baseline at the current target
  cols: 6,           // grid columns from the Size slider (2..10)
  undoStack: [],     // override history, each {path, before, after}
  redoStack: [],     // entries undone, ready to reapply
  busy: false,       // lock: one override round-trip at a time
  focusPath: null,   // path of the keyboard-focused tile (survives render)
  loupeOpen: false,  // full-res loupe overlay visible
  // View filter: narrows which tiles render. Never touches the status bar,
  // orderedPaths honors it, so navigation and the loupe only visit shown tiles.
  filter: { status: "all", issues: new Set(), tags: new Set() }
};

// --- View filter ---------------------------------------------------------
function blurThreshold() {
  return findRule("filter")?.min_sharpness ?? 170;
}

function hasIssue(img, issue) {
  if (issue === "blink") return (img.eyes_closed_count || 0) > 0;
  if (issue === "blur") return img.sharpness !== null && img.sharpness !== undefined
    && img.sharpness < blurThreshold();
  if (issue === "exposure") return (img.exposure_flags || []).length > 0;
  return false;
}

function filterIsClear() {
  const f = state.filter;
  return f.status === "all" && f.issues.size === 0 && f.tags.size === 0;
}

function matchesFilter(img) {
  const f = state.filter;
  if (f.status === "picks" && !shownPicks().has(img.path)) return false;
  if (f.status === "notpicked" && shownPicks().has(img.path)) return false;
  if (f.issues.size && ![...f.issues].some((i) => hasIssue(img, i))) return false;
  if (f.tags.size) {
    const tags = img.scene_tags || [];
    if (![...f.tags].some((t) => tags.includes(t))) return false;
  }
  return true;
}

// Build tag chips (one per tag present, by count desc) and wire every chip.
// Chip changes only re-render the grid and status bar; no server calls.
function initFilterChips() {
  const tagCounts = {};
  for (const img of state.images) {
    for (const t of img.scene_tags || []) tagCounts[t] = (tagCounts[t] || 0) + 1;
  }
  const tagBox = document.getElementById("filter-tags");
  tagBox.innerHTML = "";
  for (const [tag] of Object.entries(tagCounts).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chip";
    btn.dataset.tag = tag;
    btn.setAttribute("aria-pressed", "false");
    btn.innerHTML = tag + ' <span class="chip-n" data-tagcount="' + tag + '">0</span>';
    tagBox.appendChild(btn);
  }

  const afterChange = (btn) => {
    render();
    renderStatusBar();
    btn.blur();  // hand keyboard focus back to the grid for arrows and P/X/U
  };

  document.getElementById("filter-status").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-status]");
    if (!btn) return;
    state.filter.status = btn.dataset.status;
    afterChange(btn);
  });
  const toggleSet = (set, key, btn) => {
    if (set.has(key)) set.delete(key);
    else set.add(key);
    afterChange(btn);
  };
  document.getElementById("filter-issues").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-issue]");
    if (btn) toggleSet(state.filter.issues, btn.dataset.issue, btn);
  });
  tagBox.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-tag]");
    if (btn) toggleSet(state.filter.tags, btn.dataset.tag, btn);
  });
  document.getElementById("filter-clear").addEventListener("click", (e) => {
    state.filter.status = "all";
    state.filter.issues.clear();
    state.filter.tags.clear();
    afterChange(e.target);
  });
}

// Reflect filter state into the chips and the "Showing n of total" line.
// Issue/tag counts are over the FULL set, independent of the active filter.
function updateFilterUI(shownTotal) {
  const f = state.filter;
  for (const btn of document.querySelectorAll("#filter-status button[data-status]")) {
    const on = btn.dataset.status === f.status;
    btn.classList.toggle("on", on);
    btn.setAttribute("aria-pressed", String(on));
  }
  for (const btn of document.querySelectorAll("#filter-issues button[data-issue]")) {
    const on = f.issues.has(btn.dataset.issue);
    btn.classList.toggle("on", on);
    btn.setAttribute("aria-pressed", String(on));
  }
  for (const btn of document.querySelectorAll("#filter-tags button[data-tag]")) {
    const on = f.tags.has(btn.dataset.tag);
    btn.classList.toggle("on", on);
    btn.setAttribute("aria-pressed", String(on));
  }
  // Live counts over the full image set.
  for (const issue of ["blink", "blur", "exposure"]) {
    const el = document.querySelector('[data-count="' + issue + '"]');
    if (el) el.textContent = state.images.filter((i) => hasIssue(i, issue)).length;
  }
  for (const el of document.querySelectorAll("[data-tagcount]")) {
    const tag = el.dataset.tagcount;
    el.textContent = state.images.filter((i) => (i.scene_tags || []).includes(tag)).length;
  }
  const line = document.getElementById("filter-count");
  if (line) line.textContent = "Showing " + shownTotal + " of " + state.images.length + " frames";
}

// Find a rule of a given type in the current plan (or null).
function findRule(type) {
  return (state.plan.rules || []).find((r) => r.type === type) || null;
}

function basename(preview) {
  if (!preview) return "";
  const parts = preview.split("/");
  return parts[parts.length - 1];
}

async function getJSON(url, body) {
  const opts = body === undefined
    ? {}
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const res = await fetch(url, opts);
  if (!res.ok) throw new Error(url + " -> " + res.status);
  return res.json();
}

// Apply a result object (from /api/run or /api/plan) to state.
function applyResult(result) {
  result = result || {};
  state.picks = new Set(result.picks || []);
  state.decisions = result.decisions || {};
  state.report = result.report || [];
  state.unmetReasons = result.unmet_reasons || {};
}

// renderReport (views.js) marks every unmet rule red with a cross. An unmet
// coverage rule means some moments had no usable frame, which is information,
// not an error: restyle that row neutrally and list each moment's reason.
function relabelCoverageRows() {
  const rows = document.getElementById("report").children;
  state.report.forEach((entry, i) => {
    const li = rows[i];
    const ids = Object.keys(state.unmetReasons).sort();
    if (!li || entry.type !== "coverage" || entry.met || ids.length === 0) return;
    li.className = "report-row";  // drops "unmet", so no red
    const mark = li.querySelector(".mark");
    mark.textContent = "\u2022";
    mark.style.color = "var(--muted)";
    li.querySelector(".report-text").textContent = "No usable frame: " +
      ids.map((g) => g + " (" + state.unmetReasons[g] + ")").join(", ");
  });
}

// POST /api/run with the current plan (no LLM call). Used on load and Re-plan.
async function runPlan() {
  const data = await getJSON("/api/run", { plan: state.plan });
  applyResult(data.result);
  document.getElementById("export-btn").disabled = false;
  if (state.view === "topn") await loadBaseline();
}

function setStatus(text) {
  document.getElementById("status").textContent = text;
}

// Cycle: no override -> force pick (5) -> force reject (1) -> clear (null).
function nextRating(current) {
  if (current === 5) return 1;
  if (current === 1) return null;
  return 5;
}

// Undo/redo for tile overrides.
// Every override (click, undo, or redo) runs through setOverride, which POSTs
// the new rating and re-runs the plan. cycleOverride records each change as
// {path, before, after} on undoStack and clears redoStack, so a fresh click
// drops any forward history. undo moves an entry to redoStack and restores
// `before`; redo moves it back and reapplies `after`. state.busy is a lock:
// each handler returns early while a round-trip is in flight, so overlapping
// clicks or key presses cannot interleave POSTs or corrupt the stacks. History
// lives only in memory, so a reload empties it while the server keeps the
// overrides themselves.
const UNDO_LIMIT = 200;

// POST the override and refresh. Shared by cycleOverride, undo, and redo.
async function setOverride(path, rating) {
  await getJSON("/api/override", { path, rating });
  if (rating === null) delete state.overrides[path];
  else state.overrides[path] = rating;
  await runPlan();
  render();
  showSummary();
  if (state.loupeOpen) updateLoupe();
}

function overrideLabel(rating) {
  if (rating === 5) return "pick";
  if (rating === 1) return "reject";
  return "clear";
}

// Path at `index` in `order`, clamped to the last entry, or null if empty.
function pathAtIndex(order, index) {
  if (order.length === 0) return null;
  return order[Math.min(index, order.length - 1)];
}

// Single override entry point for clicks and P/X/U keys. Records history.
async function applyOverride(path, after) {
  if (state.busy || !path) return;
  const before = state.overrides[path] ?? null;
  if (before === after) return;  // nothing to change, nothing to record
  // Remember where the focus sat in the filtered list; the Picks/Not-picked
  // filter can drop this frame once its pick state flips.
  const prevOrder = orderedPaths();
  const prevIndex = prevOrder.indexOf(state.focusPath);
  state.busy = true;
  try {
    await setOverride(path, after);  // runs render(); focus class is reapplied below
    state.undoStack.push({ path, before, after });
    if (state.undoStack.length > UNDO_LIMIT) state.undoStack.shift();
    state.redoStack = [];
    // If the focused frame no longer matches, land on the frame now at the
    // same index (or the last one), so the ring follows the cull.
    if (state.focusPath && !matchesFilter(imageFor(state.focusPath))) {
      const next = prevIndex === -1 ? firstVisiblePath()
        : pathAtIndex(orderedPaths(), prevIndex);
      state.focusPath = next;
      if (state.loupeOpen) updateLoupe();
      const el = next && tileEl(next);
      if (el) {
        el.classList.add("focused");
        el.scrollIntoView({ block: "nearest" });
      }
    }
  } catch (err) {
    setStatus("error: " + err.message);
  } finally {
    state.busy = false;
  }
}

function imageFor(path) {
  return state.images.find((i) => i.path === path) || {};
}

function cycleOverride(path) {
  return applyOverride(path, nextRating(state.overrides[path] ?? null));
}

// --- Keyboard focus and navigation ---------------------------------------
// focusPath is the single source of truth and is redrawn by render(). Arrow
// keys move it; P/X/U act on it. Below the top bars (76px) is the visible area.
const STICKY_OFFSET = 76;

// Paths in display order: group order, then image order within each group.
// Mirrors how render() lays out tiles, so Left/Right follow the screen.
function orderedPaths() {
  const out = [];
  for (const g of state.groups) {
    for (const img of state.images) {
      if (img.group_id === g.group_id && matchesFilter(img)) out.push(img.path);
    }
  }
  return out;
}

function tileEl(path) {
  return document.querySelector('.tile[data-path="' + (window.CSS && CSS.escape ? CSS.escape(path) : path) + '"]');
}

// Move the white ring without a full render: just toggle the class and scroll.
function setFocus(path) {
  if (!path || path === state.focusPath) return;
  const prev = state.focusPath && tileEl(state.focusPath);
  if (prev) prev.classList.remove("focused");
  state.focusPath = path;
  const next = tileEl(path);
  if (next) {
    next.classList.add("focused");
    next.scrollIntoView({ block: "nearest" });
  }
}

// First tile whose bottom edge is below the sticky bars (first one in view).
function firstVisiblePath() {
  for (const el of document.querySelectorAll(".tile[data-path]")) {
    if (el.getBoundingClientRect().bottom > STICKY_OFFSET) return el.dataset.path;
  }
  const tiles = document.querySelectorAll(".tile[data-path]");
  return tiles.length ? tiles[0].dataset.path : null;
}

function moveFocus(dir) {
  // If the focused tile was filtered out of the DOM, start fresh from the top.
  if (!state.focusPath || !tileEl(state.focusPath)) {
    setFocus(firstVisiblePath());
    return;
  }
  if (dir === "left" || dir === "right") {
    const order = orderedPaths();
    const i = order.indexOf(state.focusPath);
    if (i === -1) return;
    const j = dir === "left" ? i - 1 : i + 1;
    if (j >= 0 && j < order.length) setFocus(order[j]);
    return;
  }

  // Up/Down by geometry: nearest row in that direction, then closest column.
  const cur = tileEl(state.focusPath);
  if (!cur) return;
  const cr = cur.getBoundingClientRect();
  const cx = cr.left + cr.width / 2;
  const cy = cr.top + cr.height / 2;

  let best = null;
  for (const el of document.querySelectorAll(".tile[data-path]")) {
    if (el === cur) continue;
    const r = el.getBoundingClientRect();
    const ey = r.top + r.height / 2;
    const dy = ey - cy;
    if (dir === "up" && dy >= 0) continue;
    if (dir === "down" && dy <= 0) continue;
    const ex = r.left + r.width / 2;
    const cand = { path: el.dataset.path, vdist: Math.abs(dy), hdist: Math.abs(ex - cx) };
    if (!best || cand.vdist < best.vdist - 1 ||
        (Math.abs(cand.vdist - best.vdist) <= 1 && cand.hdist < best.hdist)) {
      best = cand;
    }
  }
  if (best) setFocus(best.path);
}

// --- Loupe (full-resolution single-frame view) ---------------------------
function openLoupe() {
  if (!state.focusPath) setFocus(firstVisiblePath());
  if (!state.focusPath) return;
  state.loupeOpen = true;
  document.getElementById("loupe").hidden = false;
  updateLoupe();
}

function updateLoupe() {
  const path = state.focusPath;
  if (!path) return;
  const name = previewName(path);
  document.getElementById("loupe-img").src = "/preview/" + encodeURIComponent(name);
  document.getElementById("loupe-img").alt = name;

  const img = state.images.find((i) => i.path === path) || {};
  const picks = shownPicks();
  const ov = state.overrides[path];
  const ovText = ov === 5 ? "PICK" : ov === 1 ? "REJECT" : "none";
  const dec = state.decisions[path];
  const parts = [
    name,
    (img.group_id || "") + (img.group_label ? " " + img.group_label : ""),
    picks.has(path) ? "PICKED" : "not picked",
    "override: " + ovText,
    (dec && dec.reason) || "",
  ].filter(Boolean);
  document.getElementById("loupe-info").textContent = parts.join(" \u00b7 ");
}

function closeLoupe() {
  state.loupeOpen = false;
  document.getElementById("loupe").hidden = true;
  // Loupe stepping moves focusPath without touching tiles; resync the ring.
  for (const t of document.querySelectorAll(".tile.focused")) t.classList.remove("focused");
  const el = state.focusPath && tileEl(state.focusPath);
  if (el) el.classList.add("focused");
  if (el) el.scrollIntoView({ block: "nearest" });
}

function toggleLoupe() {
  if (state.loupeOpen) closeLoupe();
  else openLoupe();
}

// In the loupe, Left/Right step to the previous/next frame in display order.
function loupeStep(dir) {
  const order = orderedPaths();
  const i = order.indexOf(state.focusPath);
  if (i === -1) return;
  const j = dir === "left" ? i - 1 : i + 1;
  if (j < 0 || j >= order.length) return;
  state.focusPath = order[j];
  updateLoupe();
}

async function undo() {
  if (state.busy || state.undoStack.length === 0) return;
  const entry = state.undoStack.pop();
  state.busy = true;
  try {
    await setOverride(entry.path, entry.before);
    state.redoStack.push(entry);
    setStatus("Undo: " + overrideLabel(entry.before) + " " + basename(entry.path));
  } catch (err) {
    state.undoStack.push(entry);  // leave the stacks unchanged on failure
    setStatus("error: " + err.message);
  } finally {
    state.busy = false;
  }
}

async function redo() {
  if (state.busy || state.redoStack.length === 0) return;
  const entry = state.redoStack.pop();
  state.busy = true;
  try {
    await setOverride(entry.path, entry.after);
    state.undoStack.push(entry);
    setStatus("Redo: " + overrideLabel(entry.after) + " " + basename(entry.path));
  } catch (err) {
    state.redoStack.push(entry);  // leave the stacks unchanged on failure
    setStatus("error: " + err.message);
  } finally {
    state.busy = false;
  }
}

// Keyboard culling. Ctrl/Cmd+Z undo, Ctrl/Cmd+Shift+Z or Ctrl+Y redo; arrows
// move focus (step frames in the loupe); P/X/U pick/reject/clear the focused
// tile; Space toggles the loupe; Esc closes it. Skipped entirely when a text
// field is focused so native text editing and its undo still work.
function onKeydown(e) {
  const el = document.activeElement;
  const tag = el ? el.tagName : "";
  if (tag === "TEXTAREA" || tag === "INPUT" || (el && el.isContentEditable)) return;
  const key = (e.key || "").toLowerCase();

  // Ctrl/Cmd+Z and redo come first, before the plain-key culling handlers.
  if (e.ctrlKey || e.metaKey) {
    if (key === "z" && !e.shiftKey) {
      e.preventDefault();
      undo();
    } else if ((key === "z" && e.shiftKey) || key === "y") {
      e.preventDefault();
      redo();
    }
    return;
  }
  // Leave Alt combos (and any remaining modifier combos) to the browser.
  if (e.altKey) return;

  // Plain-key culling and navigation.
  switch (e.key) {
    case "ArrowLeft":
      e.preventDefault();
      state.loupeOpen ? loupeStep("left") : moveFocus("left");
      break;
    case "ArrowRight":
      e.preventDefault();
      state.loupeOpen ? loupeStep("right") : moveFocus("right");
      break;
    case "ArrowUp":
      e.preventDefault();
      if (!state.loupeOpen) moveFocus("up");
      break;
    case "ArrowDown":
      e.preventDefault();
      if (!state.loupeOpen) moveFocus("down");
      break;
    case " ":
      e.preventDefault();
      toggleLoupe();
      break;
    case "Escape":
      if (state.loupeOpen) {
        e.preventDefault();
        closeLoupe();
      }
      break;
    default:
      if (key === "p") {
        e.preventDefault();
        if (state.focusPath) applyOverride(state.focusPath, 5);
      } else if (key === "x") {
        e.preventDefault();
        if (state.focusPath) applyOverride(state.focusPath, 1);
      } else if (key === "u") {
        e.preventDefault();
        if (state.focusPath) applyOverride(state.focusPath, null);
      }
  }
}

// /thumb is a 400px copy; at 3 columns or fewer tiles outgrow it, so use the
// full embedded preview. Denser views keep the small thumb for fast scrolling.
const FULL_PREVIEW_MAX_COLS = 3;

function useFullPreview() {
  return state.cols <= FULL_PREVIEW_MAX_COLS;
}

function imageSrc(name) {
  return (useFullPreview() ? "/preview/" : "/thumb/") + encodeURIComponent(name);
}

// Preview filename for a path, the same rule tileFor uses for its <img>.
function previewName(path) {
  const img = state.images.find((i) => i.path === path);
  return (img && (basename(img.preview) || basename(img.path))) || basename(path);
}

function tileFor(img) {
  const tile = document.createElement("div");
  tile.className = "tile";
  const path = img.path;
  tile.dataset.path = path;
  if (shownPicks().has(path)) tile.classList.add("picked");
  if (path === state.focusPath) tile.classList.add("focused");

  const ov = state.overrides[path];
  if (ov === 5) tile.classList.add("ov-pick");
  else if (ov === 1) tile.classList.add("ov-reject");

  const name = basename(img.preview) || basename(path);

  const img_el = document.createElement("img");
  img_el.alt = name;
  img_el.loading = "lazy";
  img_el.dataset.name = name;
  img_el.src = imageSrc(name);
  // On 404 (fake data or missing preview) fall back to a grey filename tile.
  img_el.addEventListener("error", () => {
    img_el.remove();
    const grey = document.createElement("div");
    grey.className = "grey";
    grey.textContent = name;
    tile.prepend(grey);
  });
  tile.appendChild(img_el);

  if (ov) {
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = ov === 5 ? "PICK" : "REJECT";
    tile.appendChild(badge);
  }

  const overlay = document.createElement("div");
  overlay.className = "overlay";
  const dec = state.decisions[path];
  if (state.view === "topn") {
    overlay.textContent = state.baseline.has(path) ? "Kept: top-N baseline" : "Rejected: below top-N cut";
  } else {
    overlay.textContent = dec ? dec.reason : "";
  }
  tile.appendChild(overlay);

  tile.addEventListener("click", () => {
    state.focusPath = path;  // click focuses before cycling the override
    cycleOverride(path);
  });
  return tile;
}

// Push the current plan's target / cap / allow_intentional into the inputs.
function syncControlsFromPlan() {
  const cap = findRule("cap");
  const filter = findRule("filter");
  document.getElementById("plan-target").value = state.plan.target ?? "";
  document.getElementById("plan-cap").value = cap ? (cap.max_per_group ?? "") : "";
  document.getElementById("plan-allow-intentional").checked =
    filter ? !!filter.allow_intentional : false;
}

// Edit the plan object in place from the inputs, then run it (no LLM).
async function replan() {
  const targetEl = document.getElementById("plan-target");
  const capEl = document.getElementById("plan-cap");
  const allowEl = document.getElementById("plan-allow-intentional");

  if (targetEl.value !== "") state.plan.target = Number(targetEl.value);
  const cap = findRule("cap");
  if (cap && capEl.value !== "") cap.max_per_group = Number(capEl.value);
  const filter = findRule("filter");
  if (filter) filter.allow_intentional = allowEl.checked;

  setSpinner(true);
  try {
    await runPlan();
    render();
    showSummary();
  } catch (err) {
    setStatus("error: " + err.message);
  } finally {
    setSpinner(false);
  }
}

// Turn the instruction into a plan via /api/plan (preset while agent is absent).
async function runInstruction() {
  const instruction = document.getElementById("instruction").value;
  setSpinner(true);
  try {
    const data = await getJSON("/api/plan", { instruction });
    if (data.plan) state.plan = data.plan;
    state.explanation = data.explanation || "";
    applyResult(data.result);
    syncControlsFromPlan();
    render();
    showSummary();
  } catch (err) {
    setStatus("error: " + err.message);
  } finally {
    setSpinner(false);
  }
}

function render() {
  renderReport();
  relabelCoverageRows();
  const grid = document.getElementById("grid");
  // Keep the scroll position across rebuilds (view toggle, re-plan, override).
  const scrollY = window.scrollY;
  const gridTop = grid.scrollTop;
  grid.innerHTML = "";

  const active = !filterIsClear();
  let shownTotal = 0;
  for (const g of state.groups) {
    const rowImages = state.images.filter((i) => i.group_id === g.group_id);
    const shownImages = active ? rowImages.filter(matchesFilter) : rowImages;
    shownTotal += shownImages.length;
    // Hide a moment that has no matching frame, but never when the filter is
    // fully cleared (then an empty moment still shows, as before).
    if (active && shownImages.length === 0) continue;

    const picks = shownPicks();
    const picked = rowImages.filter((i) => picks.has(i.path)).length;  // all picks, not just shown

    const row = document.createElement("section");
    row.className = "moment";

    const header = document.createElement("div");
    header.className = "moment-header";
    if (picked === 0) header.classList.add("zero");
    header.innerHTML =
      '<span class="label"></span><span class="count"></span>';
    // "G001 · group, 11:39-11:49AM · 98 frames · 3 picks"; with a filter active
    // the frame count becomes "<shown> of <total> frames".
    const frames = active
      ? shownImages.length + " of " + rowImages.length + " frames"
      : (rowImages.length === 1 ? "1 frame" : rowImages.length + " frames");
    header.querySelector(".label").textContent =
      [g.group_id, g.group_label, frames].filter(Boolean).join(" \u00b7 ");
    header.querySelector(".count").textContent =
      "\u00b7 " + (picked === 1 ? "1 pick" : picked + " picks");
    row.appendChild(header);

    const strip = document.createElement("div");
    strip.className = "strip";
    for (const img of shownImages) strip.appendChild(tileFor(img));
    row.appendChild(strip);

    grid.appendChild(row);
  }
  grid.scrollTop = gridTop;
  window.scrollTo(0, scrollY);
  updateFilterUI(shownTotal);
}

// Size slider: sets --cols on #grid and remembers the last column count.
// Slider runs 2..10 but is inverted, so dragging right gives fewer, bigger tiles.
const GRID_COLS_KEY = "cull.gridCols";
const COLS_MIN = 2;
const COLS_MAX = 10;

function initTileSlider() {
  const slider = document.getElementById("tile-size");
  const grid = document.getElementById("grid");
  let saved = null;
  try {
    saved = localStorage.getItem(GRID_COLS_KEY);
  } catch (err) {
    // Storage blocked (private mode, file://); keep the default.
  }
  const n = Number(saved);
  if (saved !== null && Number.isInteger(n) && n >= COLS_MIN && n <= COLS_MAX) {
    state.cols = n;
  }
  slider.value = String(COLS_MIN + COLS_MAX - state.cols);

  const apply = () => {
    const wasLarge = useFullPreview();
    state.cols = COLS_MIN + COLS_MAX - Number(slider.value);
    grid.style.setProperty("--cols", String(state.cols));
    slider.setAttribute("aria-valuetext", state.cols + " columns");
    slider.title = state.cols + " columns";
    // Swap image sources only when crossing the full-preview threshold.
    if (useFullPreview() !== wasLarge) {
      for (const el of grid.querySelectorAll(".tile img[data-name]")) {
        el.src = imageSrc(el.dataset.name);
      }
    }
  };
  apply();
  slider.addEventListener("input", apply);
  slider.addEventListener("change", () => {
    try {
      localStorage.setItem(GRID_COLS_KEY, String(state.cols));
    } catch (err) {
      // Not saved; the slider still works for this session.
    }
  });
}

async function init() {
  initTileSlider();
  try {
    const scores = await getJSON("/api/scores");
    state.images = scores.images || [];
    state.groups = scores.groups || [];
    // Seed local override tracking from server state.
    for (const img of state.images) {
      if (img.overridden && (img.final_rating === 5 || img.final_rating === 1)) {
        state.overrides[img.path] = img.final_rating;
      }
    }
    syncControlsFromPlan();
    initFilterChips();
    await runPlan();
    render();
    showSummary();
  } catch (err) {
    setStatus("error: " + err.message);
  }

  document.getElementById("run-btn").addEventListener("click", runInstruction);
  document.getElementById("replan-btn").addEventListener("click", replan);
  document.getElementById("export-btn").addEventListener("click", exportSidecars);
  document.getElementById("view-cull").addEventListener("click", () => setView("cull"));
  document.getElementById("view-topn").addEventListener("click", () => setView("topn"));
  document.addEventListener("keydown", onKeydown);

  // Clicking the loupe backdrop (not the image) closes it.
  document.getElementById("loupe").addEventListener("click", (e) => {
    if (e.target.id !== "loupe-img") closeLoupe();
  });
}

init();
