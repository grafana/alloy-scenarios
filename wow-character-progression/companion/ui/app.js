const el = (id) => document.getElementById(id);
const fields = [
  "stack_url",
  "loki_url",
  "loki_user",
  "otlp_url",
  "otlp_user",
  "loki_token",
  "otlp_token",
];
let state,
  busy = false;
function link(url, text) {
  const a = document.createElement("a");
  a.href = url;
  a.textContent = text;
  a.target = "_blank";
  a.rel = "noopener";
  return a;
}
function traceURL(stack, s) {
  const uid = "grafanacloud-traces",
    url = new URL("/explore", stack);
  const range = {
    from: new Date((s.ts - 60) * 1000).toISOString(),
    to: new Date(Date.parse(s.ended) + 60000).toISOString(),
  };
  const pane = {
    datasource: uid,
    queries: [
      {
        refId: "A",
        queryType: "traceql",
        query: s.trace_id,
        datasource: { type: "tempo", uid },
      },
    ],
    range,
  };
  url.searchParams.set("schemaVersion", "1");
  url.searchParams.set("panes", JSON.stringify({ trace: pane }));
  return url;
}
function dashboardURL(stack, s) {
  const url = new URL("/d/wow-character-gear", stack);
  if (s) {
    for (const field of ["character", "region", "realm"])
      url.searchParams.set("var-" + field, s[field]);
    url.searchParams.set("var-session", s.session_id);
    url.searchParams.set("from", s.ts * 1000 - 30000);
    url.searchParams.set(
      "to",
      Math.max(Date.parse(s.ended), s.checkpoint_ms || 0) + 60000,
    );
  }
  return url;
}
function node(tag, text, className) {
  const n = document.createElement(tag);
  n.textContent = text;
  if (className) n.className = className;
  return n;
}
const date = (value) =>
  new Date(value).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
const source = (value) =>
  ({ real: "Real character", simulated: "Simulated" })[value] ||
  "Earlier export";
