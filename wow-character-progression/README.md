# WoW Forever character progression

Track public World of Warcraft: Forever characters by region and full name. The web app records a baseline when you add a character, then polls Blizzard every 15 minutes. Grafana charts level, average item level, and completed achievements from the time tracking starts.

## Run locally

From this directory, start both the tracker and the observability stack:

```sh
docker compose -f docker-compose.yml -f docker-compose.coda.yml up -d --build
```

1. Open the [character roster](http://localhost:8095), enter the character’s first name and surname, choose the region, and select **Start tracking**. Public profiles generally appear after the first logout at level 10 or above.
2. Once the first sync completes, select **View history** on the character card. The [Grafana dashboard](http://localhost:3000/d/wow-progression/character-progression) also lets you select the region and character. Allow a minute or two for backend startup and the first telemetry batches.
3. Add other characters to the same roster. **Stop tracking** removes a character from the roster and ends polling for that character. Previously recorded telemetry remains available for the backends’ retention periods.

The tracker, Grafana, and [Alloy](http://localhost:12345) bind to localhost. Override `TRACKER_PORT`, `GRAFANA_PORT`, or `ALLOY_PORT` in a local `.env` file if those ports are in use. Use the same Compose files when stopping the stack:

```sh
docker compose -f docker-compose.yml -f docker-compose.coda.yml down
```

The roster, last observed values, and backend data use Docker volumes and survive ordinary restarts.

## Character data

By default the tracker reads the profile data embedded in the character’s achievements page on Blizzard’s public Armory. This mode needs no developer account. Profile changes become visible when Blizzard publishes a new snapshot, usually after logout. A missing average item level appears as a dash. A failed lookup shows the reason, keeps the timestamp of the last successful sync, and retries at the next scheduled poll.

To use the Battle.net Profile API, set `BLIZZARD_CLIENT_ID` and `BLIZZARD_CLIENT_SECRET` in a local `.env` file and rerun the startup command. The tracker obtains an application token, caches it until shortly before expiry, and requests the profile summary and achievements using the `profile-forever-{region}` namespace. Players enter only their character name and region in either mode. `POLL_SECONDS` controls the polling interval (default 900, minimum 60). [Battle.net developer portal](https://develop.battle.net/) · [Forever endpoint examples](https://mhuijskens.com/WoWForever/Api/)

## Follow a poll through Alloy

| Signal | What to look for in Grafana |
| --- | --- |
| Metrics · Prometheus | The dashboard charts `wow_character_level`, `wow_character_item_level`, and `wow_character_achievements`. Each series carries the character slug and region. |
| Logs · Loki | **Progression events** shows the first observation, individual changes with old and new values, and lookup failures or recoveries. Expand a line and select **Tempo** beside the trace field to open the poll that produced it. |
| Traces · Tempo | In Explore, search `{ resource.service.name = "wow-character-tracker" }`. A `character.poll` trace contains a child span for each Blizzard request. Unchanged profiles still produce a poll trace. |
| Profiles · Pyroscope | In Explore, select Pyroscope and the `wow-character-tracker` service. The flame graph samples the Python tracker, including time spent waiting on network and worker threads. Profiling starts with the first tracked character. |

The tracker sends metrics, logs, and traces to Alloy over OTLP/gRPC. Its Python profiling SDK sends profiles to Alloy’s Pyroscope receiver. Alloy forwards the four signals to their respective backends.

## Import a personal map route

1. Download **Alloy Route** from the roster and extract its folder into the Forever client’s `Interface/AddOns/` directory. Enable the addon on the character selection screen.
2. In game, enter `/alloyroute start`. The addon samples your character every ten seconds and on zone transitions. It records changed positions as percentages of the current map. A zone can have observations without coordinates, for example inside an instance.
3. Watch the in-game panel for the waypoint count, size, and capacity. It reminds you once at 500 waypoints or 100 kB, warns again at 80% of either limit, and stops recording when full. Click **Save & Reload** to finish and write the route to disk. If the panel stays open, type `/reload`. In **My map routes**, choose the character’s `WTF/Account/<account>/<realm>/<character>/SavedVariables/AlloyRoute.lua` and select **Import to Tempo**.
4. Open a zone visit from the result list. Each trace has the original visit times and its timestamped waypoint events. Reimporting the same file returns the existing trace links.
5. After importing, use `/alloyroute clear` to make space for the next recording. The addon keeps one bounded recording per character. Each reload or logout ends the active recording.

Route import works independently of the Armory roster and needs no Battle.net credentials.

## Simulated Forsaken journey

Open [Forsaken journey](http://localhost:8095/journey/dashboard) to see the latest run in Grafana, with the time picker set to its three hours of gameplay. The roster links to the same dashboard. Change the time range or drag across a chart to see the character, route and journal for part of a run. Each panel has its own editable data source query.

| Panels | Stored telemetry |
| --- | --- |
| Level, equipment, session totals, experience, health and mana | PromQL queries on twelve historical character gauges in Prometheus |
| Route, latest position and quest journal | LogQL queries on timestamped JSON records in Loki. Each position has zone coordinates and a trace ID. |
| Chapter traces | A TraceQL search in Tempo. Open a result to inspect its quest spans and timestamped position events. |

The tracker simulates Vesper Ashvale, an Undead priest, at 30-second intervals. It publishes one run every 24 hours and persists the run ID alongside the roster so routine tracker restarts reuse the same session. Alloy sends historical OpenTelemetry metrics to Prometheus’s OTLP receiver, logs to Loki and traces to Tempo. The **Simulated run** variable comes from Prometheus. The artwork is served as local XYZ tiles. The map’s trail and position are drawn from Loki.

**Animated replay** opens the optional custom atlas. Its playback controls use a local JSON timeline through Infinity. The editable dashboard’s gameplay panels query the telemetry backends. Route coordinates, rewards, stats and timestamps are simulated.

The opening follows [Wowhead’s Undead quest sequence](https://www.wowhead.com/classic/guide/quests/horde-reputation-quests-leveling). The journey carries the Scarlet documents to Brill, visits Solliden Farmstead and returns to Coleman Farthing after Agamand Mills. Quest entries link to their Forever database pages. [Vital Intelligence](https://www.wowhead.com/forever/quest=383/vital-intelligence) · [Fields of Grief](https://www.wowhead.com/forever/quest=365/fields-of-grief) · [The Haunted Mills](https://www.wowhead.com/forever/quest=362/the-haunted-mills).

Map artwork © Blizzard Entertainment, sourced from the [WoW Forever DB Tirisfal Glades map](https://wowfdb.com/zones/tirisfal-glades/map/).
