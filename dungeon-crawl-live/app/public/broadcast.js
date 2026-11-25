const $ = (id) => document.getElementById(id);
const cast = {
  carl: {
    name: "Carl",
    id: "4122",
    bio: "A former Coast Guard technician with bare feet and a talent for finding the least terrible exit.",
  },
  donut: {
    name: "Princess Donut",
    id: "4119",
    bio: "A champion tortoiseshell Persian, a spellcaster and Carl’s partner on the first floor.",
  },
};
const scenes = [
  {
    title: "Goblin motor pool",
    file: "goblins",
    type: "Goblin encounter",
    xy: [24, 29],
    alt: "A goblin crew steers a scrap-built dozer towards Carl and Donut.",
    carl: [
      "Carl hears the engine before the headlamps round the bend. He searches the tunnel wall for a doorway.",
      "The murder dozer scrapes sparks off the stone. Carl gathers Donut against his jacket and ducks into the recess.",
    ],
    donut: [
      "Donut’s ears flatten. A set of headlamps is bearing down on the tunnel, and her usual perch is moving rather quickly.",
      "From Carl’s shoulder she watches the goblin crew skid past. The side passage is clear.",
    ],
  },
  {
    title: "Scatterer tunnels",
    file: "scatterers",
    type: "Roach swarm",
    xy: [71, 23],
    alt: "Giant cockroaches scramble away from Donut’s magic in the drain gallery.",
    carl: [
      "Something moves inside a split refuse sack. Carl stops short as the first Scatterer skitters across his feet.",
      "The clicking gets louder behind the door. Carl edges forward while Donut covers the gap.",
    ],
    donut: [
      "The drain is alive with antennae. Donut picks out one moving shell, and a Magic Missile lights the passage blue.",
      "The roaches scatter between the cans. Donut shifts her aim toward the sound in the next room.",
    ],
  },
  {
    title: "The Hoarder",
    file: "hoarder",
    type: "The Hoarder · Level 7 boss",
    xy: [75, 70],
    alt: "In a room of discarded furniture, a crouching shell-armoured Hoarder faces Carl and Donut.",
    carl: [
      "The door seals. Beyond a toppled armchair, the Hoarder speaks Spanish. Carl hears a frightened woman asking for help.",
      "The broadcast marks her as a Level 7 neighbourhood boss. Carl keeps looking at her face as the Scatterers close in.",
    ],
    donut: [
      "Donut watches the Scatterers spill between the furniture. The woman behind them has drawn herself into a crouch.",
      "The music cuts out. Donut stays beside Carl while the control room waits to cut away.",
    ],
  },
  {
    title: "Tutorial Guild",
    file: "guild",
    type: "Safe zone",
    xy: [28, 72],
    alt: "Mordecai greets Carl and Donut at a lamplit guild counter.",
    carl: [
      "The feed cuts back to Mordecai’s Tutorial Guildhall. Carl shuts the door. The floor timer keeps counting in the safe zone.",
      "Carl leans against the counter and listens to the rat guildmaster. Outside, the next camera is picking up engine noise.",
    ],
    donut: [
      "Donut claims the best seat on Mordecai’s counter. For a moment the loudest sound is the lamp above her.",
      "While Carl talks to Mordecai, Donut surveys the room from the counter. The director cues another pass through the floor.",
    ],
  },
];
const beatMs = 5000;
const entry = new URLSearchParams(location.search);
let scene = Math.max(
  0,
  scenes.findIndex((shot) => shot.file === entry.get("camera")),
);
let beat = 0,
  lastBeat = Date.now(),
  paused = entry.get("pause") === "1";
let selected = Object.hasOwn(cast, entry.get("watch"))
    ? entry.get("watch")
    : null,
  journey = null,
  busy = false;
