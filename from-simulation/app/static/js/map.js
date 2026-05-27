/*
 * map.js — render the per-tick snapshot onto the SVG, drive the UI panels.
 *
 * v3 changes:
 *  - Named characters render as <use href="#token-{name}"> hand-drawn tokens
 *    that live inside the inline map SVG's <defs> as 60x80 <symbol>s.
 *  - Man in Yellow / Boy in White render the same way (token-yellow / token-white).
 *  - NPCs / creatures / anghkooey keep simple shapes (circle / polygon).
 *  - Outsiders keep v2 styling: circle with a '+' glyph above.
 *  - Forest scatter is generated once per session into <g id="forest"> via a
 *    seeded mulberry32 RNG (matches the design reference exactly).
 *  - Hash marks use a per-building offset table for the 5 talisman set.
 *
 * Tick payload keys (see contracts.snapshot_dict): tick, time, lighting,
 *   cycle_number, village_wipes, food_supply, food_capacity, farm_health,
 *   yellow:{mode, deadline_in, tendrils, disguised_as},
 *   buildings[], agents[], creatures[], supernaturals[], events[],
 *   narration[]?, legacy:{building_breach_marks, journal_fragments,
 *   cycles_witnessed}, lighthouse:{voice_active, called}, bus:{...},
 *   dreams[].
 */
