/*
 * map.js — render the per-tick snapshot onto the SVG, drive the UI panels.
 *
 * Tick payload keys we read (see contracts.snapshot_dict):
 *   tick, time, lighting, cycle_number, village_wipes,
 *   food_supply, food_capacity, farm_health,
 *   yellow:{mode, deadline_in},
 *   buildings[], agents[], creatures[], supernaturals[], events[],
 *   narration[]?  (optional — only present when the LLM driver is wired)
 *
 * We maintain a Map id -> {circle, label} so updates are O(deltas), not O(N²).
 */
(function () {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";
  const RADIUS_BY_CLASS = {
    "char": 6,
    "npc": 4.5,
    "creature": 5,
    "boy-in-white": 5,
    "man-in-yellow": 6,
    "anghkooey": 5,
    "faraway-tree": 0, // already drawn in static SVG; skip rendering
  };

  // Per-pool live registries. id -> {el, lastClass}
  const dots = new Map();

  let selectedId = null;
  let lastEventTick = -1;

  function $(id) { return document.getElementById(id); }

  function ensureCircle(id, markerClass) {
    let entry = dots.get(id);
    const r = RADIUS_BY_CLASS[markerClass] != null ? RADIUS_BY_CLASS[markerClass] : 4;
    if (r === 0) return null; // faraway-trees live in the static map
    if (entry) {
      if (entry.lastClass !== markerClass) {
        entry.el.setAttribute("class", markerClass);
        entry.el.setAttribute("r", r);
        entry.lastClass = markerClass;
      }
      return entry;
    }
    const layer = $("entities");
    if (!layer) return null;
    const circle = document.createElementNS(SVG_NS, "circle");
    circle.setAttribute("class", markerClass);
    circle.setAttribute("r", r);
    circle.setAttribute("data-id", id);
    circle.addEventListener("click", (e) => {
      e.stopPropagation();
      selectedId = id;
      if (window.FROM_SOCKET) {
        window.FROM_SOCKET.emit("inspect", { id });
      }
      highlightRoster(id);
    });
    layer.appendChild(circle);
    entry = { el: circle, lastClass: markerClass };
    dots.set(id, entry);
    return entry;
  }

  function removeDots(seenIds) {
    for (const [id, entry] of dots) {
      if (!seenIds.has(id)) {
        entry.el.remove();
        dots.delete(id);
      }
    }
  }

  function applyAgent(item, seenIds) {
    if (!item || !item.id) return;
    seenIds.add(item.id);
    const entry = ensureCircle(item.id, item.marker_class || "npc");
    if (!entry) return;
    entry.el.setAttribute("cx", item.x);
    entry.el.setAttribute("cy", item.y);
  }

  // ---------------------------------------------------------- HUD updates
  function pct(num, denom) {
    if (!denom) return 0;
    return Math.max(0, Math.min(100, (num / denom) * 100));
  }
  function updateHud(payload) {
    const time = payload.time || {};
    const clock = $("hud-clock");
    if (clock) clock.textContent = time.label || `D${time.day || 0} ${pad(time.hour)}:${pad(time.minute)} ${time.phase || ""}`;
    const phase = $("hud-phase");
    if (phase) {
      const p = (time.phase || "DAY").toUpperCase();
      phase.textContent = p;
      phase.className = "hud-chip phase-" + p.toLowerCase();
    }
    const cycle = $("hud-cycle");
    if (cycle) cycle.textContent = payload.cycle_number || 1;

    const foodFill = $("hud-food-fill");
    const foodText = $("hud-food-text");
    if (foodFill && foodText) {
      const p = pct(payload.food_supply, payload.food_capacity || 200);
      foodFill.style.width = p.toFixed(1) + "%";
      foodText.textContent = Math.round(payload.food_supply || 0) + " / " + (payload.food_capacity || 200);
    }
    const farmFill = $("hud-farm-fill");
    const farmText = $("hud-farm-text");
    if (farmFill && farmText) {
      const p = (payload.farm_health || 0) * 100;
      farmFill.style.width = p.toFixed(1) + "%";
      farmText.textContent = Math.round(p) + "%";
    }

    const yellow = payload.yellow || { mode: "DORMANT", deadline_in: 0 };
    const yel = $("hud-yellow");
    if (yel) {
      if (!yellow.mode || yellow.mode === "DORMANT") {
        yel.classList.add("hidden");
      } else {
        yel.classList.remove("hidden");
        const mode = yellow.mode.toLowerCase();
        yel.className = "hud-chip yellow-" + mode;
        const deadline = yellow.deadline_in ? `  T-${yellow.deadline_in}` : "";
        yel.textContent = "Yellow Man: " + yellow.mode + deadline;
      }
    }
  }
  function pad(n) { return String(n == null ? 0 : n).padStart(2, "0"); }

  // ---------------------------------------------------------- Stats panel
  function updateStats(payload, counts) {
    setText("stat-tick", payload.tick);
    setText("stat-cycle", payload.cycle_number);
    setText("stat-wipes", payload.village_wipes || 0);
    setText("stat-lighting", (payload.lighting != null ? payload.lighting : 0).toFixed(3));
    setText("stat-food", Math.round(payload.food_supply || 0) + " / " + (payload.food_capacity || 200));
    setText("stat-farm", Math.round((payload.farm_health || 0) * 100) + "%");
    setText("stat-chars", counts.char);
    setText("stat-npcs", counts.npc);
    setText("stat-creatures", counts.creature);
    const y = payload.yellow || { mode: "DORMANT" };
    setText("stat-yellow", y.mode || "DORMANT");

    // Roster summary chips
    const roster = $("roster-summary");
    if (roster) {
      roster.querySelector('[data-pool="char"]').textContent = counts.char + " chars";
      roster.querySelector('[data-pool="npc"]').textContent = counts.npc + " NPCs";
      roster.querySelector('[data-pool="creature"]').textContent = counts.creature + " creatures";
    }
  }
  function setText(id, v) {
    const el = $(id);
    if (el) el.textContent = v == null ? "—" : String(v);
  }

  // ---------------------------------------------------------- Event log
  function renderEvents(events) {
    if (!Array.isArray(events) || events.length === 0) return;
    const ol = $("event-log");
    if (!ol) return;

    // Append only new events since last tick (deduped by tick + type + subject).
    const latestTick = events[events.length - 1].tick;
    if (latestTick === lastEventTick) return;
    lastEventTick = latestTick;

    // Replace contents — payload already last-50 from server.
    ol.innerHTML = "";
    for (let i = events.length - 1; i >= 0; i--) {
      const ev = events[i];
      const li = document.createElement("li");
      li.className = "sev-" + (ev.severity || "info");
      const tickSpan = document.createElement("span");
      tickSpan.className = "ev-tick";
      tickSpan.textContent = "t" + ev.tick;
      const typeSpan = document.createElement("span");
      typeSpan.className = "ev-type t-" + (ev.type || "info");
      typeSpan.textContent = ev.type || "?";
      const detail = document.createElement("span");
      detail.className = "ev-detail";
      detail.textContent = ev.subject ? (ev.subject + " — " + (ev.detail || "")) : (ev.detail || "");
      li.appendChild(tickSpan);
      li.appendChild(typeSpan);
      li.appendChild(detail);
      ol.appendChild(li);
    }
  }

  // ---------------------------------------------------------- Roster list
  function renderRosterList(agents) {
    const list = $("roster-list");
    if (!list) return;
    // Re-render only when count changes — names rarely shift mid-tick.
    if (list.childElementCount === agents.length) return;
    list.innerHTML = "";
    for (const a of agents) {
      const li = document.createElement("li");
      li.textContent = (a.name || a.id) + (a.role ? "  ·  " + a.role : "");
      li.dataset.id = a.id;
      if (a.id === selectedId) li.classList.add("selected");
      li.addEventListener("click", () => {
        selectedId = a.id;
        if (window.FROM_SOCKET) window.FROM_SOCKET.emit("inspect", { id: a.id });
        highlightRoster(a.id);
      });
      list.appendChild(li);
    }
  }
  function highlightRoster(id) {
    const list = $("roster-list");
    if (!list) return;
    list.querySelectorAll("li").forEach((li) => {
      li.classList.toggle("selected", li.dataset.id === id);
    });
  }

  // ---------------------------------------------------------- Inspect detail
  function renderInspect(record) {
    const box = $("roster-detail");
    if (!box) return;
    if (!record || record.error) {
      box.innerHTML = '<div class="roster-empty">' +
        (record && record.error ? record.error : "No selection.") + "</div>";
      return;
    }
    const fields = [
      ["id", record.id],
      ["name", record.name],
      ["kind", record.kind],
      ["role", record.role],
      ["status", record.status],
      ["state", record.state],
      ["personality", record.personality],
      ["fear", record.fear != null ? Number(record.fear).toFixed(2) : null],
      ["sanity", record.sanity != null ? Number(record.sanity).toFixed(2) : null],
      ["trust", record.trust],
      ["hunger", record.hunger],
      ["home", record.home_id],
      ["faction", record.faction],
    ];
    const title = record.name || record.id;
    let html = `<h4>${escapeHtml(title)}</h4><dl class="kv">`;
    for (const [k, v] of fields) {
      if (v == null || v === "") continue;
      html += `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(String(v))}</dd>`;
    }
    html += "</dl>";
    box.innerHTML = html;
  }
  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[c]);
  }

  // ---------------------------------------------------------- Narration
  function renderNarration(items) {
    const panel = $("narration-panel");
    const list = $("narration");
    if (!panel || !list) return;
    if (!Array.isArray(items) || items.length === 0) {
      // leave panel hidden if server has never sent any
      return;
    }
    panel.style.display = "";
    list.innerHTML = "";
    items.slice(-10).reverse().forEach((line) => {
      const li = document.createElement("li");
      li.textContent = typeof line === "string" ? line : (line && line.text) || "";
      list.appendChild(li);
    });
  }

  // ---------------------------------------------------------- main tick
  function handleTick(payload) {
    const seen = new Set();
    const counts = { char: 0, npc: 0, creature: 0, other: 0 };

    const agents = Array.isArray(payload.agents) ? payload.agents : [];
    const creatures = Array.isArray(payload.creatures) ? payload.creatures : [];
    const supes = Array.isArray(payload.supernaturals) ? payload.supernaturals : [];

    for (const a of agents) {
      applyAgent(a, seen);
      if (a.marker_class === "char") counts.char++;
      else if (a.marker_class === "npc") counts.npc++;
      else counts.other++;
    }
    for (const c of creatures) {
      applyAgent(c, seen);
      counts.creature++;
    }
    for (const s of supes) {
      applyAgent(s, seen);
      counts.other++;
    }

    removeDots(seen);
    updateHud(payload);
    updateStats(payload, counts);
    renderEvents(payload.events || []);
    renderRosterList(agents);
    renderNarration(payload.narration);
  }

  window.addEventListener("from:tick", (e) => handleTick(e.detail));
  window.addEventListener("from:inspect_reply", (e) => renderInspect(e.detail));
})();
