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

For a fresh local deployment using Docker Hardened Images for Grafana, Prometheus and Tempo, sign in with `docker login dhi.io`. With Compose 2.24.4 or later, run `docker compose -p wow-hardened -f docker-compose.yml -f docker-compose.coda.yml -f docker-compose.hardened.yml up -d` and use the same project and files when stopping. The separate Cloud collector only needs the public Alloy image.

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

## Record your own character

The **Alloy Route** addon records the character you're logged in as, anywhere in WoW Forever, at any level. It records level, XP, health, the active power type and amount, copper, and map position. It also records zone and level changes, NPC windows, and quest accepts and turn-ins. The game writes the recording to the character's SavedVariables file. A local reader turns that file into JSON Lines. Alloy can then ship them to Grafana Cloud. [`companion/FORMAT.md`](companion/FORMAT.md) documents every field.

1. Install the addon into the client and confirm the drive path:

   ```sh
   companion/install_addon.sh "/Volumes/T7/Blizzard/World of Warcraft/_forever_"
   ```

   On the character selection screen, open **AddOns** and enable **Alloy Route**. If it is listed as out of date, run `/dump select(4, GetBuildInfo())` in game and set `## Interface:` in `AlloyRoute.toc` to the printed number.

2. In game, enter `/alloyroute start`. The panel shows the row count, size and capacity. A snapshot is taken at the start and then every ten seconds whenever something changed, even while standing still. Speak to an NPC or hand in a quest to record an interaction. `/alloyroute status` prints usage; `/alloyroute stop` ends the session without reloading.
3. Click **Save & Reload**, type `/reload`, or log out normally. The game writes SavedVariables only at that point, so a crash loses the unsaved session. After a reload, `/alloyroute start` adds a new session to the same save.
4. Find the character's save and decode it on the Mac. This needs only Python 3.9 or later, with no Docker, network or credentials:

   ```sh
   companion/find_saves.sh
   mkdir -p captures
   python3 companion/read_recording.py "/Volumes/T7/Blizzard/World of Warcraft/_forever_/WTF/Account/<account>/<realm>/<character>/SavedVariables/AlloyRoute.lua" > captures/first-login.jsonl
   ```

   The reader prints one session object and then one event per line. It writes diagnostics and per-type counts to stderr. A truncated or unfinished file exits with status 2 and writes nothing.

5. After exporting, run `/alloyroute clear` and then `/alloyroute clear confirm` to free space. A character holds up to 4,096 rows or 1,000,000 bytes, about 11 hours of constant movement. The panel warns at 80% and stops recording when full.

`captures/` and `exports/` are git-ignored because decoded files contain real account, realm and character names.

### Send recordings to Grafana Cloud

[`cloud/config.alloy`](cloud/config.alloy) tails decoded files in `exports/` and pushes them to the stack's Loki endpoint. It keeps the in-game timestamp and uses `seq` to order rows within a second. `region`, `realm` and `character` become stream labels, and `type` and `session_id` become structured metadata.

1. Create a write-only access policy and token. Use a Grafana Cloud token that can read stacks and manage access policies, in `GCOM_TOKEN` or in `GRAFANA_CLOUD_TOKEN` as gcx uses:

   ```sh
   GCOM_TOKEN=... python3 cloud/create_access_policy.py --stack wow
   ```

   The script looks up the stack's Loki URL and user, creates `alloyroute-logs-write` with the `logs:write` scope on that stack only, creates a token and writes `cloud/.env` with mode 600. To set this up by hand instead, copy `cloud/.env.example` to `cloud/.env`. Then fill it in from the stack's Loki **Details** page and a token created under **Administration > Cloud access policies**.

2. Start Alloy and run the local reader. The reader checks the T7 every five seconds for character saves. It publishes one complete file per session into `exports/` and skips sessions it already exported.

   ```sh
   docker compose --project-name wow-route-cloud --env-file cloud/.env -f cloud/docker-compose.yml up -d
   python3 companion/watch_recordings.py
   ```

   For another installation, pass `--client "/path/to/_forever_"`. For a single checkpoint, run `python3 companion/read_recording.py "<path to AlloyRoute.lua>" --export-dir exports`. With the reader running, each **Save & Reload** or normal logout sends the newly saved sessions. Use `/alloyroute start` again after reloading to record the next session.

3. In Grafana Explore on the Loki data source, query `{service_name="wow-alloyroute"}`. For a level chart, use:

   ```logql
   max by (character, realm) (max_over_time({service_name="wow-alloyroute"} | type="snapshot" | json | unwrap level [5m]))
   ```

   Loki rejects lines older than the stack's maximum sample age, so export soon after playing.

The tracker's **My map routes** importer still reads v1 route files. It points v2 recordings to the reader instead.

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
