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
  busy: false        // lock: one override round-trip at a time
};

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
}

function overrideLabel(rating) {
  if (rating === 5) return "pick";
  if (rating === 1) return "reject";
  return "clear";
}

async function cycleOverride(path) {
  if (state.busy) return;
  const before = state.overrides[path] ?? null;
  const after = nextRating(before);
  state.busy = true;
  try {
    await setOverride(path, after);
    state.undoStack.push({ path, before, after });
    if (state.undoStack.length > UNDO_LIMIT) state.undoStack.shift();
    state.redoStack = [];
  } catch (err) {
    setStatus("error: " + err.message);
  } finally {
    state.busy = false;
  }
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

// Ctrl/Cmd+Z undo, Ctrl/Cmd+Shift+Z or Ctrl+Y redo. Skip when a text field is
// focused so the browser's own text undo still works in the instruction box.
function onKeydown(e) {
  const el = document.activeElement;
  const tag = el ? el.tagName : "";
  if (tag === "TEXTAREA" || tag === "INPUT" || (el && el.isContentEditable)) return;
  if (!(e.ctrlKey || e.metaKey)) return;
  const key = (e.key || "").toLowerCase();
  if (key === "z" && !e.shiftKey) {
    e.preventDefault();
    undo();
  } else if ((key === "z" && e.shiftKey) || key === "y") {
    e.preventDefault();
    redo();
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

function tileFor(img) {
  const tile = document.createElement("div");
  tile.className = "tile";
  const path = img.path;
  if (shownPicks().has(path)) tile.classList.add("picked");

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

  tile.addEventListener("click", () => cycleOverride(path));
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

  for (const g of state.groups) {
    const rowImages = state.images.filter((i) => i.group_id === g.group_id);
    const picks = shownPicks();
    const picked = rowImages.filter((i) => picks.has(i.path)).length;

    const row = document.createElement("section");
    row.className = "moment";

    const header = document.createElement("div");
    header.className = "moment-header";
    if (picked === 0) header.classList.add("zero");
    header.innerHTML =
      '<span class="label"></span><span class="count"></span>';
    // "G001 · group, 11:39-11:49AM · 98 frames · 3 picks"; the pick count keeps
    // its own muted styling in the .count span.
    const frames = rowImages.length === 1 ? "1 frame" : rowImages.length + " frames";
    header.querySelector(".label").textContent =
      [g.group_id, g.group_label, frames].filter(Boolean).join(" \u00b7 ");
    header.querySelector(".count").textContent =
      "\u00b7 " + (picked === 1 ? "1 pick" : picked + " picks");
    row.appendChild(header);

    const strip = document.createElement("div");
    strip.className = "strip";
    for (const img of rowImages) strip.appendChild(tileFor(img));
    row.appendChild(strip);

    grid.appendChild(row);
  }
  grid.scrollTop = gridTop;
  window.scrollTo(0, scrollY);
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
}

init();
