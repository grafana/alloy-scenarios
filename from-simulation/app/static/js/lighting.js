/*
 * lighting.js — day/night overlay (v3).
 *
 * Reads payload.time.phase ("DAY" | "DUSK" | "DAWN" | "NIGHT") and applies
 * matching CSS classes to:
 *   - #lighting   : radial-gradient overlay div inside .map-wrap
 *   - #mapWrap    : data-time attribute drives .windows + .lighthouse-beam
 *
 * Mapping:  DAY  -> ""     (no overlay)
 *           DUSK -> "dusk"
 *           DAWN -> "dusk"  (same warm radial)
 *           NIGHT-> "night"
 *
 * Continuous-alpha fallback: the existing #lighting rect (if any) is still
 * tinted by payload.lighting so non-CSS clients still degrade smoothly.
 *
 * Dream-mode class toggle on #world (or #mapWrap as fallback) when
 * payload.dreams.length > 0 — unchanged from v2.
 */
(function () {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";

  function classForPhase(phase) {
    const p = (phase || "DAY").toUpperCase();
    if (p === "NIGHT") return "night";
    if (p === "DUSK" || p === "DAWN") return "dusk";
    return "";
  }

  function applyPhase(payload) {
    const phase = (payload.time && payload.time.phase) || "DAY";
    const cls = classForPhase(phase);
    const wrap = document.getElementById("mapWrap");
    const lighting = document.getElementById("lighting");
    if (wrap) wrap.dataset.time = cls || "day";
    if (lighting) lighting.className = "lighting " + cls;

    // Continuous-alpha fallback. If #lighting is a <div>, we'll set an inline
    // background-color tint as well so non-CSS clients still see the gradient.
    if (lighting) {
      const a = alphaFor(payload.lighting);
      // Only paint the fallback tint when we're not relying on the .night/.dusk
      // class (so the cleaner CSS overlay wins).
      lighting.style.boxShadow = `inset 0 0 0 1000px rgba(10, 12, 40, ${a.toFixed(3)})`;
      lighting.style.opacity = cls ? "" : (a > 0 ? "1" : "0");
    }
  }

  function alphaFor(lighting) {
    const clamped = Math.max(0, Math.min(1, Number(lighting) || 0));
    return (1 - clamped) * 0.55;
  }

  // ---------------------------------------------------------- v2: dream overlay
  const dreamDialogs = new Map();

  function dreamHost() {
    return document.getElementById("world") || document.getElementById("mapWrap");
  }

  function renderDreamOverlay(payload) {
    const host = dreamHost();
    const overlays = document.getElementById("overlays");
    if (!host || !overlays) return;
    const dreams = Array.isArray(payload.dreams) ? payload.dreams : [];
    if (dreams.length === 0) {
      host.classList.remove("dream-mode");
      for (const [, g] of dreamDialogs) g.remove();
      dreamDialogs.clear();
      return;
    }
    host.classList.add("dream-mode");

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
      const ox = (pos.x || 0) + 12;
      const oy = (pos.y || 0) - 18;
      g.setAttribute("transform", `translate(${ox}, ${oy})`);
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
    for (const [id, g] of dreamDialogs) {
      if (!seen.has(id)) {
        g.remove();
        dreamDialogs.delete(id);
      }
    }
  }

  window.addEventListener("from:tick", (e) => {
    const payload = e.detail || {};
    applyPhase(payload);
    renderDreamOverlay(payload);
  });
})();