let version = localStorage.getItem("crawlcast-site") === "v2" ? "v2" : "v1";
let favourites = new Set();
const [config, initial] = await Promise.all(
  ["config", "favourites"].map(async (resource) => {
    const response = await fetch("/api/" + resource);
    if (!response.ok) throw new Error("Unable to load broadcast " + resource);
    return response.json();
  }),
);
favourites = new Set(initial.favourites);
const faro = window.GrafanaFaroWebSdk.initializeFaro({
  url: location.origin + "/collect",
  app: { name: "borant-broadcast", environment: "local" },
  dedupe: false,
});
function telemetry(name, extra = {}) {
  faro.api.pushEvent(
    name,
    {
      site_version: version,
      crawler: selected || "wide",
      scene: scenes[scene].file,
      ...extra,
    },
    "broadcast",
    { skipDedupe: true },
  );
}
function metadata() {
  faro.api.setPage({
    url: location.href,
    attributes: { site_version: version },
  });
}
function updateDashboard() {
  const origin = new URL(location.origin);
  origin.port = config.grafanaPort;
  const url = new URL(
    (config.grafana || origin.origin).replace(/\/$/, "") +
      "/d/crawlcast-audience/broadcast-control",
  );
  url.searchParams.set("var-session", faro.api.getSession()?.id || "");
  url.searchParams.set("from", "now-30m");
  url.searchParams.set("to", "now");
  $("dashboard").href = url;
}
function endJourney(reason) {
  if (journey)
    telemetry("favourite_abandoned", { journey: journey.id, reason });
  journey = null;
}
function message(text) {
  $("feedback").textContent = text;
}
function selectCrawler(key) {
  if (busy) return;
  if (selected !== key) endJourney("changed_crawler");
  selected = key;
  message("");
  telemetry("crawler_opened");
  render();
}
function tune(index, source) {
  scene = index;
  beat = 0;
  lastBeat = Date.now();
  telemetry("scene_tuned", { source });
  render();
}
function render() {
  const shot = scenes[scene];
  const seat = selected && cast[selected];
  $("scene-title").textContent = shot.title;
  $("still").src = "/art/" + shot.file + ".webp";
  $("still").alt = shot.alt;
  $("camera-no").textContent = "CAM / 0" + (scene + 1);
  $("cam-tag").textContent = seat
    ? "TRACKING · " + seat.name.toUpperCase()
    : "WIDE FEED";
  $("byline").textContent = seat
    ? shot.type.toUpperCase()
    : "FLOOR 01 · WIDE FEED";
  $("who").textContent = seat ? seat.name : "Tune in to a crawler";
  $("commentary").textContent = seat
    ? shot[selected][beat]
    : "Select Carl or Princess Donut on the map to follow their camera.";
  $("save").hidden = !seat;
  $("profile").hidden = !seat;
  if (seat) {
    const saved = favourites.has(seat.id);
    $("save").textContent = saved ? "★ Favourited" : "☆ Favourite " + seat.name;
    $("save").setAttribute("aria-pressed", saved);
    $("map-caption").textContent = "Tracking " + seat.name;
  }
  $("count").textContent = favourites.size;
  $("version").setAttribute("aria-checked", version === "v2");
  $("pause").textContent = paused ? "▶" : "Ⅱ";
  $("pause").setAttribute(
    "aria-label",
    paused ? "Resume broadcast" : "Pause broadcast",
  );
  for (const [key, offset] of [
    ["carl", -4],
    ["donut", 4],
  ]) {
    const pin = $("pin-" + key);
    pin.style.left = shot.xy[0] + offset + beat * 2 + "%";
    pin.style.top = shot.xy[1] + (key === "carl" ? -2 : 3) + beat + "%";
    pin.setAttribute("aria-pressed", selected === key);
  }
  for (const [i, button] of [...$("chapters").children].entries())
    button.setAttribute("aria-current", i === scene);
  for (const id of [
    "save",
    "profile",
    "version",
    "pin-carl",
    "pin-donut",
    "list-nav",
  ])
    $(id).disabled = busy;
}
function dialog(title) {
  $("drawer").classList.remove("screening");
  $("dialog-title").textContent = title;
  $("dialog-body").replaceChildren();
  if (!$("drawer").open) $("drawer").showModal();
  return $("dialog-body");
}
function action(text, className, handler) {
  const button = document.createElement("button");
  button.className = className;
  button.textContent = text;
  button.onclick = handler;
  return button;
}
function showProfile() {
  const seat = cast[selected],
    body = dialog(seat.name);
  const avatar = document.createElement("img");
  avatar.src = "/art/" + selected + ".webp";
  avatar.alt = "";
  avatar.className = "profile-img";
  const id = document.createElement("small");
  id.textContent = "CRAWLER " + Number(seat.id).toLocaleString("en-US");
  const bio = document.createElement("p");
  bio.textContent = seat.bio;
  body.append(
    avatar,
    id,
    bio,
    action(
      favourites.has(seat.id) ? "Remove favourite" : "Save favourite",
      "save",
      () => {
        $("drawer").close();
        save("profile");
      },
    ),
  );
  telemetry("profile_opened", journey ? { journey: journey.id } : {});
}
async function save(route) {
  if (busy || !selected) return;
  const seat = cast[selected],
    removing = favourites.has(seat.id);
  if (!removing && !journey) {
    journey = {
      id: Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) =>
        byte.toString(16).padStart(2, "0"),
      ).join(""),
      since: performance.now(),
    };
    telemetry("favourite_started", { journey: journey.id, route });
  }
  busy = true;
  render();
  message("");
  try {
    // The v2 quick card binds its public slug where the watchlist expects a crawler ID.
    const reference =
      version === "v2" && route === "quick" && !removing ? selected : seat.id;
    const response = await fetch("/api/favourites/" + reference, {
      method: removing ? "DELETE" : "PUT",
    });
    if (!response.ok) {
      const error = new Error(
        "Watchlist rejected " + reference + " (HTTP " + response.status + ")",
      );
      error.name = "FavouriteSaveError";
      throw error;
    }
    favourites = new Set((await response.json()).favourites);
    if (removing) {
      telemetry("favourite_removed");
      message(seat.name + " removed from favourites.");
    } else {
      const duration = Math.round(performance.now() - journey.since);
      telemetry("favourite_saved", {
        journey: journey.id,
        route,
        duration_ms: String(duration),
      });
      faro.api.pushMeasurement({
        type: "favourite_time",
        values: { duration_ms: duration },
        context: { site_version: version, route },
      });
      journey = null;
      message(seat.name + " added to favourites.");
    }
  } catch (error) {
    const context = {
      site_version: version,
      crawler: selected,
      route,
      journey: journey?.id || "",
    };
    faro.api.pushError(error, { context, skipDedupe: true });
    telemetry("favourite_failed", context);
    message(
      route === "quick" && !removing
        ? "Couldn’t save this crawler. Open the full profile to favourite them."
        : "Couldn’t update favourites. Please try again.",
    );
  } finally {
    busy = false;
    render();
  }
}
for (const [i, shot] of scenes.entries()) {
  const b = action("", "chapter", () => tune(i, "rundown"));
  b.setAttribute("aria-label", "Watch " + shot.title);
  const image = document.createElement("img");
  image.src = "/art/" + shot.file + ".webp";
  image.alt = "";
  const text = document.createElement("span"),
    label = document.createElement("small"),
    title = document.createElement("strong");
  label.textContent = "CAM 0" + (i + 1);
  title.textContent = shot.title;
  text.append(label, title);
  b.append(image, text);
  $("chapters").append(b);
}
for (const key of Object.keys(cast))
  $("pin-" + key).onclick = () => selectCrawler(key);
