// Asks /api/jobs every 2 seconds and draws the running jobs and the recent ones.
// Only textContent is used for job data, so text from a job can never become HTML.

const INTERVAL_MS = 2000;
const STATES = {
  running: ["●", "Running"],
  done: ["✓", "Done"],
  failed: ["✕", "Failed"],
  stopped: ["!", "Stopped"],
};

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function number(n) {
  return n === null || n === undefined ? "-" : Number(n).toLocaleString("en-US");
}

function duration(seconds) {
  if (seconds === null || seconds === undefined || !isFinite(seconds)) return "-";
  seconds = Math.max(0, Math.round(seconds));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h) return `${h} h ${String(m).padStart(2, "0")} min`;
  if (m) return `${m} min ${String(s).padStart(2, "0")} s`;
  return `${s} s`;
}

function secondsBetween(a, b) {
  if (!a || !b) return null;
  return (new Date(b) - new Date(a)) / 1000;
}

function clock(iso) {
  if (!iso) return "-";
  const d = new Date(iso);
  const today = new Date().toDateString() === d.toDateString();
  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return today ? time : `${d.toLocaleDateString([], { month: "short", day: "numeric" })} ${time}`;
}

function percent(job) {
  if (!job.total) return null;
  return Math.min(100, (100 * job.done) / job.total);
}

function badge(state) {
  const [icon, label] = STATES[state] || ["?", state];
  const node = el("span", `badge ${state}`);
  node.append(el("span", "icon", icon), el("span", null, label));
  return node;
}

function meter(value, small) {
  const node = el("div", small ? "meter small" : "meter");
  node.setAttribute("role", "progressbar");
  node.setAttribute("aria-valuemin", "0");
  node.setAttribute("aria-valuemax", "100");
  node.setAttribute("aria-valuenow", String(Math.round(value || 0)));
  const fill = el("div", "fill");
  fill.style.width = `${value || 0}%`;
  node.append(fill);
  return node;
}

function stat(label, value) {
  const node = el("div");
  node.append(el("dt", null, label), el("dd", null, value));
  return node;
}

function card(job, now) {
  const node = el("article", "card");
  const head = el("div", "card-head");
  head.append(el("span", "job", job.job), el("h3", null, job.name), badge(job.state));
  node.append(head, el("p", "stage", job.stage || "starting"));

  const pct = percent(job);
  node.append(meter(pct));
  const line = el("p", "count-line");
  line.append(el("b", null, number(job.done)));
  const unit = job.unit ? ` ${job.unit}` : "";
  line.append(job.total ? ` of ${number(job.total)}${unit} · ${pct.toFixed(0)}%` : `${unit} done`);
  node.append(line);

  const stats = el("dl", "stats");
  const speed = job.rate === null || job.rate === undefined ? "-" : `${job.rate.toFixed(1)}${unit} / min`;
  stats.append(
    stat("Speed", speed),
    stat("Time left", duration(job.eta_seconds)),
    stat("Elapsed", duration(secondsBetween(job.started, now))),
    stat("Retries", number(job.retries)),
  );
  node.append(stats);

  const parts = Object.entries(job.parts || {});
  if (parts.length) {
    const grid = el("div", "parts");
    for (const [name, part] of parts) {
      const value = part.total ? (100 * part.done) / part.total : 0;
      const bar = meter(value, true);
      bar.title = `${name}: ${part.done} of ${part.total}`;
      grid.append(el("span", "name", name), bar, el("span", "num", `${number(part.done)} / ${number(part.total)}`));
    }
    node.append(grid);
  }

  if (job.log && job.log.length) node.append(el("pre", "log", job.log.join("\n")));
  if (job.argv && job.argv.length) node.append(el("p", "argv", `cmeval ${job.argv.join(" ")}`));
  return node;
}

function resultText(job) {
  if (job.error) return job.error;
  if (job.state === "stopped") return "no final status: the process ended (killed?) or stopped writing (machine asleep?)";
  return Object.entries(job.result || {})
    .filter(([, v]) => v !== false && v !== null)
    .map(([k, v]) => (v === true ? k.replaceAll("_", " ") : `${k.replaceAll("_", " ")} ${typeof v === "number" ? number(v) : v}`))
    .join(", ");
}

function row(job) {
  const tr = el("tr");
  const stateCell = el("td");
  stateCell.append(badge(job.state));
  const done = job.total ? `${number(job.done)} / ${number(job.total)}` : number(job.done);
  const end = job.ended || job.updated;
  const result = el("td", job.error ? "result error" : "result", resultText(job));
  tr.append(
    el("td", null, job.job),
    el("td", "nowrap", job.name),
    stateCell,
    el("td", "num", `${done}${job.unit ? " " + job.unit : ""}`),
    el("td", "num", duration(secondsBetween(job.started, end))),
    el("td", "nowrap", clock(end)),
    result,
  );
  return tr;
}

function draw(data) {
  const running = document.getElementById("running");
  running.replaceChildren(...data.running.map((job) => card(job, data.now)));
  document.getElementById("running-empty").hidden = data.running.length > 0;
  document.getElementById("running-count").textContent = data.running.length ? `(${data.running.length})` : "";

  const body = document.querySelector("#recent tbody");
  body.replaceChildren(...data.recent.map(row));
  document.getElementById("recent").hidden = data.recent.length === 0;
  document.getElementById("recent-empty").hidden = data.recent.length > 0;
  if (data.folder) document.getElementById("folder").textContent = data.folder;

  const connection = document.getElementById("connection");
  connection.className = "connection";
  connection.textContent = `live · updated ${new Date().toLocaleTimeString()}`;
}

async function tick() {
  try {
    const response = await fetch("/api/jobs", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    draw(await response.json());
  } catch (error) {
    const connection = document.getElementById("connection");
    connection.className = "connection lost";
    connection.textContent = "the dashboard server is not reachable (is cmeval dashboard still running?)";
  } finally {
    setTimeout(tick, INTERVAL_MS);
  }
}

tick();
