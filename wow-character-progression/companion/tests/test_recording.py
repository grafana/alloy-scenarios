"""Offline checks for the AlloyRoute v2 addon and its reader.

    python3 -m unittest discover -s companion/tests -v

The addon runs in a Lua 5.1 harness (`lua5.1` on Linux,
`brew install luajit` on a Mac). Reader-only tests run without Lua.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMPANION = HERE.parent
ADDON = COMPANION.parent / "app" / "addon" / "AlloyRoute" / "AlloyRoute.lua"
FIXTURES = COMPANION / "fixtures"
sys.path.insert(0, str(COMPANION))

import read_recording  # noqa: E402

LUA = shutil.which("lua5.1") or shutil.which("luajit") or shutil.which("lua")
needs_lua = unittest.skipUnless(LUA, "Lua 5.1 is not installed")


def harness(scenario_path, output):
    subprocess.run([LUA, str(COMPANION / "simulation" / "harness.lua"), str(ADDON), str(scenario_path), str(output)],
                   check=True, capture_output=True, text=True)
    return Path(output).read_text(), Path(str(output) + ".messages").read_text()


def read(path):
    result = subprocess.run([sys.executable, str(COMPANION / "read_recording.py"), str(path)],
                            capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def events(text):
    return [json.loads(line) for line in text.splitlines()]


CHARACTER = """
H.character({
    regionId = 3, realm = "Stonewake", name = "Morrow", guid = "Player-1001-0A1B2C3D",
    raceName = "Undead", raceFile = "Scourge", raceId = 5, className = "Warrior",
    classFile = "WARRIOR", classId = 1, faction = "Horde",
    level = 10, xp = 0, xpMax = 7600, hp = 300, hpMax = 300,
    powerType = 1, powerToken = "RAGE", power = 0, powerMax = 100, money = 0,
    map = 1420, zone = %s, x = 0.1, y = 0.1,
})
local S = H.state
"""


class Workspace(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def run_scenario(self, body, zone='"Tirisfal Glades"'):
        scenario = self.tmp / "scenario.lua"
        scenario.write_text(CHARACTER % zone + body)
        saved, messages = harness(scenario, self.tmp / "AlloyRoute.lua")
        return saved, messages


@needs_lua
class FixtureTests(Workspace):
    def test_equipped_slots_swaps_and_effective_armor(self):
        path = self.tmp / "gear.lua"
        harness(COMPANION / "simulation" / "gear.lua", path)
        _, rows = read_recording.read_file(path)
        start = [r for r in rows if r["type"] == "gear_start"]
        self.assertEqual(len({r["slot"] for r in start}), 19)
        self.assertEqual(next(r["item_name"] for r in start if r["slot"] == "Chest"), "Training Vest")
        self.assertEqual(sum(r["item_id"] == 0 for r in start), 18)
        swaps = [(r["ts"] - start[0]["ts"], r["previous_item_name"], r["item_name"])
                 for r in rows if r["type"] == "gear_swap"]
        self.assertEqual(swaps, [(60, "Training Vest", "Reinforced Vest"), (180, "Reinforced Vest", "Empty")])
        self.assertEqual([r["armor"] for r in rows if r["type"] == "armor"], [42, 55, 60, 20, 20])

    def test_fixtures_match_the_addon(self):
        # The committed fixtures are what the current addon writes for each scenario.
        for name in ("undead_warrior", "night_elf_druid"):
            saved, _ = harness(HERE / "scenarios" / f"{name}.lua", self.tmp / f"{name}.lua")
            self.assertEqual(saved, (FIXTURES / f"{name}.lua").read_text(), name)
            code, out, err = read(self.tmp / f"{name}.lua")
            self.assertEqual(code, 0, err)
            self.assertEqual(out, (FIXTURES / f"{name}.jsonl").read_text(), name)


class FixtureContentTests(unittest.TestCase):
    def load(self, name):
        sessions, rows = read_recording.read_file(FIXTURES / f"{name}.lua")
        return sessions, rows

    def test_forever_empty_realm_uses_player_realm_id(self):
        fixture = read_recording.saved_variables((FIXTURES / "undead_warrior.lua").read_text())
        recording = fixture["AlloyRouteRecording"].replace("|Stonewake|", "||")
        sessions, rows = read_recording.decode(recording)
        self.assertTrue(all(s["realm"] == "Realm-1001" for s in sessions + rows))
        with self.assertRaisesRegex(read_recording.RecordingError, "no realm"):
            read_recording.decode(recording.replace("Player-1001-0A1B2C3D", "Unknown"))

    def test_identity_is_kept_apart(self):
        a, _ = self.load("undead_warrior")
        b, _ = self.load("night_elf_druid")
        self.assertEqual(a[0]["character"], b[0]["character"])  # same name, different realms
        for key in ("realm", "region", "race", "class", "faction", "player_guid", "session_id"):
            self.assertNotEqual(a[0][key], b[0][key], key)
        self.assertEqual(len(b), 2, "the druid save holds two sessions")
        self.assertEqual(a[0]["client_build"], "1.60.1.71139")

    def test_starting_maps_and_resources_differ(self):
        _, a = self.load("undead_warrior")
        _, b = self.load("night_elf_druid")
        snap_a = [e for e in a if e["type"] == "snapshot"]
        snap_b = [e for e in b if e["type"] == "snapshot"]
        self.assertEqual((snap_a[0]["map_id"], snap_a[0]["zone"]), (1420, "Tirisfal Glades"))
        self.assertEqual((snap_b[0]["map_id"], snap_b[0]["zone"]), (1438, "Teldrassil"))
        self.assertEqual(snap_a[0]["power_type"], "RAGE")
        self.assertEqual({e["power_type"] for e in snap_b}, {"MANA", "ENERGY"})

    def test_real_zeros_are_kept(self):
        _, a = self.load("undead_warrior")
        first = a[0]
        self.assertEqual((first["power"], first["money_copper"]), (0, 0))
        _, b = self.load("night_elf_druid")
        self.assertEqual(b[0]["xp"], 0)

    def test_restricted_values_are_omitted(self):
        _, b = self.load("night_elf_druid")
        combat = [e for e in b if e["type"] == "snapshot" and e.get("power") == 40]
        self.assertEqual(len(combat), 1)
        self.assertNotIn("health", combat[0])
        self.assertNotIn("health_max", combat[0])

    def test_missing_position_keeps_zone(self):
        _, a = self.load("undead_warrior")
        instance = [e for e in a if e.get("map_id") == 279]
        self.assertTrue(any(e["type"] == "zone_change" for e in instance))
        for event in instance:
            self.assertEqual(event["zone"], "The Deadmines")
            self.assertNotIn("x", event)

    def test_stationary_xp_change(self):
        _, a = self.load("undead_warrior")
        snaps = [e for e in a if e["type"] == "snapshot"]
        pairs = list(zip(snaps, snaps[1:]))
        self.assertTrue(any(p["x"] == n["x"] and p["y"] == n["y"] and p["xp"] != n["xp"]
                            for p, n in pairs if "x" in p and "x" in n))

    def test_interactions_and_quests(self):
        _, a = self.load("undead_warrior")
        kinds = [e["type"] for e in a]
        self.assertEqual(kinds.count("quest_accepted"), 1, "duplicate QUEST_ACCEPTED is dropped")
        self.assertEqual(kinds.count("interaction"), 2, "one row per NPC window opening")
        gossip = next(e for e in a if e["type"] == "interaction")
        self.assertEqual((gossip["interaction"], gossip["npc_name"], gossip["npc_id"]),
                         ("Gossip", "Executor Arren", 1570))
        turn_in = next(e for e in a if e["type"] == "quest_turned_in")
        self.assertEqual((turn_in["quest_id"], turn_in["quest_title"]), (364, "The Mindless Ones"))
        self.assertEqual((turn_in["reward_xp"], turn_in["reward_copper"]), (250, 35))
        self.assertNotIn("xp", turn_in, "rewards stay separate from measured XP")
        level = next(e for e in a if e["type"] == "level_up")
        after = [e for e in a if e["type"] == "snapshot" and e["seq"] > level["seq"]]
        self.assertEqual(after[0]["level"], 5)

    def test_every_event_carries_identity_and_order(self):
        for name in ("undead_warrior", "night_elf_druid"):
            _, rows = self.load(name)
            for event in rows:
                for key in ("session_id", "region", "realm", "character", "player_guid", "ts", "seq"):
                    self.assertIn(key, event)
            for prev, nxt in zip(rows, rows[1:]):
                if prev["session_id"] == nxt["session_id"]:
                    self.assertEqual(nxt["seq"], prev["seq"] + 1)
                    self.assertLessEqual(prev["ts"], nxt["ts"])
                    self.assertLess(int(prev["ts_ns"]), int(nxt["ts_ns"]))


class DamagedFileTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.good = (FIXTURES / "undead_warrior.lua").read_text()

    def check_rejected(self, text, message):
        path = self.tmp / "AlloyRoute.lua"
        path.write_text(text)
        out_file = self.tmp / "out.jsonl"
        result = subprocess.run([sys.executable, str(COMPANION / "read_recording.py"), str(path),
                                 "-o", str(out_file)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn(message, result.stderr)
        self.assertFalse(out_file.exists(), "no partial export")
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["AlloyRoute.lua"])

    def test_truncated_file(self):
        self.check_rejected(self.good[: len(self.good) // 2], "truncated")

    def test_missing_footer(self):
        cut = self.good.rindex(";e|")
        self.check_rejected(self.good[:cut] + '"\n', "no footer")

    def test_footer_count_mismatch(self):
        text = self.good.replace("|22\"", "|21\"")
        self.assertNotEqual(text, self.good)
        self.check_rejected(text, "footer lists 21 rows")

    def test_dropped_row(self):
        start = self.good.index(";s|1790000020|")
        end = self.good.index(";", start + 1)
        self.check_rejected(self.good[:start] + self.good[end:], "out of order")

    def test_v1_route(self):
        self.check_rejected('AlloyRouteRecording = "v1|eu|Morrow|1790000000;end|1790000100"\n', "v1 route")

    def test_no_recording(self):
        self.check_rejected("AlloyRouteRecording = nil\n", "No AlloyRouteRecording")

    def test_lua_is_never_executed(self):
        self.check_rejected('AlloyRouteRecording = os.execute("echo hi")\n', "Unexpected")

    def test_other_saved_variables_are_ignored(self):
        path = self.tmp / "AlloyRoute.lua"
        path.write_text('AlloyRouteSettings = {\n\t["auto"] = true,\n\t[1] = 2.5, -- [1]\n}\n' + self.good)
        sessions, rows = read_recording.read_file(path)
        self.assertEqual(len(rows), 22)

    def test_incremental_exports_keep_the_first_file_and_tail_offset(self):
        sessions, events = read_recording.read_file(FIXTURES / "night_elf_druid.lua")
        output = self.tmp / "exports"
        read_recording.write_sessions(output, sessions[:1], events[:sessions[0]["rows"]])
        first, = output.glob("*.jsonl")
        inode, stamp = first.stat().st_ino, first.stat().st_mtime_ns
        read_recording.write_sessions(output, sessions, events)
        read_recording.write_sessions(output, sessions, events)
        self.assertEqual((first.stat().st_ino, first.stat().st_mtime_ns), (inode, stamp))
        files = list(output.glob("*.jsonl"))
        self.assertEqual(len(files), 2)
        for path in files:
            records = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(len(records), 1 + records[0]["rows"])
            self.assertEqual(len({row["session_id"] for row in records}), 1)

    def test_output_is_atomic(self):
        path = self.tmp / "AlloyRoute.lua"
        path.write_text(self.good)
        out_file = self.tmp / "out.jsonl"
        code = read_recording.main([str(path), "-o", str(out_file)])
        self.assertEqual(code, 0)
        self.assertEqual(len(out_file.read_text().splitlines()), 23)
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["AlloyRoute.lua", "out.jsonl"])


@needs_lua
class CapacityTests(Workspace):
    def test_three_hour_session(self):
        saved, messages = self.run_scenario("""
