"""Exercise the addon, reader and OTLP conversion together."""
import sqlite3
from unittest.mock import patch

from test_recording import Workspace, needs_lua, read_recording
import export_signals


@needs_lua
class GameplaySignals(Workspace):
    def capture(self, lua):
        self.run_scenario(lua)
        sessions, events = read_recording.read_file(self.tmp / "AlloyRoute.lua")
        return sessions[0], events

    def points(self, hdr, events):
        batch, = export_signals.metrics(hdr, events, 123456789)
        gauges = batch["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]
        return {m["name"]: m["gauge"]["dataPoints"][0] for m in gauges}

    def test_partial_fights_quest_rewards_and_trace_order(self):
        hdr, events = self.capture("""
            function UnitAffectingCombat() return true end
            H.slash("start")
            H.advance(6)
            H.fire("PLAYER_REGEN_ENABLED")
            H.fire("PLAYER_REGEN_ENABLED")
            S.questLog = {[99]="Training"}
            H.fire("QUEST_ACCEPTED", 1, 99)
            H.fire("QUEST_TURNED_IN", 99, 80, 23)
            H.advance(4)
            H.fire("PLAYER_REGEN_DISABLED")
            H.fire("PLAYER_REGEN_DISABLED")
            H.advance(3)
            H.logout()
        """)
        combat = [r for r in events if r["type"] == "combat"]
        self.assertEqual([r["state"] for r in combat], ["already_active", "left", "entered"])
        self.assertEqual([r["x"] for r in combat], [1000] * 3)
        quests = [r for r in events if r["type"].startswith("quest_")]
        self.assertEqual([r["quest_id"] for r in quests], [99, 99])
        self.assertEqual((quests[1]["reward_xp"], quests[1]["reward_copper"]), (80, 23))
        points = self.points(hdr, events)
        for name, expected in (("combat_seconds", 9), ("combat_entries", 1), ("quest_accepts", 1), ("quest_turn_ins", 1)):
            point = points["wow_addon_session_" + name]
            self.assertEqual((point["asInt"], point["timeUnixNano"]), (str(expected), "123456789"))
        batch, = export_signals.traces(hdr, events)
        root, child = batch["resourceSpans"][0]["scopeSpans"][0]["spans"]
        self.assertEqual(root["spanId"], child["parentSpanId"])
        self.assertEqual(child["traceId"], read_recording.session_key(hdr)[:32])
        self.assertEqual([e["timeUnixNano"] for e in child["events"]], [r["ts_ns"] for r in events])
        names = [e["name"] for e in child["events"]]
        self.assertIn("combat.already_active", names)
        self.assertLess(names.index("quest.accepted"), names.index("quest.turned_in"))

    def test_distinguish_unobserved_combat_from_idle(self):
        hdr, events = self.capture('H.slash("start"); H.logout()')
        self.assertNotIn("wow_addon_session_combat_seconds", self.points(hdr, events))
        hdr, events = self.capture('function UnitAffectingCombat() return false end; H.slash("start"); H.logout()')
        self.assertEqual(self.points(hdr, events)["wow_addon_session_combat_seconds"]["asInt"], "0")

    def test_retries_only_unacknowledged_trace_batches(self):
        hdr, events = self.capture("""
            H.slash("start")
            H.advance(4600, function() S.money = S.money + 1 end)
            H.logout()
        """)
        read_recording.write_sessions(self.tmp, [hdr], events)
        path, = self.tmp.glob("*.jsonl")
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.execute("CREATE TABLE delivery(session,signal,next_batch, PRIMARY KEY(session,signal))")
        db.execute("CREATE TABLE checkpoint(session PRIMARY KEY,stamp)")
        with patch.object(export_signals, "post", side_effect=[None, OSError("offline")]) as post:
            with self.assertRaises(OSError):
                export_signals.deliver(db, path, "traces", "http://collector")
            failed_payload = post.call_args.args[-1]
        with patch.object(export_signals, "post") as post:
            export_signals.scan(db, self.tmp, "http://collector")
            self.assertEqual([call.args[1] for call in post.call_args_list], ["metrics", "traces"])
            self.assertEqual(post.call_args.args[-1], failed_payload)
            post.reset_mock()
            export_signals.scan(db, self.tmp, "http://collector")
            post.assert_not_called()
