// Left panel and top bar: Cull / Top-N toggle, rule report, spinner, Export.
// Loaded before app.js; uses its globals (state, getJSON, render, setStatus).

// Picks shown in the grid for the current view.
function shownPicks() {
  return state.view === "topn" ? state.baseline : state.picks;
}

// GET /api/baseline at the current target (score-and-cut, no LLM).
async function loadBaseline() {
  const n = Number(state.plan.target) || 0;
  const data = await getJSON("/api/baseline?n=" + encodeURIComponent(n));
  state.baseline = new Set(data.picks || []);
}

async function setView(view) {
  state.view = view;
  for (const [id, v] of [["view-cull", "cull"], ["view-topn", "topn"]]) {
    const btn = document.getElementById(id);
    btn.classList.toggle("active", v === view);
    btn.setAttribute("aria-pressed", String(v === view));
  }
  try {
    if (view === "topn") await loadBaseline();
    render();
    showSummary();
  } catch (err) {
    setStatus("error: " + err.message);
  }
}

// Export always sends the Cull result, whichever view is showing.
async function exportSidecars() {
  const btn = document.getElementById("export-btn");
  btn.disabled = true;
  try {
    const data = await getJSON("/api/export", { picks: [...state.picks], decisions: state.decisions });
    setStatus("Wrote " + (data.written ?? 0) + " sidecars");
  } catch (err) {
    setStatus("error: " + err.message);
  } finally {
    btn.disabled = false;
  }
}

function showSummary() {
  const picks = shownPicks();
  const zero = state.groups.filter((g) =>
    !state.images.some((i) => i.group_id === g.group_id && picks.has(i.path))).length;
  const name = state.view === "topn" ? "Top-N" : "Cull";
  setStatus(name + ": " + picks.size + " picks, " + zero + " of " + state.groups.length + " moments with 0 picks");
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