const duration = (value) => Math.floor(value / 60) + "m " + (value % 60) + "s";
function drawRoute(stats, show) {
  const view = el("route-view"),
    pts = stats?.map_points;
  view.hidden = !show || !pts?.length;
  if (view.hidden) return;
  view.querySelector("figcaption").textContent =
    stats.map_zone +
    " · " +
    pts
      .at(-1)
      .map((v) => (v / 100).toFixed(2))
      .join(", ") +
    " · last position";
  const ctx = view.querySelector("canvas").getContext("2d");
  const xs = pts.map((p) => p[0]),
    ys = pts.map((p) => p[1]),
    minX = Math.min(...xs),
    minY = Math.min(...ys);
  const dx = Math.max(...xs) - minX,
    dy = Math.max(...ys) - minY,
    scale = Math.min(410 / Math.max(1, dx), 128 / Math.max(1, dy));
  const path = pts.map(([x, y]) => [
    (500 - dx * scale) / 2 + (x - minX) * scale,
    (170 - dy * scale) / 2 + (y - minY) * scale,
  ]);
  ctx.clearRect(0, 0, 500, 170);
  ctx.lineWidth = 1;
  ctx.strokeStyle = "#bfad8480";
  ctx.beginPath();
  for (let x = 10; x < 500; x += 30) {
    ctx.moveTo(x, 0);
    ctx.lineTo(x, 170);
  }
  for (let y = 10; y < 170; y += 30) {
    ctx.moveTo(0, y);
    ctx.lineTo(500, y);
  }
  ctx.stroke();
  ctx.beginPath();
  ctx.font = "italic 15px Georgia";
  ctx.fillStyle = "#584c34";
  ctx.fillText("N", 15, 18);
  ctx.beginPath();
  ctx.moveTo(21, 22);
  ctx.lineTo(16, 39);
  ctx.lineTo(21, 34);
  ctx.lineTo(26, 39);
  ctx.closePath();
  ctx.fill();
  ctx.beginPath();
  ctx.lineWidth = 4;
  ctx.strokeStyle = "#65542f";
  ctx.moveTo(...path[0]);
  for (const point of path) ctx.lineTo(...point);
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(...path[0], 6, 0, 2 * Math.PI);
  ctx.fillStyle = "#f2e9d4";
  ctx.fill();
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(...path[path.length - 1], 7, 0, 2 * Math.PI);
  ctx.fillStyle = "#305a46";
  ctx.fill();
}
function render(s) {
  state = s;
  const real = s.config.mode === "real",
    stack = s.cloud.stack_url;
  el("real").setAttribute("aria-pressed", real);
  el("simulated").setAttribute("aria-pressed", !real);
  el("source-title").textContent = real
    ? "Character saves"
    : "Session simulator";
  el("source-status").textContent = real
    ? s.client_present
      ? "Watching for saves"
      : "Waiting for WoW directory"
    : "Ready to generate";
  el("source-copy").textContent = real
    ? "Start recording once in WoW. Reloads export your session and resume recording."
    : "Run the addon with sample equipment or a leveling journey. The recording goes to your configured Grafana stack.";
  el("sim-controls").hidden = real;
  el("dashboard").hidden = !stack;
  el("progression").hidden = !stack;
  if (stack) {
    for (const [id, path] of [
      ["dashboard", "/d/wow-character-gear"],
      ["progression", "/d/wow-chronicle-progression"],
    ]) {
      const url = new URL(path, stack);
      if (s.latest) {
        for (const field of ["character", "realm", "region"])
          url.searchParams.set("var-" + field, s.latest[field]);
      }
      el(id).href = url;
    }
  }
  el("collector").textContent = s.collector;
  el("reader-error").textContent = real ? s.error : "";
  const read = s.latest;
  const last = s.sessions.find((item) => item.key === read?.key);
  drawRoute(last?.stats, true);
  el("entry-date").textContent = read
    ? new Date(read.ended).toLocaleDateString(undefined, {
        day: "numeric",
        month: "long",
        year: "numeric",
      })
    : "Field observations";
  if (read) {
    const heading = node("h3", read.character);
    const identity = node(
      "p",
      [
        last?.stats.zone,
        last?.stats.level != null ? "Level " + last.stats.level : null,
        read.realm + " · " + read.region.toUpperCase(),
      ]
        .filter(Boolean)
        .join("  /  "),
      "identity",
    );
    const timing = node(
      "p",
      source(read.origin) +
        " · Gameplay ended " +
        date(read.ended) +
        " · Read " +
        date(read.read_at * 1000),
      "timing",
    );
    const counts = node("div", "", "totals");
    for (const [value, label] of [
      [read.new_sessions, "New sessions"],
      [read.new_rows, "New events"],
      [read.known, "Already known"],
    ]) {
      const block = node("div", "");
      block.append(node("b", value), node("span", label));
      counts.append(block);
    }
    const notes = [];
    if (last) {
      const stats = last.stats;
      if (stats.combat_seconds > 0)
        notes.push(duration(stats.combat_seconds) + " in combat");
      if (stats.xp_gain > 0) notes.push(stats.xp_gain + " XP gained");
      if (stats.gear_swaps > 0)
        notes.push(
          stats.gear_swaps +
            " equipment " +
            (stats.gear_swaps === 1 ? "change" : "changes"),
        );
      if (stats.quest_turn_ins > 0)
        notes.push(stats.quest_turn_ins + " quests turned in");
    }
    const observation = node("p", notes.join(" · "), "observation");
    el("read-report").replaceChildren(
      heading,
      identity,
      observation,
      counts,
      timing,
    );
  } else
    el("read-report").textContent = real
      ? "Waiting for a character save."
      : "Generate a recording to see its receipt.";
  const list = el("sessions");
  const open = new Set(
    [...list.querySelectorAll("details[open]")].map((row) => row.dataset.key),
  );
  const focusKey = document.activeElement.closest("details")?.dataset.key;
  const rows = s.sessions.map((item) => {
    const stats = item.stats,
      row = node("details", "", "entry");
    row.dataset.key = item.key;
    row.open = open.has(item.key);
    const summary = node("summary", "");
    const title = node("span", "");
    title.append(
      node("strong", item.character),
      node(
        "small",
        item.realm +
          " · " +
          item.region.toUpperCase() +
          " · " +
          source(item.origin),
      ),
    );
    const place = node("span", "");
    place.append(
      node("strong", stats.zone || "Unknown zone"),
      node("small", date(item.ts * 1000)),
    );
    const counts = node("span", "");
    counts.append(
      node("strong", item.rows + " events"),
      node("small", duration(item.duration_seconds)),
    );
    const delivered = item.logs_read && item.metrics && item.traces;
    const state = delivered
      ? "Read & acknowledged"
      : item.metrics_attempt.error || item.traces_attempt.error
        ? "Retrying"
        : "Delivery pending";
    summary.append(
      title,
      place,
      counts,
      node("span", state, delivered ? "receipt ready" : "receipt"),
    );
    row.append(summary);
    const detail = node("div", "", "entry-body");
    const statsList = node(
      "p",
      [
        "Level " + (stats.level ?? "—"),
        (stats.combat_entries ?? "—") +
          " fights (" +
          (stats.combat_seconds ?? "—") +
          "s)",
        stats.quest_accepts + " quests accepted",
        stats.quest_turn_ins + " turned in",
        stats.gear_swaps + " gear swaps",
        "Armour " +
          (stats.armor_start ?? "—") +
          " → " +
          (stats.armor_final ?? "—"),
      ].join(" · "),
    );
    detail.append(
      statsList,
      node(
        "p",
        "Logs · " + (item.logs_read ? "Read by Alloy" : "Queued for Alloy"),
      ),
    );
    for (const [signal, name] of [
      ["metrics", "Metrics"],
      ["traces", "Traces"],
    ]) {
      const attempt = item[signal + "_attempt"];
      const label = item[signal]
        ? "Acknowledged by Alloy"
        : attempt.error
          ? "Retrying · " + attempt.error
          : "Pending";
      detail.append(
        node(
          "p",
          name +
            " · " +
            label +
            (attempt.ack
              ? " · " + date(attempt.ack * 1000)
              : attempt.at
                ? " · Attempted " + date(attempt.at * 1000)
                : ""),
        ),
      );
    }
    if (stack) {
      detail.append(link(dashboardURL(stack, item), "View session ↗"));
      if (item.traces)
        detail.append(link(traceURL(stack, item), "Open trace ↗"));
    }
    row.append(detail);
    return row;
  });
  // Retain disclosure state, focus and open links while polling an unchanged history.
  const signature = JSON.stringify([stack, s.sessions]);
  if (list.dataset.signature !== signature) {
    const active = document.activeElement;
    const activeIndex = active.closest("details")
      ? [...active.closest("details").querySelectorAll("summary,a")].indexOf(
          active,
        )
      : -1;
    list.replaceChildren(...rows);
    list.dataset.signature = signature;
    if (focusKey && activeIndex >= 0)
      rows
        .find((r) => r.dataset.key === focusKey)
        ?.querySelectorAll("summary,a")
        [activeIndex]?.focus();
  }
  el("session-count").textContent = rows.length + " shown";
  el("empty").hidden = !!rows.length;
}
async function refresh() {
  const r = await fetch("/status");
  if (!r.ok) throw Error("Companion unavailable");
  render(await r.json());
}
async function act(route, data = {}, message = "Saved.", inDialog = false) {
  if (busy) return;
  busy = true;
  const notice = el(inDialog ? "settings-notice" : "notice");
  notice.textContent =
    route.includes("cloud") || route.includes("collector")
      ? "Starting collector…"
      : "Working…";
  try {
    const r = await fetch(route, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    const result = await r.json();
    if (!r.ok) throw Error(result.error || "Request failed");
    await refresh();
    notice.textContent = message;
  } catch (e) {
    notice.textContent = e.message;
  } finally {
    busy = false;
  }
}
for (const mode of ["real", "simulated"])
  el(mode).onclick = () =>
    act(
      "/settings",
      { mode },
      mode === "real"
        ? "Watching for real character saves."
        : "Simulation mode selected.",
    );
el("generate").onclick = () =>
  act(
    "/simulate",
    { example: el("example").value },
    "Recording exported. Delivery updates appear below.",
  );
el("open-settings").onclick = () => {
  if (!state) return;
  el("client").value = state.config.client;
  el("interval").value = state.config.interval;
  for (const k of fields) {
    el(k).value = state.cloud[k] || "";
    if (k.endsWith("_token"))
      el(k).placeholder = state.cloud[k + "_set"]
        ? "Saved · leave blank to keep"
        : "";
  }
  el("settings-notice").textContent = "";
  el("settings").showModal();
};
el("close").onclick = () => el("settings").close();
el("config-form").onsubmit = (e) => {
  e.preventDefault();
  act(
    "/settings",
    { client: el("client").value, interval: Number(el("interval").value) },
    "Capture settings saved.",
    true,
  );
};
el("cloud-form").onsubmit = async (e) => {
  e.preventDefault();
  await act(
    "/cloud",
    Object.fromEntries(fields.map((k) => [k, el(k).value])),
    "Cloud settings saved. Collector started.",
    true,
  );
  el("loki_token").value = el("otlp_token").value = "";
};
el("start").onclick = () =>
  act("/start-collector", {}, "Collector started.", true);
async function poll() {
  try {
    await refresh();
  } catch (e) {
    el("source-status").textContent = "Companion offline";
  } finally {
    setTimeout(poll, 3500);
  }
}
poll();