H.slash("start")
local tick = 0
H.advance(3 * 3600, function()
    tick = tick + 1
    if tick %% 10 == 0 then S.x = 0.1 + (tick %% 7000) / 10000 end
    if tick %% 60 == 0 then S.xp = S.xp + 7 end
end)
H.click()
H.reload()
""".replace("%%", "%"))
        path = self.tmp / "AlloyRoute.lua"
        sessions, rows = read_recording.read_file(path)
        self.assertEqual(sessions[0]["duration_seconds"], 3 * 3600)
        self.assertEqual(len(rows), sessions[0]["rows"])
        self.assertGreaterEqual(len(rows), 1080)
        self.assertLess(len(rows), 1090)
        recording = read_recording.saved_variables(saved)["AlloyRouteRecording"]
        self.assertLess(len(recording), 200_000)
        self.assertIn("sizeable recording", messages)
        self.assertNotIn("80% full", messages)
        self.assertNotIn("Recording full", messages)
        self.assertRegex(recording, r";e\|\d+\|%d$" % len(rows))
        print(f"\n  3-hour session: {len(rows)} rows, {len(recording):,} bytes saved", file=sys.stderr)

    def test_row_limit_stops_and_closes(self):
        saved, messages = self.run_scenario("""
H.slash("start")
H.advance(4200 * 10, function() S.x = (H.now %% 20 < 10) and 0.1 or 0.2 end)
H.reload()
""".replace("%%", "%"))
        sessions, rows = read_recording.read_file(self.tmp / "AlloyRoute.lua")
        self.assertEqual(len(rows), 4096)
        self.assertIn("80% full", messages)
        self.assertIn("Recording full", messages)

    def test_byte_limit_stops_and_closes(self):
        long_zone = '"' + "Ẑ" * 190 + '"'  # 3 UTF-8 bytes each, 9 after percent-encoding
        saved, messages = self.run_scenario("""
