# Azeroth Chronicle for WoW Forever

Record a character’s route, combat, quests, gear and armour as you play. The local **Azeroth Chronicle companion** reads the addon’s completed save and sends gameplay logs, session traces and summary metrics to your Grafana Cloud stack. Its simulator runs the same addon with sample game events. [Architecture and example payloads](ARCHITECTURE.md)

## Personal use and privacy

Azeroth Chronicle is an independent community project. Blizzard has not endorsed it or confirmed that using it is exempt from account action. The addon uses the in-game Lua API and WoW writes its per-character SavedVariables on reload or logout. The companion reads its own addon's save and exports character names, realm, character GUID, positions, equipment, combat boundaries quest objectives, loot receipts, NPC names, skill ranks and reputation to the destination you configure. Use your own recordings and a stack whose access you control. Anyone who can query the relevant data sources may see this history. Simulated mode lets you try the pipeline with a fictional character. [Blizzard’s add-on policy](https://eu.forums.blizzard.com/en/wow/t/wow-user-interface-add-on-development-policy/1642/1) · [Blizzard EULA](https://www.blizzard.com/en-gb/legal/08b946df-660a-40e4-a072-1fbde65173b1/blizzard-end-user-license-agreement)

## Run the companion

From this directory, start the companion with Python 3.9 or later and open the [local companion](http://127.0.0.1:8096).

```sh
python3 companion/watch_recordings.py
```

1. In **Settings**, choose your WoW client folder and how often to look for new saves. For Cloud delivery, start Docker and enter your stack URL, Loki push URL and instance ID, OpenTelemetry endpoint and instance ID, and their write tokens. Find the connection details on your stack’s Loki and OpenTelemetry tiles. The Loki token needs `logs:write`. The OpenTelemetry token needs `metrics:write` and `traces:write`. One stack-scoped token can cover all three.
2. Save the Cloud settings to start the collector. If you already have `cloud/.env`, choose **Start configured collector**. Alternatively, with a Cloud access-policy management token in `GCOM_TOKEN`, run `python3 cloud/create_access_policy.py --stack <stack-slug> --domain <stack-domain>` and then start the collector. Settings are stored locally. The UI keeps saved tokens out of its responses.
3. Choose **Real character** or **Simulated**. Both publish each completed recording into `exports/` and use the same collector. Files remain available locally when the collector is offline. Queued recordings go to the configured destination.
4. Install the **Journey** and **Progression** dashboards once on your stack. In the companion, expand a session in **Recent sessions** to open its dashboard at the recorded time, or choose **Open trace** for its gameplay timeline.

```sh
gcx dashboards create --context <your-context> --api-version dashboard.grafana.app/v1beta1 -f cloud/gear-dashboard.json
gcx dashboards create --context <your-context> --api-version dashboard.grafana.app/v1beta1 -f cloud/progression-dashboard.json
```

### Record your character

Install the addon, substituting the path to your Forever client.

```sh
companion/install_addon.sh "/Volumes/T7/Blizzard/World of Warcraft/_forever_"
```

Enable **Azeroth Chronicle** on the character selection screen. Click **Start recording** or type `/chronicle start` once per character. Drag the panel by its title to move it from the left edge. The addon records starting gear, equipment changes, effective armour, map position, level, XP, health, power and copper when available. It also records combat entry and exit, NPC windows, quest accepts and quest turn-ins. The quest record can include its title, ID, NPC and reported rewards. Combat tracking measures time your character was in combat during recording. The journal also records readable quest objectives, self-loot receipts, subzones, death and recovery, NPC targets, profession and skill ranks, and faction standing. Each reload starts a new baseline. The original `/alloyroute` command also works.

Click **Save & Reload**, type `/reload`, or log out normally to write the save. The companion can then export everything recorded since the last save, with the original event times. Recording resumes automatically after reload and at your next login. Characters with existing v2 recordings resume on upgrade. Use `/chronicle stop` to pause across reloads and logins. The addon warns at 80% and stops at 4,096 data rows or 1,000,000 bytes. **Clear…** unlocks after you click **Save & Reload** and WoW writes that character’s buffer. An ordinary logout or reload that adds a session locks Clear again. The same rule applies to the slash command. After checking delivery in the companion, choose **Clear…** and confirm to free the space used by previously saved sessions. The current session keeps recording. WoW persists the clear on the next reload or logout. [Save format and offline reader](companion/FORMAT.md)

### Character sheets and Battle.net portraits

Select a recorded character at the top of the journal to see their latest stats, observed gear and quests, map sketch, session ledger and dashboard links. Older saves can have fewer fields.

For an optional character portrait, add your Battle.net application client ID and secret in **Settings**. The companion reads the first name and surname from the character’s Forever save directory, automatically looks up the selected real character and retries unpublished media. The companion checks Blizzard’s returned character ID against the selected save. It loads the full-body rendered image or avatar from Blizzard’s render service. The companion stores credentials and the observed character names locally. The API supplies still images. A newly created character may need to reach level 10, log out and wait for Blizzard to publish media. [Forever character-media response](https://us.forums.blizzard.com/en/blizzard/t/wow-forever-api-what-works-so-far-plus-a-ts-client/60334/5)

### Try a simulated session

Install Lua 5.1 or LuaJIT, choose **Simulated**, select **Equipment changes** or **Forsaken journey**, and click **Generate recording**. The short example swaps a vest and changes armour. The three-hour example follows a fictional priest through combat, quest hand-ins and equipment changes in Tirisfal Glades. It runs immediately using a simulated game clock. The companion pauses its real-save watcher in this mode. Switching back to **Real character** picks up completed saves from the client folder.

### What you can see in Grafana

| Data source | What it shows |
| --- | --- |
| Loki | The original gameplay timeline, including starting gear, every observed swap and armour change, and the combat and quest journal. |
| Tempo | One trace per recording. Each zone visit, observed combat interval and accepted quest has a duration. Coordinates, gear changes and NPC interactions appear as timestamped events. |
| Cloud Metrics | One summary per export, including final character stats, starting/minimum/maximum armour, quest counts, entries into combat and observed combat seconds. This also works when a save contains hours of gameplay. |

Sessions made before version 2.1 lack gear history. Combat boundaries begin with 2.2. Version 2.4 adds objective, loot, exploration and progression readings. The latest-read card shows new and already-known sessions. Expand a session for its stats and delivery receipts. “Read by Alloy” means its file offset reached the end. Metrics and traces show when the local OTLP receiver acknowledged them. Open the dashboard to verify arrival in Cloud. Export soon after playing so game timestamps fall within the destination’s ingestion and retention windows.

## Optional local profile tracker

From this directory, start both the tracker and the observability stack:

```sh
docker compose -f docker-compose.yml -f docker-compose.coda.yml up -d --build
```

1. For live profiles, set `BLIZZARD_CLIENT_ID` and `BLIZZARD_CLIENT_SECRET` in a local `.env` file and rerun the startup command. The simulated journey and addon reader work without these credentials. Open the [character roster](http://localhost:8095), enter the character’s first name and surname, choose the region, and select **Start tracking**. Public profiles generally appear after the first logout at level 10 or above.
2. Once the first sync completes, select **View history** on the character card. The [Grafana dashboard](http://localhost:3000/d/wow-progression/character-progression) also lets you select the region and character. Allow a minute or two for backend startup and the first telemetry batches.
3. Add other characters to the same roster. **Stop tracking** removes a character from the roster and ends polling for that character. Previously recorded telemetry remains available for the backends’ retention periods.

The tracker, Grafana, and [Alloy](http://localhost:12345) bind to localhost. Override `TRACKER_PORT`, `GRAFANA_PORT`, or `ALLOY_PORT` in a local `.env` file if those ports are in use. Use the same Compose files when stopping the stack:

```sh
docker compose -f docker-compose.yml -f docker-compose.coda.yml down
```

For a fresh local deployment using Docker Hardened Images for Grafana, Prometheus and Tempo, sign in with `docker login dhi.io`. With Compose 2.24.4 or later, run `docker compose -p wow-hardened -f docker-compose.yml -f docker-compose.coda.yml -f docker-compose.hardened.yml up -d` and use the same project and files when stopping. The separate Cloud collector uses public Alloy and Python base images.

The roster, last observed values, and backend data use Docker volumes and survive ordinary restarts.

## Character data

The tracker uses the Battle.net Profile API for live profile lookups. It caches an application token until shortly before expiry and requests the profile summary and achievements from the regional Forever namespace. A missing item level appears as a dash. A failed lookup preserves the last successful sync time and retries at the next scheduled poll. `POLL_SECONDS` controls the polling interval (default 900, minimum 60). [Battle.net developer portal](https://develop.battle.net/) · [Forever endpoint examples](https://mhuijskens.com/WoWForever/Api/)

## Follow a poll through Alloy

| Signal | What to look for in Grafana |
| --- | --- |
| Metrics · Prometheus | The dashboard charts `wow_character_level`, `wow_character_item_level`, and `wow_character_achievements`. Each series carries the character slug and region. |
| Logs · Loki | **Progression events** shows the first observation, individual changes with old and new values, and lookup failures or recoveries. Expand a line and select **Tempo** beside the trace field to open the poll that produced it. |
| Traces · Tempo | In Explore, search `{ resource.service.name = "wow-character-tracker" }`. A `character.poll` trace contains a child span for each Blizzard request. Unchanged profiles still produce a poll trace. |
| Profiles · Pyroscope | In Explore, select Pyroscope and the `wow-character-tracker` service. The flame graph samples the Python tracker, including time spent waiting on network and worker threads. Profiling starts with the first tracked character. |

The tracker sends metrics, logs, and traces to Alloy over OTLP/gRPC. Its Python profiling SDK sends profiles to Alloy’s Pyroscope receiver. Alloy forwards the four signals to their respective backends.

## Optional local Forsaken atlas

Generate the three-hour journey in the companion, then open the [local journey dashboard](http://localhost:8095/journey/dashboard) with the optional stack running. The companion also writes an illustrative replay for this local dashboard. It shows a map, chapter traces and a quest journal. Its synthetic kill counts and rewards belong to the example. The route follows quests in Deathknell, Brill, Solliden Farmstead and Agamand Mills. [Wowhead quest sequence](https://www.wowhead.com/classic/guide/quests/horde-reputation-quests-leveling)
