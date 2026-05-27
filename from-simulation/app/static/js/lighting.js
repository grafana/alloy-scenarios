/*
 * lighting.js — day/night overlay.
 *
 * Reads `payload.lighting` from the tick (0 = dark, 1 = bright) and adjusts
 * the alpha of a full-map dim rectangle. CSS transitions the fill smoothly.
 * Also toggles a `.lit` class on the static lighthouse group so its lamp
 * glows when the phase is anything other than DAY.
 */
(function () {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";

  function ensureOverlay() {
    const layer = document.getElementById("lighting");
    if (!layer) return null;
    let rect = layer.querySelector("rect.lighting-overlay");
    if (!rect) {
      rect = document.createElementNS(SVG_NS, "rect");
      rect.setAttribute("class", "lighting-overlay");
      rect.setAttribute("x", 0);
      rect.setAttribute("y", 0);
      rect.setAttribute("width", 1000);
      rect.setAttribute("height", 700);
      rect.setAttribute("pointer-events", "none");
      rect.setAttribute("fill", "rgba(10, 12, 40, 0)");
      layer.appendChild(rect);
    }
    return rect;
  }

  function alphaFor(lighting) {
    // Clamp + invert: lighting=1 -> alpha=0 ; lighting=0 -> alpha=0.85
    const clamped = Math.max(0, Math.min(1, Number(lighting) || 0));
    return (1 - clamped) * 0.85;
  }

  function updateLighthouseGlow(phase) {
    // The static SVG is rendered as an <image>, so we can't reach inside it from
    // the host document. Instead we add an explicit overlay glow class to the
    // outer <svg id="world"> element keyed on phase, and style it from CSS if
    // a lighthouse halo overlay is added by future iterations. For now we just
    // expose `data-phase` for any future SVG-as-DOM swap-in.
    const world = document.getElementById("world");
    if (!world) return;
    world.dataset.phase = (phase || "DAY").toUpperCase();
    const lit = world.dataset.phase !== "DAY";
    // Inject (or refresh) a tiny lighthouse halo overlay on top of the map.
    let halo = document.getElementById("lighthouse-halo");
    if (lit) {
      if (!halo) {
        const overlays = document.getElementById("overlays");
        if (overlays) {
          halo = document.createElementNS(SVG_NS, "circle");
          halo.setAttribute("id", "lighthouse-halo");
          halo.setAttribute("cx", 500);
          halo.setAttribute("cy", 522);
          halo.setAttribute("r", 14);
          halo.setAttribute("fill", "rgba(244, 215, 122, 0.35)");
          halo.style.filter = "blur(6px)";
          halo.style.pointerEvents = "none";
          overlays.appendChild(halo);
        }
      }
    } else if (halo) {
      halo.remove();
    }
  }

  // ---------------------------------------------------------- v2: dream overlay
  // character_id -> <g class="dream-dialog">
  const dreamDialogs = new Map();

  function renderDreamOverlay(payload) {
    const world = document.getElementById("world");
    const overlays = document.getElementById("overlays");
    if (!world || !overlays) return;
    const dreams = Array.isArray(payload.dreams) ? payload.dreams : [];
    if (dreams.length === 0) {
      world.classList.remove("dream-mode");
      for (const [, g] of dreamDialogs) g.remove();
      dreamDialogs.clear();
      return;
    }
    world.classList.add("dream-mode");

    // Build an id -> {x, y} lookup from the agents in this snapshot.
    const agentXY = new Map();
    for (const a of (payload.agents || [])) {
      if (a && a.id) agentXY.set(a.id, { x: a.x, y: a.y });
    }

    const seen = new Set();
    for (const d of dreams) {
      if (!d || !d.character_id) continue;
      const pos = agentXY.get(d.character_id);
      if (!pos) continue;
      seen.add(d.character_id);
      let g = dreamDialogs.get(d.character_id);
      if (!g) {
        g = document.createElementNS(SVG_NS, "g");
        g.setAttribute("class", "dream-dialog");
        g.setAttribute("pointer-events", "none");
        overlays.appendChild(g);
        dreamDialogs.set(d.character_id, g);
      }
      // Position dialog just above and to the right of the dreaming dot.
      const ox = (pos.x || 0) + 12;
      const oy = (pos.y || 0) - 18;
      g.setAttribute("transform", `translate(${ox}, ${oy})`);
      // Show the latest 1-2 lines.
      while (g.firstChild) g.removeChild(g.firstChild);
      const lines = (Array.isArray(d.lines) ? d.lines : []).slice(-2);
      lines.forEach((line, i) => {
        const t = document.createElementNS(SVG_NS, "text");
        t.setAttribute("x", 0);
        t.setAttribute("y", i * 10);
        t.textContent = String(line || "").slice(0, 80);
        g.appendChild(t);
      });
    }
    // Cull dialogs for dreams that have ended this tick.
    for (const [id, g] of dreamDialogs) {
      if (!seen.has(id)) {
        g.remove();
        dreamDialogs.delete(id);
      }
    }
  }

  window.addEventListener("from:tick", (e) => {
    const payload = e.detail || {};
    const rect = ensureOverlay();
    if (rect) {
      const a = alphaFor(payload.lighting);
      rect.setAttribute("fill", `rgba(10, 12, 40, ${a.toFixed(3)})`);
    }
    const phase = (payload.time && payload.time.phase) || "DAY";
    updateLighthouseGlow(phase);
    renderDreamOverlay(payload);
  });
})();