H.slash("start")
H.advance(4000 * 10, function() S.x = (H.now %% 20 < 10) and 0.1 or 0.2 end)
H.reload()
H.slash("start")
""".replace("%%", "%"), zone=long_zone)
        recording = read_recording.saved_variables(saved)["AlloyRouteRecording"]
        self.assertLessEqual(len(recording.encode()), read_recording.MAX_BYTES)
        self.assertGreater(len(recording.encode()), read_recording.MAX_BYTES - 4000)
        sessions, rows = read_recording.read_file(self.tmp / "AlloyRoute.lua")
        self.assertLess(len(rows), 4096)
        self.assertIn("Recording full", messages)
        self.assertIn("recording is full. Export it", messages)


@needs_lua
class SafetyTests(Workspace):
    def test_new_start_appends_and_clear_needs_confirmation(self):
        saved, messages = self.run_scenario("""
H.slash("start")
H.advance(20, function() S.x = S.x + 0.001 end)
H.reload()
H.slash("clear")
H.slash("start")
H.advance(20, function() S.x = S.x + 0.001 end)
H.slash("stop")
H.slash("clear")
H.logout()
""")
        sessions, _ = read_recording.read_file(self.tmp / "AlloyRoute.lua")
        self.assertEqual(len(sessions), 2, "the earlier session survives a new start")
        self.assertIn("type /chronicle clear confirm", messages)

    def test_panel_position_survives_reload(self):
        self.run_scenario("""
            local function panel()
                for _, frame in ipairs(H.frames) do
                    if frame.scripts.OnDragStop then return frame end
                end
            end
            function UIParent:GetWidth() return 1200 end
            function UIParent:GetHeight() return 800 end
            local frame = panel()
            assert(frame.point[1] == "LEFT" and frame.point[4] == 12)
            function frame:GetLeft() return 300 end
            function frame:GetBottom() return 400 end
            frame.scripts.OnDragStop(frame)
            H.load()
            local point = panel().point
            assert(point[1] == "BOTTOMLEFT" and point[4] == 300 and point[5] == 400)
            H.logout()
        """)

    def test_clear_button_preserves_active_session_and_recording_resumes(self):
        self.run_scenario("""
            H.slash("start")
            H.advance(5)
            assert(not H.click("Clear…"))
            H.reload()
            local prior = AlloyRouteRecording
            assert(H.click("Clear…") and H.popup and AlloyRouteRecording == prior)
            H.popup = nil -- dismiss as Cancel or Escape
            assert(AlloyRouteRecording == prior)
            H.advance(5)
            assert(H.click("Clear…"))
            H.popup.OnAccept()
            assert(AlloyRouteRecording == nil)
            H.advance(15)
            H.logout()
        """)
        sessions, rows = read_recording.read_file(self.tmp / "AlloyRoute.lua")
        self.assertEqual([s["duration_seconds"] for s in sessions], [20])
        self.assertGreater(len(rows), 0)

    def test_explicit_pause_and_login_resume_after_upgrade(self):
        self.run_scenario("""
            H.slash("start")
            H.advance(6)
            H.logout()
            AlloyRouteAutoRecord = nil -- upgrade from v2.2
            H.load()
            H.fire("PLAYER_ENTERING_WORLD", true, false)
            H.advance(11)
            H.slash("stop")
            H.reload()
            H.advance(12)
            assert(H.click("Start recording"))
            H.advance(7)
            H.logout()
        """)
        sessions, _ = read_recording.read_file(self.tmp / "AlloyRoute.lua")
        self.assertEqual([s["duration_seconds"] for s in sessions], [6, 11, 7])

    def test_clear_confirm_removes_recording(self):
        saved, messages = self.run_scenario("""
