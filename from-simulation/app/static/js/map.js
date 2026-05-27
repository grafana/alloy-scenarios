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
  // id -> {ring: <circle>, lastKind: "tendril"|"tendril-leader"|"called"} for pulsing rings around dots
  const rings = new Map();
  // id -> <text> "+" glyph for outsiders
  const outsiderGlyphs = new Map();
  // building_id -> {group: <g>, lastCount}
  const hashGroups = new Map();
  // Single bus group (or null when bus inactive)
  let busGroup = null;
  let lastJournalKey = "";
  let lastVoiceTick = -1;

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
      const base = (a.name || a.id) + (a.role ? "  ·  " + a.role : "");
      // Optional drift indicator: agent may carry a "drift" field per v2;
      // when present (truthy), show a small "↕" glyph beside the name.
      const drifted = !!(a.drift || a.personality_drifted);
      li.textContent = base + (drifted ? "  ↕" : "");
      if (drifted) li.classList.add("drifted");
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

  // ---------------------------------------------------------- v2: hash marks on buildings
  function renderHashMarks(buildings, marks) {
    const overlays = $("overlays");
    if (!overlays) return;
    const seenBuildings = new Set();
    const safeMarks = marks || {};

    for (const b of buildings) {
      if (!b || !b.id) continue;
      const count = Math.max(0, Math.floor(safeMarks[b.id] || 0));
      if (count === 0) {
        // Tear down any group we previously created for this building.
        const existing = hashGroups.get(b.id);
        if (existing) {
          existing.group.remove();
          hashGroups.delete(b.id);
        }
        continue;
      }
      seenBuildings.add(b.id);
      let entry = hashGroups.get(b.id);
      if (!entry) {
        const g = document.createElementNS(SVG_NS, "g");
        g.setAttribute("class", "hash-marks");
        overlays.appendChild(g);
        entry = { group: g, lastCount: -1 };
        hashGroups.set(b.id, entry);
      }
      // Anchor at (b.x + 30, b.y + 30).
      const ox = (b.x || 0) + 30;
      const oy = (b.y || 0) + 30;
      entry.group.setAttribute("transform", `translate(${ox}, ${oy})`);

      if (entry.lastCount === count) continue;
      entry.lastCount = count;

      // Clear and redraw — up to 12 tally lines + optional "+N" overflow label.
      while (entry.group.firstChild) entry.group.removeChild(entry.group.firstChild);

      const visible = Math.min(12, count);
      // Render in groups of 5 — four uprights + diagonal slash.
      for (let i = 0; i < visible; i++) {
        const groupIdx = Math.floor(i / 5);
        const posInGroup = i % 5;
        const gx = groupIdx * 10;
        if (posInGroup < 4) {
          const line = document.createElementNS(SVG_NS, "line");
          line.setAttribute("x1", gx + posInGroup * 2);
          line.setAttribute("y1", 0);
          line.setAttribute("x2", gx + posInGroup * 2);
          line.setAttribute("y2", 8);
          entry.group.appendChild(line);
        } else {
          const slash = document.createElementNS(SVG_NS, "line");
          slash.setAttribute("x1", gx - 1);
          slash.setAttribute("y1", 8);
          slash.setAttribute("x2", gx + 7);
          slash.setAttribute("y2", 0);
          entry.group.appendChild(slash);
        }
      }
      if (count > 12) {
        const txt = document.createElementNS(SVG_NS, "text");
        txt.setAttribute("x", Math.ceil(visible / 5) * 10 + 2);
        txt.setAttribute("y", 7);
        txt.setAttribute("class", "hash-overflow");
        txt.textContent = "+" + (count - 12);
        entry.group.appendChild(txt);
      }
    }

    // Tear down groups for buildings that no longer have any marks.
    for (const [bid, entry] of hashGroups) {
      if (!seenBuildings.has(bid)) {
        entry.group.remove();
        hashGroups.delete(bid);
      }
    }
  }

  // ---------------------------------------------------------- v2: bus
  function renderBus(bus) {
    const overlays = $("overlays");
    if (!overlays) return;
    if (!bus || !bus.active) {
      if (busGroup) {
        busGroup.remove();
        busGroup = null;
      }
      return;
    }
    if (!busGroup) {
      const g = document.createElementNS(SVG_NS, "g");
      g.setAttribute("class", "bus");
      // Hand-drawn-feel yellow school bus, ~50 x 20 (centered on origin).
      g.innerHTML = [
        '<rect class="bus-body-rect" x="-25" y="-10" width="50" height="20" rx="3" ry="3"></rect>',
        '<rect class="bus-window" x="-21" y="-7" width="8" height="6"></rect>',
        '<rect class="bus-window" x="-11" y="-7" width="8" height="6"></rect>',
        '<rect class="bus-window" x="-1" y="-7" width="8" height="6"></rect>',
        '<rect class="bus-window" x="9" y="-7" width="8" height="6"></rect>',
        '<rect class="bus-door" x="18" y="-3" width="5" height="9"></rect>',
        '<circle class="bus-wheel" cx="-15" cy="11" r="3"></circle>',
        '<circle class="bus-wheel" cx="15" cy="11" r="3"></circle>',
      ].join("");
      overlays.appendChild(g);
      busGroup = g;
    }
    busGroup.setAttribute("transform", `translate(${bus.x || 0}, ${bus.y || 0})`);
  }

  // ---------------------------------------------------------- v2: outsider glyphs
  function applyOutsiderGlyph(item, seenGlyphs) {
    if (!item || item.kind !== "outsider") return;
    seenGlyphs.add(item.id);
    let glyph = outsiderGlyphs.get(item.id);
    if (!glyph) {
      const overlays = $("overlays");
      if (!overlays) return;
      glyph = document.createElementNS(SVG_NS, "text");
      glyph.setAttribute("class", "outsider-glyph");
      glyph.setAttribute("text-anchor", "middle");
      glyph.textContent = "+";
      overlays.appendChild(glyph);
      outsiderGlyphs.set(item.id, glyph);
    }
    glyph.setAttribute("x", item.x);
    glyph.setAttribute("y", (item.y || 0) - 8);
  }

  function pruneOutsiderGlyphs(seenGlyphs) {
    for (const [id, el] of outsiderGlyphs) {
      if (!seenGlyphs.has(id)) {
        el.remove();
        outsiderGlyphs.delete(id);
      }
    }
  }

  // ---------------------------------------------------------- v2: pulsing rings (tendrils + called)
  function applyRing(id, x, y, kind) {
    let entry = rings.get(id);
    if (!entry) {
      const overlays = $("overlays");
      if (!overlays) return;
      const c = document.createElementNS(SVG_NS, "circle");
      c.setAttribute("r", 10);
      c.setAttribute("fill", "none");
      c.setAttribute("pointer-events", "none");
      overlays.appendChild(c);
      entry = { ring: c, lastKind: null };
      rings.set(id, entry);
    }
    if (entry.lastKind !== kind) {
      entry.ring.setAttribute("class", kind);
      entry.lastKind = kind;
    }
    entry.ring.setAttribute("cx", x);
    entry.ring.setAttribute("cy", y);
  }

  function pruneRings(seenRingIds) {
    for (const [id, entry] of rings) {
      if (!seenRingIds.has(id)) {
        entry.ring.remove();
        rings.delete(id);
      }
    }
  }

  // ---------------------------------------------------------- v2: journal panel
  function renderJournal(legacy) {
    const ol = $("journal-list");
    const witnessed = $("hud-cycles-witnessed");
    const frag = $("hud-fragments");
    if (witnessed) {
      const n = (legacy && legacy.cycles_witnessed) || 0;
      witnessed.textContent = "Cycle " + n + " of all that has ever been";
    }
    if (!ol) return;
    const fragments = (legacy && Array.isArray(legacy.journal_fragments))
      ? legacy.journal_fragments : [];
    if (frag) frag.textContent = "📜 " + fragments.length + " fragments";
    // Cheap change-key — only re-render when content shifts.
    const key = fragments.map((f) => `${f.cycle}|${f.burned}|${f.text}`).join("");
    if (key === lastJournalKey) return;
    lastJournalKey = key;
    ol.innerHTML = "";
    // Oldest first (server already trims to last 12).
    for (const f of fragments) {
      const li = document.createElement("li");
      const burned = Math.max(0, Math.min(1, Number(f.burned) || 0));
      li.style.opacity = (1 - burned * 0.85).toFixed(3);
      li.textContent = "D" + (f.cycle != null ? f.cycle : "?") + ": " + (f.text || "");
      ol.appendChild(li);
    }
  }

  // ---------------------------------------------------------- v2: lighthouse-voice panel
  function renderLighthouseVoice(payload) {
    const panel = $("lighthouse-voice");
    const list = $("lighthouse-voice-list");
    if (!panel || !list) return;
    const lh = payload.lighthouse || {};
    if (!lh.voice_active) {
      panel.style.display = "none";
      return;
    }
    panel.style.display = "";
    const events = Array.isArray(payload.events) ? payload.events : [];
    const voiceEvents = events.filter((e) => e && e.type === "lighthouse_voice").slice(-10);
    const newestTick = voiceEvents.length ? voiceEvents[voiceEvents.length - 1].tick : -1;
    if (newestTick === lastVoiceTick && list.childElementCount === voiceEvents.length) return;
    lastVoiceTick = newestTick;
    list.innerHTML = "";
    for (const ev of voiceEvents) {
      const li = document.createElement("li");
      li.textContent = ev.detail || "(silence)";
      list.appendChild(li);
    }
  }

  // ---------------------------------------------------------- v2: bus panel
  function renderBusPanel(payload) {
    const panel = $("bus-panel");
    const list = $("bus-passengers");
    const countdown = $("bus-countdown");
    if (!panel || !list || !countdown) return;
    const bus = payload.bus || {};
    if (!bus.active) {
      panel.style.display = "none";
      list.innerHTML = "";
      countdown.textContent = "—";
      return;
    }
    panel.style.display = "";
    // Lookup agents by id.
    const agents = Array.isArray(payload.agents) ? payload.agents : [];
    const byId = new Map(agents.map((a) => [a.id, a]));
    const passengers = Array.isArray(bus.passengers) ? bus.passengers : [];
    list.innerHTML = "";
    for (const pid of passengers) {
      const agent = byId.get(pid);
      const li = document.createElement("li");
      const name = (agent && (agent.name || agent.id)) || pid;
      const back = agent && (agent.backstory || agent.goal || agent.role);
      li.innerHTML = "<strong>" + escapeHtml(name) + "</strong>" +
        (back ? '<span class="bus-back"> — ' + escapeHtml(String(back)) + "</span>" : "");
      list.appendChild(li);
    }
    if (passengers.length === 0) {
      const li = document.createElement("li");
      li.className = "bus-empty";
      li.textContent = "(no passengers boarded yet)";
      list.appendChild(li);
    }
    // Departure countdown — next_arrival_cycle is a cycle counter, so display it raw.
    const next = bus.next_arrival_cycle;
    countdown.textContent = next != null ? ("Next bus: cycle " + next) : "—";
  }

  // ---------------------------------------------------------- main tick
  function handleTick(payload) {
    const seen = new Set();
    const counts = { char: 0, npc: 0, creature: 0, other: 0 };

    const agents = Array.isArray(payload.agents) ? payload.agents : [];
    const creatures = Array.isArray(payload.creatures) ? payload.creatures : [];
    const supes = Array.isArray(payload.supernaturals) ? payload.supernaturals : [];

    const seenGlyphs = new Set();
    for (const a of agents) {
      applyAgent(a, seen);
      applyOutsiderGlyph(a, seenGlyphs);
      if (a.marker_class === "char") counts.char++;
      else if (a.marker_class === "npc") counts.npc++;
      else if (a.kind === "outsider" || a.marker_class === "outsider") counts.other++;
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
    pruneOutsiderGlyphs(seenGlyphs);

    // ---- v2: rings (tendrils + called) ----
    const yellow = payload.yellow || {};
    const tendrils = new Set(Array.isArray(yellow.tendrils) ? yellow.tendrils : []);
    const leader = yellow.disguised_as || null;
    const lighthouse = payload.lighthouse || {};
    const calledId = lighthouse.called || null;

    const seenRingIds = new Set();
    const dotById = new Map();
    for (const a of agents) dotById.set(a.id, a);

    for (const id of tendrils) {
      const a = dotById.get(id);
      if (!a) continue;
      const kind = (id === leader) ? "tendril-leader" : "tendril";
      applyRing(id, a.x, a.y, kind);
      seenRingIds.add(id);
    }
    if (calledId) {
      const a = dotById.get(calledId);
      if (a) {
        // If the called character is also a tendril, the called ring overrides (slow aqua pulse).
        applyRing(calledId, a.x, a.y, "called");
        seenRingIds.add(calledId);
      }
    }
    pruneRings(seenRingIds);

    // ---- v2: hash marks + bus ----
    const buildings = Array.isArray(payload.buildings) ? payload.buildings : [];
    const legacy = payload.legacy || {};
    renderHashMarks(buildings, legacy.building_breach_marks);
    renderBus(payload.bus);

    updateHud(payload);
    updateStats(payload, counts);
    renderEvents(payload.events || []);
    renderRosterList(agents);
    renderNarration(payload.narration);

    // v2 right-column panels
    renderJournal(legacy);
    renderLighthouseVoice(payload);
    renderBusPanel(payload);
  }

  window.addEventListener("from:tick", (e) => handleTick(e.detail));
  window.addEventListener("from:inspect_reply", (e) => renderInspect(e.detail));
})();