(function () {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";

  // Tokens we have hand-drawn SVG <symbol>s for.
  const TOKEN_NAMES = new Set([
    "boyd", "donna", "jim", "tabitha", "ethan", "julie",
    "jade", "kenny", "khatri", "sara", "yellow", "white",
  ]);

  // Per-building hash-mark anchor offsets. Other buildings fall back to [18, 18].
  const HASH_OFFSET = {
    colony_house:   [ 28,  18],
    clinic:         [ 16,  18],
    church:         [ 22, -22],
    sheriff_office: [ 18,  20],
    matthews_home:  [ 16,  18],
  };
  const HASH_OFFSET_DEFAULT = [18, 18];

  // Per-pool live registries. id -> {el, kind, lastClass}
  // kind === "token" means el is a <use>, kind === "shape" means el is the primary
  // SVG element (circle/polygon).
  const entities = new Map();

  // id -> {ring: <circle>, lastKind} for pulsing rings around dots.
  const rings = new Map();
  // id -> <text> "+" glyph for outsiders.
  const outsiderGlyphs = new Map();
  // building_id -> {group: <g>, lastCount}
  const hashGroups = new Map();
  // Single bus group (or null when bus inactive).
  let busGroup = null;
  let lastJournalKey = "";
  let lastVoiceTick = -1;
  let selectedId = null;
  let lastEventTick = -1;

  // Forest scatter runs once per session.
  let forestScattered = false;

  function $(id) { return document.getElementById(id); }

  // ---------------------------------------------------------- Forest scatter
  // Seeded RNG copied verbatim from Fromville_Map.html (mulberry32).
  function mulberry32(seed) {
    return function () {
      let t = seed += 0x6D2B79F5;
      t = Math.imul(t ^ t >>> 15, t | 1);
      t ^= t + Math.imul(t ^ t >>> 7, t | 61);
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }

  // The big meadow polygon; trees go OUTSIDE this clearing for the dark forest
  // ring at the edges. Also a handful are placed INSIDE the meadow but away
  // from town/landmarks/road/water for texture.
  const MEADOW = [
    [60,220],[80,130],[220,70],[380,80],[520,60],[660,70],[800,110],
    [880,140],[940,230],[920,340],[950,460],[870,580],[720,620],
    [600,680],[440,690],[300,660],[180,640],[60,540],[50,420],[30,360],
  ];
  const TOWN_PTS = [
    {x:385,y:420},{x:418,y:400},{x:442,y:388},{x:478,y:402},{x:495,y:432},
    {x:390,y:470},{x:385,y:510},{x:420,y:490},{x:440,y:490},{x:462,y:478},
    {x:478,y:462},{x:510,y:458},{x:555,y:454},{x:490,y:510},{x:460,y:538},
    {x:430,y:545},{x:405,y:530},{x:382,y:552},
  ];
  const LANDMARK_PTS = [
    {x:560,y:55},{x:465,y:195},{x:620,y:225},{x:760,y:218},{x:380,y:325},
    {x:615,y:335},{x:260,y:510},{x:345,y:580},{x:275,y:610},{x:470,y:615},
    {x:240,y:650},{x:735,y:485},{x:390,y:670},{x:575,y:660},{x:720,y:670},
    {x:140,y:585},
  ];

  function pointInPoly(x, y, poly) {
    let inside = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const xi = poly[i][0], yi = poly[i][1];
      const xj = poly[j][0], yj = poly[j][1];
      const intersect = ((yi > y) !== (yj > y)) &&
        (x < (xj - xi) * (y - yi) / (yj - yi + 1e-9) + xi);
      if (intersect) inside = !inside;
    }
    return inside;
  }
  function nearAny(x, y, pts, r) {
    return pts.some((p) => (p.x - x) ** 2 + (p.y - y) ** 2 < r * r);
  }
  function nearRoad(x, y) {
    const segs = [
      [-20,200, 240,320], [240,320, 395,405], [395,405, 555,405],
      [555,405, 575,425], [575,425, 565,555], [565,555, 720,690],
    ];
    for (const [ax, ay, bx, by] of segs) {
      const dx = bx - ax, dy = by - ay;
      const t = Math.max(0, Math.min(1,
        ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy + 1e-9)));
      const px = ax + t * dx, py = ay + t * dy;
      if ((px - x) ** 2 + (py - y) ** 2 < 22 * 22) return true;
    }
    return false;
  }

  function scatterForest() {
    if (forestScattered) return;
    const forestG = $("forest");
    if (!forestG) return;
    forestScattered = true;

    const rng = mulberry32(42);
    const symbols = ["#tree", "#tree-dark", "#tree-pine"];
    const placed = [];

    // ~300 trees outside the meadow polygon.
    for (let i = 0; i < 300; i++) {
      const x = rng() * 1000;
      const y = rng() * 700;
      if (pointInPoly(x, y, MEADOW)) continue;
      if (nearAny(x, y, placed, 14)) continue;
      placed.push({ x, y });
      const sym = symbols[Math.floor(rng() * symbols.length)];
      const scale = 0.7 + rng() * 0.9;
      const use = document.createElementNS(SVG_NS, "use");
      use.setAttribute("href", sym);
      use.setAttribute("transform",
        `translate(${x.toFixed(1)} ${y.toFixed(1)}) scale(${scale.toFixed(2)})`);
      forestG.appendChild(use);
    }

    // ~60 extras inside the meadow, away from points of interest.
    const avoid = [
      ...TOWN_PTS.map((t) => ({ x: t.x, y: t.y, r: 30 })),
      ...LANDMARK_PTS.map((L) => ({ x: L.x, y: L.y, r: 30 })),
      { x: 745, y: 240, r: 65 }, // lake
      { x: 375, y: 335, r: 30 }, // brundles
      { x: 155, y: 220, r: 30 }, // small pond
    ];
    function nearAvoid(x, y) {
      return avoid.some((a) => (a.x - x) ** 2 + (a.y - y) ** 2 < a.r * a.r);
    }
    const extras = [];
    for (let i = 0; i < 60; i++) {
      const x = 70 + rng() * 860;
      const y = 90 + rng() * 540;
      if (!pointInPoly(x, y, MEADOW)) continue;
      if (nearAvoid(x, y)) continue;
      if (nearRoad(x, y)) continue;
      if (nearAny(x, y, extras, 32)) continue;
      extras.push({ x, y });
      const sym = symbols[Math.floor(rng() * symbols.length)];
      const scale = 0.55 + rng() * 0.5;
      const use = document.createElementNS(SVG_NS, "use");
      use.setAttribute("href", sym);
      use.setAttribute("transform",
        `translate(${x.toFixed(1)} ${y.toFixed(1)}) scale(${scale.toFixed(2)})`);
      use.setAttribute("opacity", "0.92");
      forestG.appendChild(use);
    }
  }

  // ---------------------------------------------------------- Entity rendering
  // Decide which token symbol id (if any) to use for a given agent.
  function tokenIdFor(item) {
    if (!item || !item.name) return null;
    const key = String(item.name).toLowerCase().trim();
    // Strip "the " prefixes for Man in Yellow / Boy in White if present.
    if (key.includes("yellow")) return "token-yellow";
    if (key.includes("white"))  return "token-white";
    if (TOKEN_NAMES.has(key)) return "token-" + key;
    // Marker-class fallbacks for supernaturals carrying no name.
    const mc = item.marker_class || "";
    if (mc === "man-in-yellow") return "token-yellow";
    if (mc === "boy-in-white")  return "token-white";
    return null;
  }

  function attachClick(el, id) {
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      selectedId = id;
      if (window.FROM_SOCKET) window.FROM_SOCKET.emit("inspect", { id });
      highlightRoster(id);
    });
  }

  function ensureToken(id, symbolId, klass) {
    let entry = entities.get(id);
    if (entry && entry.kind === "token" && entry.symbolId === symbolId) {
      return entry;
    }
    if (entry) {
      // Kind/symbol changed — tear down and rebuild.
      entry.el.remove();
      entities.delete(id);
    }
    const layer = $("entities");
    if (!layer) return null;
    const use = document.createElementNS(SVG_NS, "use");
    use.setAttribute("href", "#" + symbolId);
    use.setAttribute("class", "token " + klass);
    use.setAttribute("data-id", id);
    layer.appendChild(use);
    attachClick(use, id);
    entry = { el: use, kind: "token", symbolId, klass };
    entities.set(id, entry);
    return entry;
  }

  function ensureShape(id, tag, klass, attrs) {
    let entry = entities.get(id);
    if (entry && entry.kind === "shape" && entry.tag === tag) {
      if (entry.klass !== klass) {
        entry.el.setAttribute("class", klass);
        entry.klass = klass;
      }
      return entry;
    }
    if (entry) {
      entry.el.remove();
      entities.delete(id);
    }
    const layer = $("entities");
    if (!layer) return null;
    const el = document.createElementNS(SVG_NS, tag);
    el.setAttribute("class", klass);
    el.setAttribute("data-id", id);
    if (attrs) {
      for (const k in attrs) el.setAttribute(k, attrs[k]);
    }
    layer.appendChild(el);
    attachClick(el, id);
    entry = { el, kind: "shape", tag, klass };
    entities.set(id, entry);
    return entry;
  }

  function placeToken(entry, x, y) {
    // 60x80 viewBox centered roughly on token's belt; scale 0.55 ⇒ visual ~33x44.
    // Anchor so that (x,y) sits at the centre of the token's mass.
    entry.el.setAttribute(
      "transform",
      `translate(${(x - 15).toFixed(2)} ${(y - 22).toFixed(2)}) scale(0.55)`,
    );
  }

  function applyAgent(item, seenIds) {
    if (!item || !item.id) return;
    seenIds.add(item.id);

    const tokenId = tokenIdFor(item);
    const x = item.x || 0;
    const y = item.y || 0;

    if (tokenId) {
      const klass = (item.marker_class || "char") === "man-in-yellow"
        ? "yellow"
        : (item.marker_class === "boy-in-white" ? "white" : "char");
      const entry = ensureToken(item.id, tokenId, klass);
      if (entry) placeToken(entry, x, y);
      return;
    }

    // Fallback shapes by marker_class.
    const mc = item.marker_class || "npc";
    if (mc === "creature") {
      // small jagged triangle, points roughly forming a creature glyph
      const entry = ensureShape(item.id, "polygon", "creature", {
        points: "0,-7 6,5 -2,2 -6,5",
      });
      if (entry) entry.el.setAttribute("transform", `translate(${x} ${y})`);
      return;
    }
    if (mc === "anghkooey") {
      const entry = ensureShape(item.id, "circle", "anghkooey", { r: 5 });
      if (entry) {
        entry.el.setAttribute("cx", x);
        entry.el.setAttribute("cy", y);
      }
      return;
    }
    if (mc === "music-box") {
      // small ornate gold box with soft pulsing glow
      const entry = ensureShape(item.id, "rect", "music-box", {
        x: -6, y: -4, width: 12, height: 8, rx: 1,
      });
      if (entry) entry.el.setAttribute("transform", `translate(${x} ${y})`);
      return;
    }
    if (mc === "cicada") {
      const entry = ensureShape(item.id, "circle", "cicada", { r: 1.6 });
      if (entry) {
        entry.el.setAttribute("cx", x);
        entry.el.setAttribute("cy", y);
      }
      return;
    }
    if (item.kind === "outsider" || mc === "outsider") {
      const entry = ensureShape(item.id, "circle", "outsider", { r: 7 });
      if (entry) {
        entry.el.setAttribute("cx", x);
        entry.el.setAttribute("cy", y);
      }
      return;
    }
    // Default: NPC dot.
    // v5: NPC default — promoted sub-mains get a larger circle + a chevron;
    // tombstoned ones render with a fading "✝" glyph for ~30 ticks.
    const isSubMain = item.is_sub_main === true;
    const isDead = (item.status === "DEAD");
    const r = isSubMain ? 7.5 : 6;
    const klass = isSubMain ? (isDead ? "npc sub-main tombstone" : "npc sub-main") : "npc";
    const entry = ensureShape(item.id, "circle", klass, { r });
    if (entry) {
      entry.el.setAttribute("cx", x);
      entry.el.setAttribute("cy", y);
      // Keep the class fresh in case status flips between ticks (alive -> tombstone).
      entry.el.setAttribute("class", klass);
    }
    if (isSubMain) {
      // chevron marker: a tiny "^" rendered as a polyline 8 px above the dot.
      const chevId = item.id + "::chev";
      const chev = ensureShape(chevId, "polyline", isDead ? "sub-main-chev tombstone" : "sub-main-chev", {
        points: "-3,-12 0,-16 3,-12",
      });
      if (chev) chev.el.setAttribute("transform", `translate(${x} ${y})`);
      seenIds.add(chevId);
      // Tombstone cross glyph for dead sub-mains.
      if (isDead) {
        const xId = item.id + "::cross";
        const cross = ensureShape(xId, "text", "tombstone-cross", {});
        if (cross) {
          cross.el.setAttribute("x", x);
          cross.el.setAttribute("y", y - 18);
          cross.el.setAttribute("text-anchor", "middle");
          cross.el.textContent = "✝";
        }
        seenIds.add(xId);
      }
    }
  }

  function removeEntities(seenIds) {
    for (const [id, entry] of entities) {
      if (!seenIds.has(id)) {
        entry.el.remove();
        entities.delete(id);
      }
    }
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
    const latestTick = events[events.length - 1].tick;
    if (latestTick === lastEventTick) return;
    lastEventTick = latestTick;
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
    if (list.childElementCount === agents.length) return;
    list.innerHTML = "";
    for (const a of agents) {
      const li = document.createElement("li");
      const base = (a.name || a.id) + (a.role ? "  ·  " + a.role : "");
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
    if (!Array.isArray(items) || items.length === 0) return;
    panel.style.display = "";
    list.innerHTML = "";
    items.slice(-10).reverse().forEach((line) => {
      const li = document.createElement("li");
      li.textContent = typeof line === "string" ? line : (line && line.text) || "";
      list.appendChild(li);
    });
  }

  // ---------------------------------------------------------- v4: cooling-off haze
  const coolingMarkers = new Map();
  function renderCoolingOff(buildings) {
    const overlays = $("overlays");
    if (!overlays) return;
    const live = new Set();
    for (const b of buildings) {
      if (!b || !b.id) continue;
      const cooling = (b.cooling_off || 0) > 0 || b.protected === false && b.has_talisman;
      if (!cooling) continue;
      live.add(b.id);
      let entry = coolingMarkers.get(b.id);
      if (!entry) {
        const g = document.createElementNS(SVG_NS, "g");
        g.setAttribute("class", "cooling-off");
        const haze = document.createElementNS(SVG_NS, "rect");
        haze.setAttribute("x", -22);
        haze.setAttribute("y", -22);
        haze.setAttribute("width", 44);
        haze.setAttribute("height", 44);
        haze.setAttribute("rx", 4);
        g.appendChild(haze);
        overlays.appendChild(g);
        entry = { group: g };
        coolingMarkers.set(b.id, entry);
      }
      entry.group.setAttribute("transform", `translate(${b.x || 0} ${b.y || 0})`);
    }
    for (const [id, entry] of coolingMarkers) {
      if (!live.has(id)) {
        entry.group.remove();
        coolingMarkers.delete(id);
      }
    }
  }

  // ---------------------------------------------------------- v2: hash marks
  function renderHashMarks(buildings, marks) {
    const overlays = $("overlays");
    if (!overlays) return;
    const seenBuildings = new Set();
    const safeMarks = marks || {};

    for (const b of buildings) {
      if (!b || !b.id) continue;
      const count = Math.max(0, Math.floor(safeMarks[b.id] || 0));
      if (count === 0) {
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

      // v3: per-building offset table for the 5 talisman set, fallback otherwise.
      const off = HASH_OFFSET[b.id] || HASH_OFFSET_DEFAULT;
      const ox = (b.x || 0) + off[0];
      const oy = (b.y || 0) + off[1];
      entry.group.setAttribute("transform", `translate(${ox}, ${oy})`);

      if (entry.lastCount === count) continue;
      entry.lastCount = count;

      while (entry.group.firstChild) entry.group.removeChild(entry.group.firstChild);

      const visible = Math.min(12, count);
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

    for (const [bid, entry] of hashGroups) {
      if (!seenBuildings.has(bid)) {
        entry.group.remove();
        hashGroups.delete(bid);
      }
    }
  }

  // ---------------------------------------------------------- v2: bus marker
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

  // ---------------------------------------------------------- v2: outsider '+'
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

  // ---------------------------------------------------------- v2: pulsing rings
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
    const key = fragments.map((f) => `${f.cycle}|${f.burned}|${f.text}`).join("");
    if (key === lastJournalKey) return;
    lastJournalKey = key;
    ol.innerHTML = "";
    for (const f of fragments) {
      const li = document.createElement("li");
      const burned = Math.max(0, Math.min(1, Number(f.burned) || 0));
      li.style.opacity = (1 - burned * 0.85).toFixed(3);
      li.textContent = "D" + (f.cycle != null ? f.cycle : "?") + ": " + (f.text || "");
      ol.appendChild(li);
    }
  }

  // ---------------------------------------------------------- v2: lighthouse-voice
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
    const next = bus.next_arrival_cycle;
    countdown.textContent = next != null ? ("Next bus: cycle " + next) : "—";
  }

  // ---------------------------------------------------------- main tick
  function handleTick(payload) {
    // Forest scatter runs once per session, on the first real tick.
    scatterForest();

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

    removeEntities(seen);
    pruneOutsiderGlyphs(seenGlyphs);

    // ---- v2: rings (tendrils + called) ----
    const yellow = payload.yellow || {};
    const tendrils = new Set(Array.isArray(yellow.tendrils) ? yellow.tendrils : []);
    const leader = yellow.disguised_as || null;
    const lighthouse = payload.lighthouse || {};
    const calledId = lighthouse.called || null;

    const seenRingIds = new Set();
    const agentById = new Map();
    for (const a of agents) agentById.set(a.id, a);

    for (const id of tendrils) {
      const a = agentById.get(id);
      if (!a) continue;
      const kind = (id === leader) ? "tendril-leader" : "tendril";
      applyRing(id, a.x, a.y, kind);
      seenRingIds.add(id);
    }
    if (calledId) {
      const a = agentById.get(calledId);
      if (a) {
        applyRing(calledId, a.x, a.y, "called");
        seenRingIds.add(calledId);
      }
    }
    pruneRings(seenRingIds);

    const buildings = Array.isArray(payload.buildings) ? payload.buildings : [];
    const legacy = payload.legacy || {};
    renderHashMarks(buildings, legacy.building_breach_marks);
    renderCoolingOff(buildings);
    renderBus(payload.bus);

    updateHud(payload);
    updateStats(payload, counts);
    renderEvents(payload.events || []);
    renderRosterList(agents);
    renderNarration(payload.narration);

    renderJournal(legacy);
    renderLighthouseVoice(payload);
    renderBusPanel(payload);
  }

  window.addEventListener("from:tick", (e) => handleTick(e.detail));
  window.addEventListener("from:inspect_reply", (e) => renderInspect(e.detail));
})();
