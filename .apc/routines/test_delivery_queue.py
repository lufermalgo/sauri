import hashlib
import importlib.util
import json
import pathlib
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from contextlib import closing
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
        self.merged = set()
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
                                    datetime.now(timezone.utc), dry, self.merged.__contains__))

    def complete(self, *cards):
        for card in cards:
            self.cards[card]["state"] = "done"
        for run in self.runs:
            if run["card"] in cards:
                run.update(state="completed", ended_at="now")

    def add_third(self):
        root, card = "task_3", "task_d"
        self.cards[root] = dict(self.cards[self.a], id=root)
        self.cards[card] = dict(self.cards[self.x], id=card, parent_id=root, assignee=None)
        self.items.append({"root": root, "approval": "reviewed third",
                           "jobs": [job(card, "agent-a", ["third"])]})
        return root, card

    def test_parallel_across_roots_then_automatic_rollover_and_exhaustion(self):
        root, card = self.add_third()
        self.assertIn("QUEUE WAIT: " + self.a, self.tick())
        self.assertEqual(self.called, [self.x, self.y, self.z])
        self.assertEqual(self.state["active"], [self.a, self.b])
        self.assertIn("submitted", self.tick())
        self.assertEqual(self.called, [self.x, self.y, self.z])
        self.complete(self.x, self.y)
        self.assertIn("verify the approved acceptance gates", self.tick())
        self.assertNotIn(card, self.called)
        self.complete(self.a)
        self.assertIn("QUEUE WAIT: " + root, self.tick())
        self.assertEqual(self.state["active"], [self.b, root])
        self.complete(self.z, self.b, card, root)
        self.assertIn("no approved delivery is ready", self.tick())
        self.assertEqual(self.called, [self.x, self.y, self.z, card])

    def test_migrates_single_active_root_and_preserves_uncertain_attempt(self):
        self.state.update(active=self.a, attempts={self.x: {"result": "uncertain"}})
        self.tick()
        self.assertEqual(self.called, [self.y, self.z])
        self.assertEqual(self.state["attempts"][self.x], {"result": "uncertain"})

    def test_blocked_active_root_does_not_stop_independent_root(self):
        self.state.update(active=self.a, attempts={})
        self.cards[self.a]["awaits_owner"] = 1
        self.assertIn("QUEUE BLOCKED: keep active " + self.a, self.tick())
        self.assertEqual(self.called, [self.z])

    def test_review_wakes_with_another_root_live(self):
        self.tick()
        self.complete(self.x)
        self.cards[self.x].update(state="open", status="review")
        self.assertIn("Returned reviews: " + self.x, self.tick())

    def test_ended_verified_run_frees_agent_but_not_its_resource(self):
        self.items[1]["jobs"][0].update(agent="agent-a")
        self.tick()
        self.assertNotIn(self.z, self.called)
        self.runs[0].update(state="completed", ended_at="now")
        self.items[1]["jobs"][0]["resources"] = ["frontend"]
        self.tick()
        self.assertNotIn(self.z, self.called)
        self.items[1]["jobs"][0]["resources"] = ["docs"]
        self.tick()
        self.assertIn(self.z, self.called)

    def test_resource_collision_with_live_card_even_when_card_done(self):
        self.items[1]["jobs"][0]["resources"] = ["frontend"]
        self.tick()
        self.cards[self.x]["state"] = "done"
        self.tick()
        self.assertNotIn(self.z, self.called)
        self.complete(self.x)
        self.tick()
        self.assertIn(self.z, self.called)

    def test_readiness_skips_blocked_higher_priority_without_dispatching_it(self):
        self.cards[self.a]["awaits_owner"] = 1
        self.assertIn(self.b, self.tick())
        self.assertEqual(self.called, [self.z])

    def test_hold_active_until_root_and_every_child_done(self):
        _, card = self.add_third()
        self.tick()
        self.complete(self.a, self.x)
        self.assertIn("No rollover", self.tick())
        self.assertNotIn(card, self.called)

    def test_resource_overlap_serializes(self):
        self.items[0]["jobs"][1]["resources"] = ["frontend"]
        self.tick()
        self.assertEqual(self.called, [self.x, self.z])
        self.complete(self.x)
        self.tick()
        self.assertEqual(self.called, [self.x, self.z, self.y])

    def test_dependencies_serialize_and_same_agent_cannot_run_in_parallel(self):
        self.items[0]["jobs"][1].update(requires=[self.x], agent="agent-a")
        self.tick()
        self.assertEqual(self.called, [self.x, self.z])
        self.complete(self.x)
        self.tick()
        self.assertEqual(self.called, [self.x, self.z, self.y])

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
        self.assertEqual(self.called, [self.x, self.y, self.z])

    def test_apx_done_without_github_merge_does_not_unlock_dependent_or_rollover(self):
        self.items[0]["jobs"][0]["completion_merges"] = [557]
        self.items[0]["jobs"][1].update(requires=[self.x], requires_merges=[557])
        self.tick()
        self.complete(self.x)
        self.assertIn("#557", self.tick())
        self.assertEqual(self.called, [self.x, self.z])
        self.merged.add(557)
        self.tick()
        self.assertEqual(self.called, [self.x, self.z, self.y])

    def test_changed_packet_is_never_dispatched(self):
        self.cards[self.x]["description"] = "different scope"
        self.assertIn("approved SHA-256", self.tick())
        self.assertEqual(self.called, [self.y, self.z])

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
        self.cards[self.z]["status"] = "backlog"
        self.tick()
        self.complete(self.x, self.y)
        self.cards[self.a]["state"] = "dropped"
        self.runs.append(self.run_record(self.a, "reviewer", "working"))
        self.cards[self.z]["status"] = "todo"
        self.assertIn("unclassified", self.tick())
        self.assertNotIn(self.z, self.called)
        self.runs[-1].update(state="completed", ended_at="now")
        self.tick()
        self.assertIn(self.z, self.called)


class CommandTest(unittest.TestCase):
    def test_actual_sqlite_subprocess_deduplicates_no_ready_and_dry_never_consumes(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = pathlib.Path(folder)
            db = folder / "apx.db"
            with closing(sqlite3.connect(db)) as con:
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


class GitHubTest(unittest.TestCase):
    def test_closed_issue_without_merged_main_pr_is_not_evidence(self):
        issue = {"state":"CLOSED", "closedByPullRequestsReferences":[
            {"number":8,"repository":{"name":"sauri","owner":{"login":"example"}}}]}
        for pr, result in [({"state":"MERGED","baseRefName":"staging","mergeCommit":{"oid":"1"}},False),
                           ({"state":"MERGED","baseRefName":"main","mergeCommit":{"oid":"1"}},True)]:
            with patch.object(queue.subprocess, "check_output", side_effect=[json.dumps(issue), json.dumps(pr)]) as gh:
                verifier=queue.GitHub("/gh","example/sauri")
                self.assertEqual(verifier.merged_issue(7),result)
                self.assertEqual(verifier.merged_issue(7),result)
                self.assertEqual(gh.call_count,2)
