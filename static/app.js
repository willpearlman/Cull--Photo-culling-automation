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
  overrides: {}      // path -> 5 | 1 (local cycle tracking)
};

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

async function runPlan() {
  const data = await getJSON("/api/run", { plan: state.plan });
  const result = data.result || {};
  state.picks = new Set(result.picks || []);
  state.decisions = result.decisions || {};
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

function render() {
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
    await runPlan();
    render();
    setStatus(state.groups.length + " moments, " + state.picks.size + " picks");
  } catch (err) {
    setStatus("error: " + err.message);
  }
}

init();
