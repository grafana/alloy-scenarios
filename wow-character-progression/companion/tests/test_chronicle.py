import json
import shutil
import sqlite3
from unittest.mock import patch

from test_recording import FIXTURES, Workspace, needs_lua, read_recording
from control import Companion
import export_signals
from simulate import simulate
from watch_recordings import scan


class DeliveryJournal(Workspace):
    def test_reread_restart_and_independent_delivery_stages(self):
        client = self.tmp / "client"
        path = client / "WTF/Account/test/Realm/Hero/SavedVariables/AlloyRoute.lua"
        path.parent.mkdir(parents=True)
        shutil.copyfile(FIXTURES / "undead_warrior.lua", path)
        folder = self.tmp / "exports"
        app = Companion(folder, client, scan)
        self.assertFalse(scan(client, folder, {}))
        first = app.status()
        self.assertGreater(first["latest"]["new_rows"], 0)
        files = {p.name: p.stat().st_mtime_ns for p in folder.glob("*.jsonl")}
        restarted = Companion(folder, client, scan)
        self.assertEqual(restarted.status()["latest"], first["latest"])
        self.assertFalse(scan(client, folder, {}))
        last = restarted.status()["latest"]
        self.assertEqual((last["new_sessions"], last["new_rows"], last["known"]), (0, 0, len(files)))
        self.assertEqual(files, {p.name: p.stat().st_mtime_ns for p in folder.glob("*.jsonl")})
        state = folder / ".delivery"
        state.mkdir()
        db = sqlite3.connect(state / "delivery.sqlite")
        self.addCleanup(db.close)
        db.execute("CREATE TABLE delivery(session,signal,next_batch, PRIMARY KEY(session,signal))")
        db.execute("CREATE TABLE checkpoint(session PRIMARY KEY,stamp)")
        file = next(folder.glob("*.jsonl"))
        positions = self.tmp / "positions.yml"
        def tail(size):
            positions.write_text(f'positions:\n  ? path: /exports/{file.name}\n    labels: test\n  : "{size}"\n')
            with patch.object(export_signals, "urlopen", side_effect=ConnectionRefusedError):
                export_signals.observe_collector(db, positions, "http://alloy")
            return next(s for s in app.status()["sessions"] if s["key"] == file.stem)
        with patch.object(export_signals, "post", side_effect=OSError("private error details")):
            export_signals.scan(db, folder, "http://alloy")
        self.assertFalse(tail(file.stat().st_size-1)["logs_read"])
        row = tail(file.stat().st_size)
        self.assertTrue(row["logs_read"])
        self.assertFalse(row["metrics"])
        self.assertEqual(row["metrics_attempt"]["error"], "OSError")
        self.assertEqual(app.status()["collector"], "Alloy offline")
        with patch.object(export_signals, "post") as post:
            export_signals.scan(db, folder, "http://alloy")
            self.assertTrue(app.status()["sessions"][0]["metrics"])
            post.reset_mock()
            export_signals.scan(db, folder, "http://alloy")
            post.assert_not_called()
        path.write_text('AlloyRouteRecording="unfinished')
        self.assertIn("complete", scan(client, folder, {}))
        self.assertEqual(restarted.status()["latest"], last)

    @needs_lua
    def test_simulated_journey_crosses_reload(self):
        folder = self.tmp / "exports"
        simulate("journey", folder)
        sessions = []
        for file in folder.glob("*.jsonl"):
            sessions.append([json.loads(line) for line in file.read_text().splitlines()])
        self.assertEqual(len(sessions), 2)
        sessions.sort(key=lambda s: s[0]["ts"])
        events = sessions[0][1:] + sessions[1][1:]
        obj = [r for r in events if r["type"] == "quest_objective"]
        self.assertEqual([(r["observation"],r["fulfilled"]) for r in obj],
                         [("baseline",0),("change",1),("baseline",1),("change",2)])
        self.assertEqual({r["quest_id"] for r in obj}, {380})
        loot, = [r for r in events if r["type"] == "loot_received"]
        self.assertTrue(any(r["type"]=="gear_swap" and r["ts"]>loot["ts"] and r["item_id"]==loot["item_id"] for r in events))
        self.assertEqual({r["category"] for r in events if r["type"]=="skill_rank"}, {"profession","skill"})
        self.assertEqual({r["state"] for r in events if r["type"]=="life"}, {"alive","dead"})
        self.assertTrue(any(r["type"]=="reputation" and r["observation"]=="change" for r in events))
        self.assertTrue(any(r["type"]=="subzone" and r["observation"]=="change" for r in events))
        for header, *rows in sessions:
            stats = export_signals.session_summary(header, rows)
            self.assertGreater(stats["xp_gain"], 0)
            self.assertGreater(stats["xp_per_hour"], 0)
            self.assertIn("net_copper", stats)

    @needs_lua
    def test_secret_target_and_loot_privacy(self):
        self.run_scenario("""
            LOOT_ITEM_SELF_MULTIPLE = "You receive loot: %sx%d."
            LOOT_ITEM_SELF = "You receive loot: %s."
            H.slash("start")
            function UnitExists() return true end
            function UnitGUID() return SECRET end
            H.fire("PLAYER_TARGET_CHANGED")
            function UnitGUID() return "Player-1-123" end
            H.fire("PLAYER_TARGET_CHANGED")
            local link = "|Hitem:42|h[Boots]|h"
            H.fire("CHAT_MSG_LOOT", SECRET)
            H.fire("CHAT_MSG_LOOT", "Someone receives loot: "..link..".")
            for i=1,2 do H.fire("CHAT_MSG_LOOT", "You receive loot: "..link.."x3.", "", "", "", "", "", "", "", "", "", 12) end
            H.logout()
        """)
        _, rows = read_recording.read_file(self.tmp / "AlloyRoute.lua")
        self.assertEqual([r["quantity"] for r in rows if r["type"]=="loot_received"],[3])
        self.assertFalse(any(r["type"]=="target" for r in rows))
