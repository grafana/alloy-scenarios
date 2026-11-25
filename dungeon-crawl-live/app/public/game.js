const $ = (id) => document.getElementById(id);
const config = await (await fetch("/api/config")).json();
function sibling(port, path = "") {
  const url = new URL(location.origin);
  url.port = port;
  url.pathname = path;
  return url.href;
}
const { initializeFaro } = window.GrafanaFaroWebSdk;
const faro = initializeFaro({
  url: location.origin + "/collect",
  app: { name: "crawler-hud", version: "1.0", environment: "training" },
  dedupe: false,
});
const tiles = { guild: 1, toll: 6, gate: 9, stairs: 10 };
const scenarios = {
  baseline: "01 / 03",
  incident: "02 / 03",
  rollback: "03 / 03",
};
let game;
let operator = false;
let busy = false;
let buttons = [];
let notice = "";

async function api(path, method = "POST") {
  const response = await fetch("/api/" + path, { method });
  if (!response.ok)
    throw new Error(
      "The reward service is unavailable. Try that action again.",
    );
  return response.json();
}
function remember() {
  if (game) sessionStorage.setItem("crawl-" + game.id, JSON.stringify(game));
}
function identify() {
  faro.api.setPage({
    url: location.href,
    attributes: { run_id: game.id, release: game.release },
  });
}
function event(name, details = {}) {
  faro.api.pushEvent(name, details, "dungeon", { skipDedupe: true });
}
async function start(mode) {
  const run = await api("runs?mode=" + mode);
  const shiftStarted =
    mode === "baseline" ? run.started : (game?.shiftStarted ?? run.started);
  game = {
    ...run,
    shiftStarted,
    tile: run.earned ? tiles.guild : 3,
    hp: 3,
    stamina: 3,
    combat: false,
    distracted: false,
    claimed: false,
    usable: false,
    equipped: false,
    blocked: false,
    descended: false,
  };
  operator = false;
  history.replaceState(null, "", "?run=" + game.id);
  identify();
  event("floor_entered", { checkpoint: mode });
}
function move(tile) {
  if (!game || operator || game.descended || game.combat) return;
  game.tile = Math.max(
    0,
    Math.min(game.gateOpen ? 10 : 9, game.earned ? tile : Math.min(6, tile)),
  );
  notice = "";
}
function show(speaker, title, message, ...actions) {
  $("speaker").textContent = speaker;
  $("headline").textContent = title;
  $("message").textContent = notice || message;
  buttons = actions;
  for (const [i, id] of ["primary", "secondary"].entries()) {
    const button = $(id);
    button.hidden = !actions[i];
    button.disabled = busy;
    if (actions[i]) {
      button.textContent = actions[i][0];
      button.setAttribute("aria-label", actions[i][0]);
    }
  }
}
function cast() {
  $("spell").classList.remove("flash");
  void $("spell").offsetWidth;
  $("spell").classList.add("flash");
}
async function fight(action) {
  event("combat_action", { action });
  if (action === "distract") {
    game.distracted = true;
    notice =
      "Carl disputes the toll. The clerk climbs onto his stool to find the correct form. Donut has a clear shot.";
    return;
  }
  cast();
  game.hp = Math.max(0, game.hp - (game.distracted ? 3 : 1));
  if (game.hp === 0) {
    await api("runs/" + game.id + "/earn");
    game.combat = false;
    game.earned = true;
    event("mob_defeated", { mob: "goblin_toll_clerk" });
    return;
  }
  game.stamina--;
  notice =
    "The missile clips the ticket punch. The clerk stamps Carl for improper queueing. Try drawing his attention.";
}
function beginFight() {
  game.combat = true;
  event("mob_encountered", { mob: "goblin_toll_clerk" });
}
function renderInventoryItem(item) {
  // HUD 1.1 shipped with an assumption that every reward includes a thumbnail.
  if (game.release === "1.1") $("slot").title = item.thumbnail.alt;
  $("item").textContent = item.name;
  $("slot").textContent = "⚿";
  game.usable = true;
}
async function claim() {
  if (game.tile > 2) {
    notice =
      "The box stays sealed. Take it into the Tutorial Guildhall to open it.";
    event("safe_zone_required");
    return;
  }
  const since = performance.now();
  event("box_opened");
  const item = await api("runs/" + game.id + "/claim");
  game.claimed = true;
  try {
    renderInventoryItem(item);
  } catch (error) {
    // Isolate the broken slot so movement and other HUD controls keep working.
    faro.api.pushError(error, {
      context: { component: "inventory" },
      skipDedupe: true,
    });
    return;
  }
  event("key_usable");
  faro.api.pushMeasurement({
    type: "inventory_render",
    values: { duration_ms: performance.now() - since },
  });
}
function unlock() {
  if (!game.equipped) {
    game.blocked = true;
    event("unlock_blocked");
    return;
  }
  game.gateOpen = true;
  event("grille_opened");
}
function descend() {
  move(tiles.stairs);
  game.descended = true;
  event("floor_descended");
}
function investigate() {
  const dash = new URL(
    (config.grafana || sibling(config.grafanaPort)).replace(/\/$/, "") +
      "/d/missing-key/borant-duty-desk",
  );
  for (const [key, value] of Object.entries({
    "var-run": game.id,
    "var-game": location.origin,
    from: (game.shiftStarted || game.started) - 1000,
    to: "now",
  }))
    dash.searchParams.set(key, value);
  location.assign(dash);
}
function render() {
  const g = game;
  const tile = g?.tile ?? 3;
  const x = (n) => 7 + n * 8.55 + "%";
  $("carl").style.left = x(tile);
  $("donut").style.left = x(tile >= 9 ? tile + 0.45 : tile - 0.77);
  $("donut").style.bottom = tile <= 2 ? "40%" : "25%";
  $("scene").classList.toggle("won", Boolean(g?.earned));
  $("scene").classList.toggle("open", Boolean(g?.gateOpen));
  $("scene").classList.toggle("descended", Boolean(g?.descended));
  $("chapter").textContent = scenarios[g?.mode || "baseline"];
  $("location").textContent =
    tile <= 2
      ? "Tutorial Guildhall"
      : tile >= 8
        ? "Stairwell grille"
        : "Service passage";
  $("award").hidden = !g?.claimed || g.descended || operator;
  $("item").textContent = g?.equipped
    ? "Brass key · equipped"
    : g?.usable
      ? "Brass key"
      : g?.earned && !g.claimed
        ? "Crawler box"
        : "Empty slot";
  $("slot").textContent = g?.usable ? "⚿" : g?.earned && !g.claimed ? "▣" : "◇";
  $("combat").hidden = !g?.combat;
  if (g?.combat) {
    $("health").textContent =
      "TOLL CLERK " + g.hp + "/3   ·   CARL " + g.stamina + "/3";
    $("hp").value = g.hp;
  }
  for (const spot of $("spots").children) {
    spot.disabled = !g || g.combat || g.descended || operator || busy;
    spot.setAttribute("aria-current", Number(spot.dataset.tile) === tile);
  }
  if (!g)
    return show(
      "BORANT OPERATIONS",
      "On the air",
      "Earth’s survivors are live across the galaxy. Get Carl and Princess Donut past the toll clerk and down the stairs.",
      ["Enter the floor", () => start("baseline")],
    );
  if (operator)
    return show(
      "BORANT OPERATIONS",
      "Operator checkpoint",
      "Restore inventory display 1.0 and send the party through the guildhall again. The previous attempt stays in the duty log.",
      ["Roll back inventory display", () => start("rollback")],
      ["Review this attempt", investigate],
    );
  if (g.descended)
    return show(
      "DUNGEON AI",
      "Both crawlers through",
      "Carl holds the grille until Donut clears it. Two sets of footsteps disappear down the stairs.",
      g.mode === "baseline"
        ? ["Replay with HUD 1.1", () => start("incident")]
        : ["Verify recovery in Grafana", investigate],
      g.mode === "baseline"
        ? ["View healthy run", investigate]
        : ["Play from the beginning", () => start("baseline")],
    );
  if (g.combat)
    return show(
      "MOB ENCOUNTER",
      "Goblin toll clerk",
      g.distracted
        ? "The clerk is looking at Carl. Donut lines up her shot."
        : "A ticket punch snaps shut. Carl can keep the clerk busy while Donut aims, or she can cast immediately.",
      ["Cast Magic Missile", () => fight("missile")],
      ["Distract with Carl", () => fight("distract")],
    );
  if (g.gateOpen)
    return show(
      "CARL",
      "After you, Princess",
      "The brass key turns. Carl braces the grille with his shoulder. The blue stairwell is clear.",
      ["Descend together", descend],
    );
  if (tile >= 8 && g.blocked && g.claimed && !g.usable)
    return show(
      "PRINCESS DONUT",
      "An empty slot",
      "Donut slips a paw through the bars. She heard the reward announcement too. Carl tries the latch again. It doesn’t move.",
      ["Investigate this run", investigate],
      ["Try the grille again", unlock],
    );
  if (!g.earned && tile === tiles.toll)
    return show(
      "GOBLIN TOLL CLERK",
      "Exact change only",
      "The goblin taps his ticket punch against a crooked maintenance plaque. Behind him, the grille leads to the stairs.",
      ["Challenge the clerk", beginFight],
    );
  if (!g.earned)
    return show(
      "PRINCESS DONUT",
      "A toll on the stairs",
      "Donut spots a brass keyhole beyond the clerk. He slides a ticket under his cap and puts one hand on the grille.",
      ["Approach the toll booth", () => move(tiles.toll)],
    );
  if (tile >= 8)
    return show(
      "CARL",
      "Maintenance grille",
      "There is light on the other side of these bars. Carl tests the latch by hand.",
      [
        g.claimed || g.equipped ? "Unlock the grille" : "Return for the box",
        g.claimed || g.equipped ? unlock : () => move(tiles.guild),
      ],
      ["Return to guildhall", () => move(tiles.guild)],
    );
  if (g.equipped)
    return show(
      "CARL",
      "Key in hand",
      "One brass key, one matching lock. Donut takes point.",
      ["Approach the grille", () => move(tiles.gate)],
    );
  if (g.usable)
    return show(
      "MORDECAI",
      "Check the teeth",
      "The brass key settles into the inventory slot. Mordecai gestures for Carl to equip it before leaving.",
      [
        "Equip brass key",
        () => {
          g.equipped = true;
          event("key_equipped");
        },
      ],
    );
  if (tile <= 2 && g.claimed)
    return show(
      "DUNGEON AI",
      "Reward issued",
      "The award names a brass key. Carl looks down at the slot where the key should be. Beyond the counter, the grille is still shut.",
      ["Approach the grille", () => move(tiles.gate)],
      ["Reopen crawler box", claim],
    );
  if (tile <= 2)
    return show(
      "MORDECAI",
      "Inside the safe zone",
      "Mordecai clears a spot on the counter. Donut hops up for a better look. The floor clock keeps ticking.",
      ["Open crawler box", claim],
    );
  return show(
    "DUNGEON AI",
    "Toll evasion rewarded",
    "The goblin drops his punch and scuttles off. A crawler box appears in Carl’s awards. Only a safe zone lets him open it.",
    ["Enter the guildhall", () => move(tiles.guild)],
    ["Inspect crawler box", claim],
  );
}
async function act(action) {
  if (!action || busy) return;
  busy = true;
  notice = "";
  render();
  try {
    await action();
  } catch (error) {
    notice = error.message;
  } finally {
    busy = false;
    remember();
    render();
  }
}
$("primary").onclick = () => act(buttons[0]?.[1]);
$("secondary").onclick = () => act(buttons[1]?.[1]);
$("scene").onclick = (e) => {
  const bounds = $("scene").getBoundingClientRect();
  const tile =
    e.target.closest("[data-tile]")?.dataset.tile ??
    Math.round((((e.clientX - bounds.left) / bounds.width) * 100 - 7) / 8.55);
  act(() => move(Number(tile)));
};
window.addEventListener("keydown", (e) => {
  if (e.repeat || e.ctrlKey || e.metaKey || e.altKey) return;
  const key = e.key.toLowerCase();
  if (["arrowleft", "arrowright", "a", "d"].includes(key) && game) {
    e.preventDefault();
    act(() => move(game.tile + (["arrowleft", "a"].includes(key) ? -1 : 1)));
  } else if (key === "e") {
    e.preventDefault();
    act(buttons[0]?.[1]);
  }
});
const params = new URLSearchParams(location.search);
const savedId = params.get("operator") || params.get("run");
if (savedId && /^[a-f0-9-]{36}$/.test(savedId)) {
  try {
    const run = await api("runs/" + savedId, "GET");
    const saved = JSON.parse(sessionStorage.getItem("crawl-" + savedId));
    if (saved || params.has("operator")) {
      game = saved || { ...run, tile: 9, claimed: true, blocked: true };
      operator = params.has("operator");
      identify();
    }
  } catch {
    notice = "This checkpoint has expired. Start a fresh run below.";
  }
}
function tick() {
  const seconds = Math.max(
    0,
    4 * 86400 +
      17 * 3600 +
      32 * 60 -
      Math.floor((Date.now() - (game?.started ?? Date.now())) / 1000),
  );
  const hms = new Date(seconds * 1000).toISOString().slice(11, 19);
  $("clock").textContent = Math.floor(seconds / 86400) + "d " + hms;
}
setInterval(tick, 1000);
tick();
render();
