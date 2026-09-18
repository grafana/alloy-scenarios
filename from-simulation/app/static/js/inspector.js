/*
 * inspector.js — v6 dossier overlay + SVG viewBox zoom.
 *
 * Lifecycle:
 *   1. User clicks a token on the map. map.js emits an `inspect` socket
 *      event with the clicked agent's id.
 *   2. The Flask server resolves the agent and emits `inspect_reply` back,
 *      which socket.js fans out as a `from:inspect` window event with the
 *      full agent record (now including v6 fields: intent, inventory,
 *      relationships, memory_recent).
 *   3. This module catches `from:inspect`, animates the SVG viewBox to
 *      zoom on the agent's (x, y), and renders the dossier panel.
 *   4. Close (button, Escape, or click outside the dossier) → restore the
 *      original viewBox and hide the panel.
 *
 * Self-contained IIFE: no globals beyond the existing window event bus.
 */
(function () {
  "use strict";

  // viewport for the world map; matches the inline SVG declaration in
  // _map_svg.html. Used as the "rest" frame to restore on close.
  const DEFAULT_VIEWBOX = [0, 0, 1000, 700];
  const ZOOM_W = 200;
  const ZOOM_H = 150;
  const ANIM_MS = 400;

  let currentRecord = null;          // last full record received
  let animRaf = 0;                   // RAF handle for the in-flight tween
  let restoreViewBox = DEFAULT_VIEWBOX.slice();

  function $(id) { return document.getElementById(id); }

  // ---------------------------------------------------------------- helpers
  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[c]);
  }

  function slugFor(record) {
    if (!record) return null;
    const name = String(record.name || "").toLowerCase().trim();
    if (name.includes("yellow")) return "yellow";
    if (name.includes("white"))  return "white";
    const known = new Set([
      "boyd", "donna", "jim", "tabitha", "ethan", "julie",
      "jade", "kenny", "khatri", "sara",
    ]);
    if (known.has(name)) return name;
    const mc = record.marker_class || "";
    if (mc === "man-in-yellow") return "yellow";
    if (mc === "boy-in-white")  return "white";
    return null;
  }

  function parseViewBox(svg) {
    const raw = svg && svg.getAttribute("viewBox");
    if (!raw) return DEFAULT_VIEWBOX.slice();
    const parts = raw.split(/[\s,]+/).map(Number).filter((n) => !isNaN(n));
    if (parts.length !== 4) return DEFAULT_VIEWBOX.slice();
    return parts;
  }

  // ---------------------------------------------------------------- zoom
  function easeOutCubic(t) { return 1 - Math.pow(1 - t, 3); }

  function tweenViewBox(svg, from, to, durationMs) {
    if (animRaf) {
      cancelAnimationFrame(animRaf);
      animRaf = 0;
    }
    const start = performance.now();
    function step(now) {
      const t = Math.min(1, (now - start) / durationMs);
      const e = easeOutCubic(t);
      const x = from[0] + (to[0] - from[0]) * e;
      const y = from[1] + (to[1] - from[1]) * e;
      const w = from[2] + (to[2] - from[2]) * e;
      const h = from[3] + (to[3] - from[3]) * e;
      svg.setAttribute(
        "viewBox",
        `${x.toFixed(2)} ${y.toFixed(2)} ${w.toFixed(2)} ${h.toFixed(2)}`
      );
      if (t < 1) {
        animRaf = requestAnimationFrame(step);
      } else {
        animRaf = 0;
      }
    }
    animRaf = requestAnimationFrame(step);
  }

  function zoomToAgent(x, y) {
    const svg = document.getElementById("map");
    if (!svg) return;
    // Save the viewBox the FIRST time we zoom — subsequent zooms (clicking
    // a second token without closing) should still restore to the original
    // pre-zoom frame, not the zoomed one we just left.
    if (!isOpen()) restoreViewBox = parseViewBox(svg);
    const from = parseViewBox(svg);
    // Clamp the zoom rect inside the world bounds so we don't pan into the
    // void when a token is right at the edge.
    const minX = Math.max(0, Math.min(1000 - ZOOM_W, x - ZOOM_W / 2));
    const minY = Math.max(0, Math.min(700 - ZOOM_H, y - ZOOM_H / 2));
    tweenViewBox(svg, from, [minX, minY, ZOOM_W, ZOOM_H], ANIM_MS);
  }

  function restoreZoom() {
    const svg = document.getElementById("map");
    if (!svg) return;
    const from = parseViewBox(svg);
    tweenViewBox(svg, from, restoreViewBox, ANIM_MS);
  }

  // ---------------------------------------------------------------- dossier
  function isOpen() {
    const el = $("dossier");
    return !!(el && !el.classList.contains("hidden"));
  }

  function close() {
    const el = $("dossier");
    if (!el) return;
    if (!el.classList.contains("hidden")) {
      el.classList.add("hidden");
      restoreZoom();
    }
    currentRecord = null;
  }

  function renderTokenSvg(slug) {
    if (!slug) {
      // Generic silhouette for NPCs / creatures / unknowns. Uses a stylised
      // pin shape so the dossier header isn't visually empty.
      return [
        '<svg viewBox="0 0 60 80" width="60" height="80" aria-hidden="true">',
        '<ellipse cx="30" cy="76" rx="12" ry="1.5" fill="#1a1611" opacity="0.4"/>',
        '<circle cx="30" cy="28" r="14" fill="#7d6a4a" stroke="#1a1611" stroke-width="1"/>',
        '<path d="M 14 70 Q 30 50 46 70 L 48 76 L 12 76 Z" fill="#7d6a4a" stroke="#1a1611" stroke-width="1"/>',
        "</svg>",
      ].join("");
    }
    return [
      '<svg viewBox="0 0 60 80" width="60" height="80" aria-hidden="true">',
      `<use href="#token-${escapeHtml(slug)}" />`,
      "</svg>",
    ].join("");
  }

  function vitalBar(klass, label, value) {
    // Values may be 0..1 (fear/sanity, floats) or 0..100 (hunger).
    let pct;
    if (value == null || isNaN(value)) {
      pct = 0;
    } else if (value <= 1.0001) {
      pct = Math.max(0, Math.min(100, value * 100));
    } else {
      pct = Math.max(0, Math.min(100, value));
    }
    const display = value == null
      ? "—"
      : (value <= 1.0001 ? value.toFixed(2) : Math.round(value));
    return [
      '<div class="vital">',
      `<span class="vital-label">${escapeHtml(label)}</span>`,
      `<div class="bar ${escapeHtml(klass)}"><div class="bar-fill" style="width:${pct.toFixed(1)}%"></div></div>`,
      `<span class="vital-val">${escapeHtml(display)}</span>`,
      "</div>",
    ].join("");
  }

  function renderInventory(inventory) {
    const items = inventory && typeof inventory === "object" ? inventory : {};
    const keys = Object.keys(items).filter((k) => Number(items[k]) > 0);
    if (keys.length === 0) {
      return '<ul class="inventory"><li class="muted">Empty pockets</li></ul>';
    }
    const rows = keys.map((k) => {
      const qty = Number(items[k]) || 0;
      const pretty = k.replace(/_/g, " ");
      return `<li><span class="item-name">${escapeHtml(pretty)}</span><span class="item-qty">×${qty}</span></li>`;
    });
    return `<ul class="inventory">${rows.join("")}</ul>`;
  }

  function renderRelationships(rel) {
    const trusted = (rel && Array.isArray(rel.trusted)) ? rel.trusted : [];
    const mistrusted = (rel && Array.isArray(rel.mistrusted)) ? rel.mistrusted : [];
    function rows(list, klass, empty) {
      if (list.length === 0) {
        return `<li class="muted">${escapeHtml(empty)}</li>`;
      }
      return list.map((r) => {
        const score = (r && typeof r.score === "number") ? r.score.toFixed(2) : "—";
        return `<li><span class="rel-name">${escapeHtml(r.partner_name || r.partner_id || "?")}</span><span class="rel-score ${klass}">${escapeHtml(score)}</span></li>`;
      }).join("");
    }
    return [
      '<div class="relationships">',
      '<h3>Trusted</h3>',
      `<ul class="rel-list pos">${rows(trusted, "pos", "no strong allies")}</ul>`,
      '<h3>Mistrusted</h3>',
      `<ul class="rel-list neg">${rows(mistrusted, "neg", "no enemies recorded")}</ul>`,
      "</div>",
    ].join("");
  }

  function renderMemory(memory) {
    const rows = Array.isArray(memory) ? memory : [];
    if (rows.length === 0) {
      return '<ol class="memory"><li class="muted">No recent memories on file.</li></ol>';
    }
    const items = rows.map((m) => {
      const tick = m && m.tick != null ? "t" + m.tick : "";
      const kind = m && m.kind ? `[${String(m.kind).toUpperCase()}]` : "";
      const detail = m && m.detail ? m.detail : "(silent)";
      return [
        "<li>",
        `<span class="mem-tick">${escapeHtml(tick)}</span>`,
        `<span class="kind">${escapeHtml(kind)}</span>`,
        `<span class="detail">${escapeHtml(detail)}</span>`,
        "</li>",
      ].join("");
    });
    return `<ol class="memory">${items.join("")}</ol>`;
  }

  function isCreature(record) {
    const k = String(record.kind || "").toLowerCase();
    const mc = String(record.marker_class || "").toLowerCase();
    return k === "creature" || mc.startsWith("creature");
  }

  function isBuilding(record) {
    return String(record.kind || "").toLowerCase() === "building";
  }

  function isCar(record) {
    return String(record.kind || "").toLowerCase() === "car";
  }

  // v9 — Mind section in the dossier: active goal + top 3 beliefs.
  function renderMind(mind) {
    if (!mind || typeof mind !== "object") {
      return [
        '<div class="mind-section">',
          '<h4>Mind</h4>',
          '<div class="mind-empty">No active thoughts.</div>',
        '</div>',
      ].join("");
    }
    const goal = mind.active_goal;
    const beliefs = Array.isArray(mind.beliefs) ? mind.beliefs : [];
    const parts = ['<div class="mind-section"><h4>Mind</h4>'];
    if (goal) {
      const prio = Math.round((goal.priority || 0) * 100);
      parts.push(
        '<div class="mind-goal">',
          `<span class="goal-kind">${escapeHtml(goal.kind || "")}</span>`,
          `<span class="goal-target">${escapeHtml(goal.target || "")}</span>`,
          `<span class="goal-priority">P=${prio}</span>`,
        '</div>'
      );
    } else {
      parts.push('<div class="mind-empty">No active goal.</div>');
    }
    if (beliefs.length === 0) {
      parts.push('<div class="mind-empty">No formed beliefs yet.</div>');
    } else {
      parts.push('<ul class="mind-beliefs">');
      beliefs.forEach(function (b) {
        const conf = Math.max(0, Math.min(1, b.confidence || 0));
        const polCls = (b.polarity || 0) >= 0 ? "belief-polarity-positive" : "belief-polarity-negative";
        const glyph = (b.polarity || 0) >= 0 ? "▲" : "▼";
        parts.push(
          '<li>',
            `<span class="${polCls}">${glyph}</span>`,
            `<span class="belief-key">${escapeHtml(b.key || "")}</span>`,
            `<span class="belief-note">${escapeHtml(b.note || "")}</span>`,
            '<span class="belief-conf"><span class="belief-conf-fill" ',
              `style="width:${(conf * 100).toFixed(0)}%"></span></span>`,
          '</li>'
        );
      });
      parts.push('</ul>');
    }
    parts.push(
      `<div class="mind-empty">Reflections: ${mind.reflections_count || 0}</div>`,
      '</div>'
    );
    return parts.join("");
  }

  function renderCar(record) {
    const pass = record.passenger;
    const passLine = pass && pass.name
      ? `${escapeHtml(pass.name)}`
      : "no passenger";
    return [
      '<dl class="creature-facts">',
        '<dt>Mode</dt>',
        `<dd>${escapeHtml(record.substate || "—")}</dd>`,
        '<dt>Passenger</dt>',
        `<dd>${passLine}</dd>`,
        '<dt>Trip</dt>',
        `<dd>${escapeHtml(record.outbound_done > 0 ? "leaving town" : "arriving")}</dd>`,
      "</dl>",
    ].join("");
  }

  function renderBuilding(record) {
    const occupants = Array.isArray(record.occupants_inside) ? record.occupants_inside : [];
    const residents = Array.isArray(record.residents_away) ? record.residents_away : [];
    const status = record.destroyed
      ? "Destroyed"
      : (record.cooling_off_in_ticks > 0
          ? `Cooling off (${record.cooling_off_in_ticks} ticks)`
          : "Intact");
    const cap = record.capacity || 0;
    const occ = record.occupied || 0;
    const capLine = cap > 0
      ? `${occ} of ${cap}${record.full ? " (FULL)" : ""}`
      : "—";
    const facts = [
      '<dl class="creature-facts">',
        '<dt>Talisman</dt>',
        `<dd>${record.has_talisman ? "Warded" : "None"}</dd>`,
        '<dt>State</dt>',
        `<dd>${escapeHtml(status)}</dd>`,
        '<dt>Capacity</dt>',
        `<dd>${escapeHtml(capLine)}</dd>`,
        '<dt>Damage</dt>',
        `<dd>${escapeHtml(String(record.damage || 0))}</dd>`,
      record.destroyed
        ? `<dt>Rebuild</dt><dd>${(record.rebuild_progress || 0).toFixed(1)} / 50</dd>`
        : "",
      "</dl>",
    ].join("");

    function listSection(label, list, empty) {
      if (!list.length) {
        return `<h3>${escapeHtml(label)}</h3>`
          + `<div class="muted-line">${escapeHtml(empty)}</div>`;
      }
      const rows = list.map((p) => {
        const role = p.role
          ? `<span class="building-role"> · ${escapeHtml(String(p.role))}</span>`
          : "";
        return `<li><span class="rel-name">${escapeHtml(p.name)}</span>${role}</li>`;
      }).join("");
      return `<h3>${escapeHtml(label)}</h3>`
        + `<ul class="building-list">${rows}</ul>`;
    }
    return [
      facts,
      listSection("Inside now", occupants, "No one is inside right now."),
      listSection("Lives here", residents, "No one calls this home."),
    ].join("");
  }

  function renderCreatureExtras(record) {
    // Creatures don't have vitals/inventory/relationships/memory — surface
    // the substate FSM fields instead so clicking a creature is useful.
    const target = record.target || record.target_id || "";
    const targetLabel = record.target_name || target || "—";
    const substate = record.substate || record.status || "—";
    const victim = record.victim_id || "—";
    return [
      '<dl class="creature-facts">',
        '<dt>Mode</dt>',
        `<dd>${escapeHtml(substate)}</dd>`,
        '<dt>Target</dt>',
        `<dd>${escapeHtml(targetLabel)}</dd>`,
        '<dt>Quarry</dt>',
        `<dd>${escapeHtml(victim)}</dd>`,
      "</dl>",
    ].join("");
  }

  function render(record) {
    const dossier = $("dossier");
    if (!dossier || !record) return;
    currentRecord = record;

    if (record.error) {
      dossier.innerHTML = [
        '<button class="close" type="button" aria-label="Close">×</button>',
        `<div class="error">${escapeHtml(record.error)}</div>`,
      ].join("");
      dossier.classList.remove("hidden");
      wireClose();
      return;
    }

    const slug = slugFor(record);
    const name = record.name || record.id || "Unknown";
    const role = record.role || record.kind || "";
    const status = record.status || record.state || "";
    const intent = (record.intent && String(record.intent).trim()) ||
      "Going about their business.";

    const building = isBuilding(record);
    const car = !building && isCar(record);
    const creature = !building && !car && isCreature(record);
    const body = building
      ? renderBuilding(record)
      : car
      ? renderCar(record)
      : creature
      ? [
          `<p class="intent">${escapeHtml(intent)}</p>`,
          renderCreatureExtras(record),
        ].join("")
      : [
          `<p class="intent">${escapeHtml(intent)}</p>`,
          '<div class="vitals">',
            vitalBar("fear",   "Fear",   record.fear),
            vitalBar("sanity", "Sanity", record.sanity),
            vitalBar("hunger", "Hunger", record.hunger),
          "</div>",
          renderMind(record.mind),
          "<h3>Inventory</h3>",
          renderInventory(record.inventory),
          renderRelationships(record.relationships),
          "<h3>Recent memory</h3>",
          renderMemory(record.memory_recent),
        ].join("");

    const html = [
      '<button class="close" type="button" aria-label="Close">×</button>',
      '<div class="header">',
        renderTokenSvg(slug),
        '<div class="header-text">',
          `<h2>${escapeHtml(name)}</h2>`,
          `<span class="role">${escapeHtml(role)}${role && status ? " · " : ""}${escapeHtml(status)}</span>`,
        "</div>",
      "</div>",
      body,
    ].join("");

    dossier.innerHTML = html;
    dossier.classList.remove("hidden");
    wireClose();
  }

  function wireClose() {
    const dossier = $("dossier");
    if (!dossier) return;
    const btn = dossier.querySelector(".close");
    if (btn) {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        close();
      });
    }
  }

  // ---------------------------------------------------------------- events
  window.addEventListener("from:inspect", (e) => {
    const record = e && e.detail;
    if (!record || !record.id) return;

    // Zoom: prefer the agent's coords from the reply, falling back to looking
    // up the on-screen token transform if the server omitted x/y.
    let x = Number(record.x);
    let y = Number(record.y);
    if (!isFinite(x) || !isFinite(y)) {
      const el = document.querySelector(`#entities [data-id="${record.id}"]`);
      if (el) {
        const cx = Number(el.getAttribute("cx"));
        const cy = Number(el.getAttribute("cy"));
        if (isFinite(cx) && isFinite(cy)) { x = cx; y = cy; }
      }
    }
    if (isFinite(x) && isFinite(y)) zoomToAgent(x, y);

    render(record);
  });

  // Close via Escape.
  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && isOpen()) {
      close();
    }
  });

  // Click outside the dossier closes it. We listen on the document so any
  // click anywhere on the page that ISN'T inside #dossier dismisses the panel.
  // Clicks on map tokens still re-open it via the inspect round-trip.
  document.addEventListener("click", (e) => {
    if (!isOpen()) return;
    const dossier = $("dossier");
    if (!dossier) return;
    if (dossier.contains(e.target)) return;
    // If the click was on a map token, the new inspect cycle will re-render
    // before this close fires — but the close listener runs first. Defer the
    // close one frame so the new render wins.
    const onToken = e.target && (e.target.closest && e.target.closest("[data-id]"));
    if (onToken) return;
    close();
  });
})();