$("version").onclick = () => {
  endJourney("changed_version");
  version = version === "v1" ? "v2" : "v1";
  localStorage.setItem("crawlcast-site", version);
  metadata();
  telemetry("version_changed");
  message("Now watching on website " + version + ".");
  render();
};
$("save").onclick = () => save("quick");
$("profile").onclick = showProfile;
$("expand").onclick = () => {
  const shot = scenes[scene];
  const body = dialog(shot.title);
  $("drawer").classList.add("screening");
  const frame = document.createElement("img");
  frame.src = "/art/" + shot.file + ".webp";
  frame.alt = shot.alt;
  body.append(frame);
  if (selected) {
    const caption = document.createElement("p");
    caption.textContent = shot[selected][beat];
    body.append(caption);
  }
};

$("list-nav").onclick = () => {
  const body = dialog("Your favourites");
  if (!favourites.size) {
    const p = document.createElement("p");
    p.textContent =
      "Select a crawler on the floor map and favourite them to save their camera here.";
    body.append(p);
  }
  for (const [key, seat] of Object.entries(cast))
    if (favourites.has(seat.id))
      body.append(
        action("★   " + seat.name + "  →", "saved-row", () => {
          $("drawer").close();
          selectCrawler(key);
        }),
      );
};
$("map-nav").onclick = () => $("map").scrollIntoView({ block: "center" });
$("close").onclick = () => $("drawer").close();
$("pause").onclick = () => {
  paused = !paused;
  lastBeat = Date.now();
  render();
};
$("next").onclick = () => tune((scene + 1) % scenes.length, "next");
setInterval(() => {
  if (paused || document.hidden || Date.now() - lastBeat < beatMs) return;
  if (beat === 1) tune((scene + 1) % scenes.length, "director");
  else {
    beat = 1;
    lastBeat = Date.now();
    render();
  }
}, 250);
metadata();
telemetry("broadcast_opened");
if (selected) telemetry("crawler_opened");
updateDashboard();
$("dashboard").addEventListener("click", updateDashboard);
render();
