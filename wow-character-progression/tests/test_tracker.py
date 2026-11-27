"""Run with the tracker dependencies and PYTHONPATH=app."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import tracker
from profiles import ProfileError, Profiles


class ProgressionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = patch.object(tracker, "db_file", Path(tmp.name) / "roster.sqlite")
        db.start()
        self.addCleanup(db.stop)
        enabled = patch.object(tracker.source, "enabled", True)
        enabled.start()
        self.addCleanup(enabled.stop)
        tracker.initialize()
        self.client = tracker.app.test_client()
        self.player = {"name": "River Stone", "region": "eu"}
        self.assertEqual(self.client.post("/api/characters", json=self.player).status_code, 201)

    def poll(self):
        with tracker.database() as conn:
            row = conn.execute("SELECT * FROM characters LIMIT 1").fetchone()
        tracker.poll(row)

    def test_progression_retry_and_removal(self):
        baseline = {"level": 16, "item_level": None, "achievements": 0, "class_name": "Mage", "avatar": ""}
        progressed = dict(baseline, level=17, item_level=9, achievements=2)
        results = [baseline, baseline, ProfileError("Unavailable"), progressed]
        with patch.object(tracker.source, "fetch", side_effect=results):
            with self.assertLogs(tracker.events) as logs:
                self.poll()
            self.assertEqual([e.event for e in logs.records], ["profile.baseline"])
            with self.assertNoLogs(tracker.events):
                self.poll()
            with self.assertLogs(tracker.events, "WARNING"):
                self.poll()
            row = tracker.roster()[0]
            self.assertEqual(row["snapshot"], baseline)
            self.assertEqual(row["error"], "Unavailable")
            self.assertEqual(list(tracker.observations("level")(None)), [])
            with self.assertLogs(tracker.events) as logs:
                self.poll()
            self.assertEqual(
                [e.event for e in logs.records], ["poll.recovered", "progress.changed", "progress.changed"]
            )
            self.assertEqual([(e.previous, e.current) for e in logs.records[1:]], [(16, 17), (0, 2)])
        tracker.initialize()
        self.assertEqual(tracker.roster()[0]["snapshot"], progressed)
        self.assertEqual(next(tracker.observations("level")(None)).value, 17)
        self.assertEqual(self.client.delete(f"/api/characters/{row['id']}").status_code, 204)
        self.assertEqual(list(tracker.observations("level")(None)), [])

    def test_region_identity_and_duplicate_names(self):
        self.assertEqual(
            self.client.post("/api/characters", json={**self.player, "name": "RIVER  stone"}).status_code, 409
        )
        self.assertEqual(
            self.client.post("/api/characters", json={**self.player, "region": "us"}).status_code, 201
        )
        self.assertEqual(
            self.client.post("/api/characters", json={**self.player, "region": "xx"}).status_code, 400
        )
        self.assertEqual(
            self.client.post("/api/characters", json={**self.player, "name": "River"}).status_code, 400
        )
        self.assertEqual(len(tracker.roster()), 2)

    def test_remove_and_readd_during_poll(self):
        with tracker.database() as conn:
            removed = conn.execute("SELECT * FROM characters").fetchone()
        self.client.delete(f"/api/characters/{removed['id']}")
        self.client.post("/api/characters", json=self.player)
        with (
            patch.object(tracker.source, "fetch", return_value={"level": 16}),
            self.assertNoLogs(tracker.events),
        ):
            tracker.poll(removed)
        self.assertIsNone(tracker.roster()[0]["snapshot"])


class SourceTests(unittest.TestCase):
    def test_api_oauth_reuse_and_optional_gear(self):
        with patch.dict(os.environ, BLIZZARD_CLIENT_ID="test", BLIZZARD_CLIENT_SECRET="example"):
            src = Profiles()
        token = {"access_token": "example", "expires_in": 86400}
        summary = {"level": 60, "character_class": {"name": "Mage"}}
        achievements = {"total_quantity": 3}
        replies = [token, summary, achievements, summary, achievements]
        with patch.object(
            src.http,
            "request",
            side_effect=[Mock(ok=True, status_code=200, json=lambda v=v: v) for v in replies],
        ) as http:
            first = src.fetch("eu", "river-stone")
            self.assertEqual(src.fetch("eu", "river-stone"), first)
        self.assertEqual(first["achievements"], 3)
        self.assertIsNone(first["item_level"])
        calls = http.call_args_list
        self.assertEqual(calls[0].args, ("POST", "https://oauth.battle.net/token"))
        self.assertEqual(
            calls[1].args, ("GET", "https://eu.api.blizzard.com/profile/wow/character/river-stone")
        )
        self.assertEqual(calls[2].args[1], calls[1].args[1] + "/achievements")
        self.assertEqual(calls[1].kwargs["params"]["namespace"], "profile-forever-eu")
        self.assertEqual(calls[1].kwargs["headers"], {"Authorization": "Bearer example"})

    def test_missing_credentials_make_no_outbound_requests(self):
        with patch.dict(os.environ, BLIZZARD_CLIENT_ID="", BLIZZARD_CLIENT_SECRET=""):
            src = Profiles()
        with patch.object(src.http, "request") as http, patch.object(tracker, "source", src):
            with self.assertRaisesRegex(ProfileError, "credentials"):
                src.fetch("eu", "river-stone")
            client = tracker.app.test_client()
            self.assertEqual(client.post("/api/characters", json={"name": "River Stone", "region": "eu"}).status_code, 503)
            self.assertIn(b"Set BLIZZARD_CLIENT_ID", client.get("/").data)
            http.assert_not_called()
