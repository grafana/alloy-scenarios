# Capture a WoW Forever session on the T7

Extend **AlloyRoute** to record the character who is actually logged in, anywhere in WoW Forever. The deliverable for this phase is a game-written SavedVariables file and a local command that decodes it into readable events. Stop once the capture has been verified. Grafana dashboards, telemetry export and an always-running file watcher are later work.

## 1. Start with the existing recorder

Work in `wow-character-progression/`. Read `app/addon/AlloyRoute/AlloyRoute.lua`, its sibling `AlloyRoute.toc`, and the v1 parser in `app/routes.py`. The addon already samples movement every ten seconds, handles zone changes, shows a capacity warning and provides a **Save & Reload** button. Reuse those pieces.

The inspected client is **1.60.1.71139** in `/Volumes/T7/Blizzard/World of Warcraft/_forever_/`. Its `Interface` and `WTF` folders were absent at inspection. Let WoW create its account and character save folders. Use the interface and event signatures for the installed build. [Build 71139 UI source](https://github.com/Gethe/wow-ui-source/tree/d9c22e32cb240afb82bb2ecefbb78ef935333f59/Interface/AddOns/Blizzard_APIDocumentationGenerated)

## 2. Capture the minimum useful dataset

| When | What to record |
| --- | --- |
| Recording starts | Format version, session ID, server time, client build, region, realm and character name. Read race, class and faction from the player when available. A character can start recording at any level. |
| Initial snapshot, then every ten seconds | Level, current XP and XP maximum, health and maximum health, active power type and current/maximum amount, and money in copper. Capture map ID, zone and map-local x/y together. A stationary character can still gain XP or spend money. |
| Zone or level changes | Timestamp the transition and take a fresh snapshot. Keep a zone change even when coordinates are unavailable, such as inside an instance. |
| The player interacts with an NPC or quest | Record the observed interaction type and readable NPC name. For quest acceptance or turn-in, record the quest ID and title when available. Keep a turn-in’s reward separate from measured character XP. |

Use server timestamps and a sequence number to order events within the same second. Read the active power type each time so mana, rage, energy and form changes are represented correctly. Preserve a real zero. Omit unavailable or restricted values. Store coordinates with their original map ID and the existing integer scale of 0–10000 per axis. Artwork, zone names, quest lists and simulator data are unnecessary for capture.

On build 71139, the first `QUEST_ACCEPTED` argument is the quest ID. `QUEST_TURNED_IN` includes the ID, XP reward and money reward. `GOSSIP_SHOW` can supply a texture kit. Read the NPC identity from the available interaction unit. Cover direct quest-giver windows and deduplicate overlapping UI events. [Quest events](https://github.com/Gethe/wow-ui-source/blob/d9c22e32cb240afb82bb2ecefbb78ef935333f59/Interface/AddOns/Blizzard_APIDocumentationGenerated/QuestLogDocumentation.lua) · [Gossip events](https://github.com/Gethe/wow-ui-source/blob/d9c22e32cb240afb82bb2ecefbb78ef935333f59/Interface/AddOns/Blizzard_APIDocumentationGenerated/GossipInfoDocumentation.lua)

## 3. Save and read one character’s recording

1. Keep `AlloyRouteRecording` per character. Define a v2 header, typed rows and a footer with end time and row count. Document field order, units and encoding beside an example fixture. Keep the existing v1 route import working.
2. Buffer rows in memory and maintain an incremental byte count. Preserve the 4,096-row and 1,000,000-byte limits. Reserve room for the footer before appending. Show usage and the existing warning; keep the checkpoint player-initiated. A reload or normal logout finalizes the segment. Protect an unexported recording from being overwritten by a new start.
3. Provide a local reader, for example `python3 companion/read_recording.py "/path/to/SavedVariables/AlloyRoute.lua"`. Parse the saved assignment as data and emit one JSON object per line. Include character/session identity on each event or an explicit session header. Write diagnostics to stderr. This command should run on the Mac without Docker, credentials or a network connection. A truncated file should return an error and produce no partial export.

## 4. Verify offline, then on the first login

**Offline checks.** Use two fixtures with different races, classes, realms and starting maps. Include a shared character name across realms, a non-mana resource, a missing map position, a legitimate zero and an XP change while stationary. Verify the reader preserves these differences. Simulate three hours of ten-second ticks in the addon harness and check the output size, warning and footer. Report fixture results as offline evidence.

**First-login check.** During implementation, install the addon files directly under `/Volumes/T7/Blizzard/World of Warcraft/_forever_/Interface/AddOns/AlloyRoute/`. The player can create or select any character, enable the addon and enter `/alloyroute start`. Walk far enough for two distinct samples, note the displayed level, and speak to an NPC if one is nearby. Click **Save & Reload** or log out normally. Find the new save with:

```sh
find '/Volumes/T7/Blizzard/World of Warcraft/_forever_/WTF/Account' \
  -path '*/SavedVariables/AlloyRoute.lua' -type f
```

Pass the character-scoped file to the reader and save its JSON output before clearing the recording. Verify the decoded identity, level, zone and positions against that session. If an NPC conversation or quest occurred, check its record as well. A character without an available quest can still complete the basic capture check.

**Completion evidence.** Report the real save path, decoded event counts by type, and a few representative rows from that session. Until the player logs in and writes a checkpoint, report real-client capture as pending.
