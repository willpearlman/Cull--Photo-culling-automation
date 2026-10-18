// Cull review grid. UI lane, task 5. Vanilla JS, no framework, no build step.
// On load: GET /api/scores, then POST /api/run with DEFAULT_PLAN, render moments
// as rows. Click a tile to cycle override (5 -> 1 -> null) and re-run the plan.

// First plan from fixtures/preset_plans.json ("cull this shoot to about 30").
const DEFAULT_PLAN = {
  target: 30,
  rules: [
    { type: "filter", max_eyes_closed: 0, allow_intentional: true, min_sharpness: 150, drop_exposure_flags: true },
    { type: "dedupe_bursts", keep: 1 },
    { type: "coverage", by: "group_id", min_per_group: 1 },
    { type: "cap", by: "group_id", max_per_group: 3 },
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
  explanation: ""    // text from the latest /api/plan
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
}

// POST /api/run with the current plan (no LLM call). Used on load and Re-plan.
async function runPlan() {
  const data = await getJSON("/api/run", { plan: state.plan });
  applyResult(data.result);
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

async function cycleOverride(path) {
  const rating = nextRating(state.overrides[path] ?? null);
  await getJSON("/api/override", { path, rating });
  if (rating === null) delete state.overrides[path];
  else state.overrides[path] = rating;
  await runPlan();
  render();
}

function tileFor(img) {
  const tile = document.createElement("div");
  tile.className = "tile";
  const path = img.path;
  if (state.picks.has(path)) tile.classList.add("picked");

  const ov = state.overrides[path];
  if (ov === 5) tile.classList.add("ov-pick");
  else if (ov === 1) tile.classList.add("ov-reject");

  const name = basename(img.preview) || basename(path);

  const img_el = document.createElement("img");
  img_el.alt = name;
  img_el.loading = "lazy";
  img_el.src = "/thumb/" + encodeURIComponent(name);
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
  overlay.textContent = dec ? dec.reason : "";
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
    setStatus(state.groups.length + " moments, " + state.picks.size + " picks");
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
    setStatus(state.groups.length + " moments, " + state.picks.size + " picks");
  } catch (err) {
    setStatus("error: " + err.message);
  } finally {
    setSpinner(false);
  }
}

function setSpinner(on) {
  document.getElementById("spinner").hidden = !on;
  document.getElementById("run-btn").disabled = on;
  document.getElementById("replan-btn").disabled = on;
}

function renderReport() {
  const list = document.getElementById("report");
  list.innerHTML = "";
  for (const entry of state.report) {
    const li = document.createElement("li");
    li.className = "report-row " + (entry.met ? "met" : "unmet");
    const mark = document.createElement("span");
    mark.className = "mark";
    mark.textContent = entry.met ? "\u2713" : "\u2717";
    const text = document.createElement("span");
    text.className = "report-text";
    text.textContent = entry.detail || entry.type;
    li.appendChild(mark);
    li.appendChild(text);
    list.appendChild(li);
  }
  document.getElementById("explanation").textContent = state.explanation;
}

function render() {
  renderReport();
  const grid = document.getElementById("grid");
  grid.innerHTML = "";

  for (const g of state.groups) {
    const rowImages = state.images.filter((i) => i.group_id === g.group_id);
    const picked = rowImages.filter((i) => state.picks.has(i.path)).length;

    const row = document.createElement("section");
    row.className = "moment";

    const header = document.createElement("div");
    header.className = "moment-header";
    if (picked === 0) header.classList.add("zero");
    header.innerHTML =
      '<span class="label"></span><span class="count"></span>';
    header.querySelector(".label").textContent = g.group_label || g.group_id;
    header.querySelector(".count").textContent = picked + " picks";
    row.appendChild(header);

    const strip = document.createElement("div");
    strip.className = "strip";
    for (const img of rowImages) strip.appendChild(tileFor(img));
    row.appendChild(strip);

    grid.appendChild(row);
  }
}

async function init() {
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
    setStatus(state.groups.length + " moments, " + state.picks.size + " picks");
  } catch (err) {
    setStatus("error: " + err.message);
  }

  document.getElementById("run-btn").addEventListener("click", runInstruction);
  document.getElementById("replan-btn").addEventListener("click", replan);
}

init();
