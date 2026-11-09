import hashlib
import importlib.util
import json
import pathlib
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone

spec = importlib.util.spec_from_file_location("delivery_queue", pathlib.Path(__file__).with_name("delivery-queue.py"))
queue = importlib.util.module_from_spec(spec)
spec.loader.exec_module(queue)


def job(id, agent, resources, requires=()):
    return {"card": id, "agent": agent, "resources": resources, "requires": list(requires),
            "packet_sha256": hashlib.sha256(b"PACKET").hexdigest()}


class QueueTest(unittest.TestCase):
    def setUp(self):
        self.a, self.b, self.x, self.y, self.z = ("task_1", "task_2", "task_a", "task_b", "task_c")
        self.cards = {i: dict(id=i, state="open", status="todo", assignee=None, proposed=0, awaits_owner=0,
                             start_at=None, parent_id=None, description="PACKET")
                      for i in (self.a, self.b, self.x, self.y, self.z)}
        self.cards[self.x]["parent_id"] = self.a
        self.cards[self.y]["parent_id"] = self.a
        self.cards[self.z]["parent_id"] = self.b
        self.items = [{"root": self.a, "approval": "reviewed a", "jobs": [
            job(self.x, "agent-a", ["frontend"]), job(self.y, "agent-b", ["backend"])]},
            {"root": self.b, "approval": "reviewed b", "jobs": [job(self.z, "agent-c", ["docs"])]}]
        self.state, self.runs, self.called, self.saved = {}, [], [], []
        self.agents = {"agent-a", "agent-b", "agent-c"}

    def snapshot(self):
        return self.cards, self.agents, self.runs

    def run_record(self, card, agent, state="submitted"):
        return {"id": f"run-{len(self.runs)}", "card": card, "agent_id": agent,
                "state": state, "ended_at": None}

    def dispatch(self, card, agent):
        self.assertIn(card, self.saved[-1]["attempts"])
        self.called.append(card)
        self.cards[card]["assignee"] = agent
        self.runs.append(self.run_record(card, agent))
        return subprocess.CompletedProcess([], 0)

    def tick(self, dry=False, dispatch=None):
        return "\n".join(queue.tick(self.items, self.state, self.snapshot, dispatch or self.dispatch,
                                    lambda s: self.saved.append(json.loads(json.dumps(s))),
                                    datetime.now(timezone.utc), dry))

    def complete(self, *cards):
        for card in cards:
            self.cards[card]["state"] = "done"
        for run in self.runs:
            if run["card"] in cards:
                run.update(state="completed", ended_at="now")

    def test_parallel_then_automatic_rollover_and_exhaustion(self):
        self.assertIn("QUEUE ACTIVE: " + self.a, self.tick())
        self.assertEqual(self.called, [self.x, self.y])
        self.assertIn("submitted", self.tick())
        self.assertEqual(self.called, [self.x, self.y])
        self.complete(self.x, self.y)
        self.assertIn("verify the approved acceptance gates", self.tick())
        self.assertEqual(self.called, [self.x, self.y])
        self.complete(self.a)
        self.assertIn("QUEUE ACTIVE: " + self.b, self.tick())
        self.assertEqual(self.called, [self.x, self.y, self.z])
        self.complete(self.z, self.b)
        self.assertIn("no approved delivery is ready", self.tick())
        self.assertEqual(self.called, [self.x, self.y, self.z])

    def test_readiness_skips_blocked_higher_priority_without_dispatching_it(self):
        self.cards[self.a]["awaits_owner"] = 1
        self.assertIn(self.b, self.tick())
        self.assertEqual(self.called, [self.z])

    def test_hold_active_until_root_and_every_child_done(self):
        self.tick()
        self.complete(self.a, self.x)
        self.assertIn("No rollover", self.tick())
        self.assertNotIn(self.z, self.called)

    def test_resource_overlap_serializes(self):
        self.items[0]["jobs"][1]["resources"] = ["frontend"]
        self.tick()
        self.assertEqual(self.called, [self.x])
        self.complete(self.x)
        self.tick()
        self.assertEqual(self.called, [self.x, self.y])

    def test_dependencies_serialize_and_same_agent_cannot_run_in_parallel(self):
        self.items[0]["jobs"][1].update(requires=[self.x], agent="agent-a")
        self.tick()
        self.assertEqual(self.called, [self.x])
        self.complete(self.x)
        self.tick()
        self.assertEqual(self.called, [self.x, self.y])

    def test_proposed_future_and_unrelated_work_are_not_dispatched(self):
        self.cards[self.x]["proposed"] = 1
        self.cards[self.y]["start_at"] = "2099-01-01T00:00:00Z"
        self.cards[self.z]["status"] = "backlog"
        self.assertIn("no approved delivery is ready", self.tick())
        self.assertFalse(self.called)
        self.runs.append(self.run_record(None, "agent-other"))
        self.assertIn("live project runs", self.tick())

    def test_ambiguous_assignment_never_retries(self):
        def no_run(card, agent):
            self.called.append(card)
            return subprocess.CompletedProcess([], 0)
        self.assertIn("did not stick", self.tick(dispatch=no_run))
        self.tick(dispatch=no_run)
        self.assertEqual(self.called, [self.x, self.y])
        self.assertNotIn(self.z, self.called)

    def test_changed_packet_is_never_dispatched(self):
        self.cards[self.x]["description"] = "different scope"
        self.assertIn("approved SHA-256", self.tick())
        self.assertEqual(self.called, [self.y])

    def test_dry_run_never_calls_dispatch_or_persist(self):
        self.assertIn("would assign agent-a", self.tick(dry=True))
        self.assertEqual((self.called, self.saved), ([], []))

    def test_reject_invalid_manifest_and_cyclic_dependencies(self):
        self.items[0]["jobs"][0]["requires"] = [self.y]
        self.items[0]["jobs"][1]["requires"] = [self.x]
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "queue.json"
            p.write_text(json.dumps(self.items))
            with self.assertRaisesRegex(ValueError, "cyclic"):
                queue.load_queue(p)

    def test_live_review_and_explicit_withdrawal(self):
        self.tick()
        self.complete(self.x, self.y)
        self.cards[self.a]["state"] = "dropped"
        self.runs.append(self.run_record(self.a, "reviewer", "working"))
        self.assertIn("keep active", self.tick())
        self.assertNotIn(self.z, self.called)
        self.runs[-1].update(state="completed", ended_at="now")
        self.tick()
        self.assertIn(self.z, self.called)


class CommandTest(unittest.TestCase):
    def test_actual_sqlite_subprocess_deduplicates_no_ready_and_dry_never_consumes(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = pathlib.Path(folder)
            db = folder / "apx.db"
            with sqlite3.connect(db) as con:
                con.executescript("""
                  create table tasks(id,project_id,state,status,assignee,proposed,awaits_owner,start_at,parent_id,description);
                  create table agents(id,project_id,archived);
                  create table threads(id,project_id,task_id,context);
                  create table runs(id,agent_id,state,ended_at,created_at,thread_id,trigger);
                """)
            manifest = folder / "queue.json"
            manifest.write_text("[]")
            state = folder / "state.json"
            args = [sys.executable, "-I", spec.origin, "p_canary", str(manifest), "--state",
                    str(state), "--db", str(db), "--apx", "/no-such-apx"]
            def invoke(*flags):
                return subprocess.check_output(args + list(flags), text=True)
            self.assertIn("no approved delivery is ready", invoke("--dry"))
            self.assertFalse(state.exists())
            self.assertIn("no approved delivery is ready", invoke())
            self.assertEqual(invoke(), "")
