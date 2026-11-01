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
        self.assertIn({"ev": "progress", "bot": "donna", "text": "Messaging a teammate…", "askId": "ask1"}, self.out)
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

    def test_approval_requests_carry_their_command_and_choices(self):
        self.state.mine["A"] = "ask1"
        self.state.handle(frame("approval.request", "A", prompt_id="p1", description="recursive delete",
                                command="rm -rf build", choices=["once", "deny", "session"], execution_generation=4))
        self.assertEqual(self.out[-1], {"ev": "prompt", "bot": "donna", "promptId": "p1", "kind": "approval",
                                        "choices": ["once", "deny", "session"], "multiSelect": False,
                                        "askId": "ask1", "text": "recursive delete", "command": "rm -rf build"})
        self.assertEqual(self.state.prompts["p1"], {"kind": "approval", "generation": 4})

    def test_clarify_requests_without_an_admission_still_reach_the_shell(self):
        self.state.handle(frame("clarify.request", prompt_id="q1", question="Red or blue?",
                                choices=["red", "blue"], multi_select=False))
        self.assertEqual(self.out[-1]["kind"], "clarify")
        self.assertEqual(self.out[-1]["text"], "Red or blue?")
        self.assertEqual(self.out[-1]["choices"], ["red", "blue"])

    def test_a_prompt_answered_anywhere_is_settled_once(self):
        self.state.handle(frame("approval.request", "A", prompt_id="p1", description="x", choices=["once"]))
        self.state.handle(frame("approval.settled", prompt_id="p1"))
        self.state.handle(frame("approval.settled", prompt_id="p1"))
        self.assertEqual([e["ev"] for e in self.out], ["prompt", "settled"])
        self.assertEqual(self.state.prompts, {})

    def test_attaching_replays_open_prompts_and_drops_stale_ones(self):
        self.state.handle(frame("approval.request", "A", prompt_id="old", description="x", choices=["once"]))
        self.state.attached({"prompts": [{"kind": "clarify", "prompt_id": "q2", "question": "Which?",
                                          "choices": [], "execution_generation": 7}]})
        self.assertEqual([(e["ev"], e.get("promptId")) for e in self.out[1:]],
                         [("history", None), ("settled", "old"), ("prompt", "q2")])
        self.assertEqual(self.state.prompts["q2"]["generation"], 7)


class HistoryAndProgressTest(unittest.TestCase):
    def test_history_keeps_questions_and_final_replies_only(self):
        rows = [
            {"role": "user", "content": bridge.NOTE + "\n\nq1"},
            {"role": "assistant", "content": "", "tool_calls": [{}]},
            {"role": "tool", "content": "{}"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "[IMPORTANT: background]", "display_kind": "process_complete"},
            {"role": "assistant", "content": "The job finished."},
            {"role": "user", "content": "Message from \U0001f916 Sentinel (@sentinel): ack"},
            {"role": "assistant", "content": "Got it."},
            {"role": "user", "content": "q4"},
            {"role": "assistant", "content": "[SILENT]"},
        ]
        self.assertEqual(bridge.history_items(rows), [
            {"asked": "q1", "body": "a1"},
            {"asked": "", "body": "The job finished."},
            {"asked": "From Sentinel: ack", "body": "Got it."},
        ])
        many = [r for i in range(30) for r in ({"role": "user", "content": f"q{i}"}, {"role": "assistant", "content": f"a{i}"})]
        self.assertEqual(bridge.history_items(many)[0], {"asked": "q10", "body": "a10"})

    def test_progress_names_what_the_bot_is_doing(self):
        self.assertEqual(bridge.tool_label({"tool_name": "message_agent", "args": {"target": "@sentinel"}}), "Messaging sentinel…")
        self.assertEqual(bridge.tool_label({"tool_name": "terminal"}), "Running a command…")
        self.assertEqual(bridge.tool_label({"tool_name": "mnemosyne_recall"}), "Checking memory…")
        self.assertEqual(bridge.tool_label({"tool_name": "odd"}), "Using odd…")

    def test_a_turn_started_elsewhere_completes_with_its_question(self):
        out = []
        state = bridge.BotState("donna", lambda **ev: out.append(ev))
        state.session_id = "S1"
        state.handle(frame("session.info", pending=[{"admission_id": "D", "text": "from desktop"}]))
        state.handle(frame("thinking.delta", "D", text="(◇) on it"))
        state.handle(frame("message.delta", "D", text="Here you go."))
        state.handle(frame("message.complete", "D"))
        self.assertEqual(out[0], {"ev": "progress", "bot": "donna", "text": "(◇) on it"})
        self.assertEqual(out[-1], {"ev": "complete", "bot": "donna", "text": "Here you go.", "status": "complete",
                                   "asked": "from desktop"})

    def test_attaching_sends_history_first(self):
        out = []
        state = bridge.BotState("donna", lambda **ev: out.append(ev))
        state.attached({"messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]})
        self.assertEqual(out[0], {"ev": "history", "bot": "donna", "items": [{"asked": "hi", "body": "hello"}]})


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
