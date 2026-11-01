#!/usr/bin/env python3
"""Unit tests for bin/hermes-blob-bridge's event bookkeeping (no Hermes needed)."""
import importlib.machinery
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
loader = importlib.machinery.SourceFileLoader("hermes_blob_bridge", str(ROOT / "bin" / "hermes-blob-bridge"))
spec = importlib.util.spec_from_loader("hermes_blob_bridge", loader)
assert spec is not None
bridge = importlib.util.module_from_spec(spec)
loader.exec_module(bridge)


def frame(kind, admission="", sid="S1", **payload):
    params = {"session_id": sid, "type": kind, "payload": payload}
    if admission:
        params["admission_id"] = admission
    return params


class BotStateTest(unittest.TestCase):
    def setUp(self):
        self.out = []
        self.state = bridge.BotState("donna", lambda **ev: self.out.append(ev))
        self.state.session_id = "S1"

    def test_own_ask_streams_then_completes_with_the_streamed_text(self):
        self.state.mine["A"] = "ask1"
        for kind, text in [("message.start", None), ("message.delta", "bridge"), ("message.delta", " live")]:
            self.state.handle(frame(kind, "A", **({"text": text} if text else {})))
        self.state.handle(frame("message.complete", "A", text=None, status="complete"))
        self.assertEqual(self.out[-2], {"ev": "delta", "bot": "donna", "text": "bridge live", "askId": "ask1"})
        self.assertEqual(self.out[-1], {"ev": "complete", "bot": "donna", "text": "bridge live",
                                        "status": "complete", "askId": "ask1"})
        self.assertNotIn("A", self.state.mine)

    def test_a_turn_nobody_here_asked_for_is_reported_without_an_ask_id(self):
        self.state.handle(frame("message.delta", "B", text="Sentinel answered ack."))
        self.state.handle(frame("message.complete", "B"))
        self.assertEqual(self.out[-1], {"ev": "complete", "bot": "donna", "text": "Sentinel answered ack.",
                                        "status": "complete"})

    def test_an_empty_unrequested_turn_is_silent(self):
        self.state.handle(frame("message.complete", "B", text=""))
        self.assertEqual(self.out, [])

    def test_events_before_the_receipt_are_held_and_replayed_as_ours(self):
        self.state.submitting = 1
        self.state.handle(frame("message.delta", "A", text="early"))
        self.state.handle(frame("message.complete", "A"))
        self.assertEqual(self.out, [])
        self.state.own("A", "ask9")
        self.assertEqual(self.out[-1]["askId"], "ask9")
        self.assertEqual(self.out[-1]["text"], "early")
        self.assertEqual(self.state.submitting, 0)

    def test_tool_call_resets_commentary_and_reports_progress(self):
        self.state.mine["A"] = "ask1"
        self.state.handle(frame("message.delta", "A", text="Let me ask Sentinel."))
        self.state.handle(frame("tool.start", "A", tool_name="message_agent"))
        self.state.handle(frame("message.delta", "A", text="Asked."))
        self.state.handle(frame("message.complete", "A"))
        self.assertIn({"ev": "progress", "bot": "donna", "text": "Using message_agent…", "askId": "ask1"}, self.out)
        self.assertEqual(self.out[-1]["text"], "Asked.")

    def test_other_sessions_are_ignored_and_a_replay_gap_asks_to_reattach(self):
        self.assertTrue(self.state.handle(frame("message.complete", "Z", sid="OTHER", text="x")))
        self.assertEqual(self.out, [])
        self.assertFalse(self.state.handle(frame("session.replay_gap")))

    def test_generation_follows_the_owner_for_interrupts(self):
        self.state.handle({"session_id": "S1", "type": "agent.step", "execution_generation": 12, "payload": {}})
        self.assertEqual(self.state.generation, 12)
        self.state.handle(frame("session.info", execution_generation=13))
        self.assertEqual(self.state.generation, 13)

    def test_approval_and_clarify_requests_are_forwarded(self):
        self.state.handle(frame("approval.request", "A", prompt_id="p1", description="rm -rf build"))
        self.assertEqual(self.out[-1]["ev"], "prompt")
        self.assertEqual(self.out[-1]["kind"], "approval")
        self.assertEqual(self.out[-1]["text"], "rm -rf build")


class RosterTest(unittest.TestCase):
    def test_only_roster_bots_that_are_profiles_are_attached(self):
        with tempfile.TemporaryDirectory() as home:
            os.environ["HOME"] = home
            os.environ.pop("XDG_CONFIG_HOME", None)
            root = Path(home) / ".hermes"
            for path in [root, root / "profiles" / "donna"]:
                path.mkdir(parents=True, exist_ok=True)
                (path / "config.yaml").write_text("{}\n")
            config = Path(home) / ".config" / "omarchy"
            config.mkdir(parents=True)
            (config / "grokbot-bots.json").write_text(
                '{"bots": [{"id": "default"}, {"id": "donna"}, {"id": "e0195a7d-f804-4688-9191-e2cf3574a6d1"},'
                ' {"id": "../x"}, {"id": "donna"}]}')
            self.assertEqual(bridge.roster_profiles(root), ["default", "donna"])
            self.assertEqual(bridge.profile_home(root, "default"), root)

    def test_bot_chat_is_the_newest_unarchived_session_with_that_exact_title(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as home:
            db = sqlite3.connect(Path(home) / "state.db")
            db.execute("create table sessions (id text, title text, archived int, started_at real, last_activity_at real)")
            db.executemany("insert into sessions values (?,?,?,?,?)", [
                ("old", "Bot Chat", 0, 1, 1), ("new", "Bot Chat", 0, 2, 5), ("gone", "Bot Chat", 1, 3, 9),
                ("other", "Bot Chat 2", 0, 4, 10)])
            db.commit()
            db.close()
            self.assertEqual(bridge.bot_chat_id(Path(home)), "new")
            self.assertEqual(bridge.bot_chat_id(Path(home) / "missing"), "")


if __name__ == "__main__":
    unittest.main(verbosity=1)
