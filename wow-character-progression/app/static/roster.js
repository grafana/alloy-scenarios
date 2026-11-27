const form = document.querySelector("#enroll");
const roster = document.querySelector("#roster");
const notice = document.querySelector("#notice");
const dashboard = new URL(
  "/d/wow-progression/character-progression",
  location.href,
);
dashboard.port = document.body.dataset.grafanaPort;
document.querySelector("#dashboard").href = dashboard.href;
let rendered;
let requestNumber = 0;

function card(row) {
  const el = document.querySelector("#card").content.cloneNode(true);
  const snap = row.snapshot;
  el.querySelector("h3").textContent = row.name;
  el.querySelector(".identity").textContent = [
    row.region.toUpperCase(),
    snap?.class_name,
  ]
    .filter(Boolean)
    .join(" · ");
  const portrait = el.querySelector(".portrait");
  portrait.textContent = row.name
    .split(" ")
    .map((part) => Array.from(part)[0])
    .join("");
  if (snap?.avatar) {
    const image = new Image();
    image.alt = "";
    image.onload = () => portrait.replaceChildren(image);
    image.src = snap.avatar;
  }
  for (const [i, field] of ["level", "item_level", "achievements"].entries()) {
    el.querySelectorAll("dd")[i].textContent = snap?.[field] ?? "—";
  }
  const state = el.querySelector(".state");
  const last = row.last_success
    ? "Last synced " + new Date(row.last_success * 1000).toLocaleString()
    : "";
  state.textContent =
    [row.error, last].filter(Boolean).join(" · ") ||
    "Waiting for first profile…";
  if (row.error) state.classList.add("issue");
  const history = new URL(dashboard);
  history.searchParams.set("var-region", row.region);
  history.searchParams.set("var-character", row.slug);
  el.querySelector(".history").href = history.href;
  const remove = el.querySelector(".remove");
  remove.setAttribute("aria-label", "Stop tracking " + row.name);
  remove.onclick = async () => {
    try {
      const reply = await fetch("/api/characters/" + row.id, {
        method: "DELETE",
      });
      if (!reply.ok) throw new Error();
      await refresh();
      notice.textContent = "Stopped tracking " + row.name + ".";
    } catch {
      notice.textContent = "Could not stop tracking. Please try again.";
    }
  };
  return el;
}

async function refresh() {
  const id = ++requestNumber;
  const error = document.querySelector("#load-error");
  try {
    const response = await fetch("/api/characters", { cache: "no-store" });
    if (!response.ok) throw new Error();
    const rows = await response.json();
    if (id !== requestNumber) return;
    error.textContent = "";
    const key = JSON.stringify(rows);
    if (key === rendered) return;
    rendered = key;
    document.querySelector("#count").textContent = rows.length;
    roster.replaceChildren(...rows.map(card));
    if (!rows.length) {
      const p = document.createElement("p");
      p.className = "empty";
      p.textContent =
        "Add your first character to start recording progression.";
      roster.append(p);
    }
  } catch {
    error.textContent = "Could not refresh the roster. Reconnecting…";
  }
}

form.onsubmit = async (event) => {
  event.preventDefault();
  const button = form.querySelector("button");
  button.disabled = true;
  try {
    const reply = await fetch("/api/characters", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.fromEntries(new FormData(form))),
    });
    const data = await reply.json();
    if (!reply.ok) {
      notice.textContent = data.error;
      return;
    }
    notice.textContent = "Tracking started.";
    form.elements.name.value = "";
    await refresh();
  } catch {
    notice.textContent = "Could not reach the tracker. Please try again.";
  } finally {
    button.disabled = false;
  }
};

refresh();
setInterval(refresh, 5000);

const routeForm = document.querySelector("#route-form");
routeForm.onsubmit = async (event) => {
  event.preventDefault();
  const button = routeForm.querySelector("button");
  const status = document.querySelector("#route-status");
  const visits = document.querySelector("#route-visits");
  const file = document.querySelector("#route-file").files[0];
  visits.replaceChildren();
  if (!file || file.size > 1024 * 1024) {
    status.textContent = "Choose an AlloyRoute.lua saved file smaller than 1 MiB.";
    return;
  }
  button.disabled = true;
  status.textContent = "Sending route to Alloy…";
  try {
    const reply = await fetch("/api/routes", {
      method: "POST", headers: {"Content-Type":"application/octet-stream"}, body:file
    });
    const data = await reply.json();
    if (!reply.ok) throw new Error(data.error);
    status.textContent = (data.duplicate ? "Previously imported" : "Imported") +
      " · " + data.character + " · " + data.observations + " observations";
    for (const visit of data.visits) {
      const link = document.createElement("a");
      const url = new URL("/explore", dashboard);
      url.searchParams.set("left", JSON.stringify({
        datasource:"tempo", queries:[{query:visit.trace_id,queryType:"traceql",refId:"A"}],
        range:{from:String((visit.start-60)*1000),to:String((visit.end+60)*1000)}
      }));
      link.href = url.href;
      link.textContent = visit.zone + " · " + new Date(visit.start*1000).toLocaleTimeString();
      const item = document.createElement("li");
      item.append(link);
      visits.append(item);
    }
  } catch (error) { status.textContent = error.message || "Import failed. Try again."; }
  finally { button.disabled = false; }
};
