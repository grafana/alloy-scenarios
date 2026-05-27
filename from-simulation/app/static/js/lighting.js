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

  window.addEventListener("from:tick", (e) => {
    const payload = e.detail || {};
    const rect = ensureOverlay();
    if (rect) {
      const a = alphaFor(payload.lighting);
      rect.setAttribute("fill", `rgba(10, 12, 40, ${a.toFixed(3)})`);
    }
    const phase = (payload.time && payload.time.phase) || "DAY";
    updateLighthouseGlow(phase);
  });
})();
