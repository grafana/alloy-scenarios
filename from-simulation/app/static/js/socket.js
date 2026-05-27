/*
 * socket.js — connects to Flask-SocketIO and fans events out to
 * the map / lighting / UI updaters via the window event bus.
 *
 * Server -> client events the server emits (see contracts.SocketEvent):
 *   tick           — full snapshot_dict payload
 *   inspect_reply  — full agent record for a clicked dot
 *   cycle_reset    — village wipe overlay trigger
 *
 * Client -> server:
 *   inspect        — {id: "<agent_id>"}
 */
(function () {
  "use strict";

  const socket = io({
    transports: ["websocket", "polling"],
    reconnection: true,
  });

  // Expose for map.js so it can emit `inspect` on a dot click.
  window.FROM_SOCKET = socket;

  socket.on("connect", () => {
    console.log("[from-sim] socket connected", socket.id);
  });
  socket.on("disconnect", (reason) => {
    console.warn("[from-sim] socket disconnected:", reason);
  });
  socket.on("connect_error", (err) => {
    console.error("[from-sim] connect_error:", err && err.message);
  });

  socket.on("tick", (payload) => {
    if (!payload) return;
    window.dispatchEvent(new CustomEvent("from:tick", { detail: payload }));
  });

  socket.on("inspect_reply", (payload) => {
    window.dispatchEvent(
      new CustomEvent("from:inspect_reply", { detail: payload || {} })
    );
  });

  socket.on("cycle_reset", (payload) => {
    const cycle = (payload && payload.cycle) || "?";
    const overlay = document.getElementById("cycle-reset-overlay");
    const num = document.getElementById("cycle-reset-num");
    if (!overlay) return;
    if (num) num.textContent = String(cycle);
    overlay.classList.remove("hidden");
    setTimeout(() => overlay.classList.add("hidden"), 3000);
  });
})();