H.slash("start")
H.advance(20)
H.slash("stop")
H.reload()
H.slash("clear confirm")
H.logout()
""")
        self.assertIn("AlloyRouteRecording = nil", saved)

    def test_v1_route_blocks_start(self):
        saved, messages = self.run_scenario("""
AlloyRouteRecording = "v1|eu|Morrow|1790000000;1790000010|1420|Tirisfal%20Glades|1000|1000;end|1790000020"
H.load()
H.slash("start")
H.logout()
""")
        self.assertIn("older v1 route", messages)
        self.assertIn('"v1|eu|Morrow', saved)

    def test_reload_without_click_saves(self):
        saved, _ = self.run_scenario("""
H.slash("start")
H.advance(30, function() S.y = S.y + 0.001 end)
H.reload()
""")
        sessions, rows = read_recording.read_file(self.tmp / "AlloyRoute.lua")
        self.assertEqual(len(sessions), 1)
        self.assertGreaterEqual(len(rows), 3)

    def test_crash_before_logout_keeps_previous_save(self):
        # SavedVariables are only written at logout. Without PLAYER_LOGOUT nothing changes.
        saved, _ = self.run_scenario("""
H.slash("start")
H.advance(30)
""")
        self.assertIn("AlloyRouteRecording = nil", saved)


if __name__ == "__main__":
    unittest.main()
