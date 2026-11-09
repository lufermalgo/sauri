import contextlib
import io
import pathlib
import sqlite3
import tempfile
import unittest
from importlib.util import module_from_spec, spec_from_file_location

spec = spec_from_file_location("orchestrator_state", pathlib.Path(__file__).with_name("orchestrator-state.py"))
state = module_from_spec(spec)
spec.loader.exec_module(state)


class FocusTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.db.close)
        self.db.executescript("""
            create table tasks(id,status,state,assignee,reviewer,proposed,awaits_owner,title,thread_id,project_id,parent_id);
            create table threads(id,task_id,project_id);
            create table runs(id,thread_id,agent_id,state,ended_at,trigger,started_at);
            create table task_events(n integer,task_id,by);
            insert into tasks values
                ('task_ab','doing','open','nia',null,0,0,'canonical','th1','sauri',null),
                ('task_ac','todo','open',null,null,0,0,'unrelated','th2','sauri',null),
                ('task_ad','todo','open',null,null,0,0,'prerequisite','th3','sauri','task_ab');
            insert into threads values ('th1','task_ab','sauri'),('th2','task_ac','sauri'),('th3','task_ad','sauri');
        """)

    def run_focus(self, dry=False):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            state.focus_pass(lambda sql, p: self.db.execute(sql, p).fetchall(), "sauri", "ansel",
                             "task_ab", self.tmp.name + "/state.json", dry)
        return out.getvalue()

    def test_no_duplicate_wake_for_unchanged_or_unrelated_work(self):
        out = self.run_focus()
        self.assertIn("canonical", out)
        self.assertIn("prerequisite", out)
        self.assertNotIn("unrelated", out)
        self.db.execute("insert into task_events values (1,'task_ac','owner')")
        self.assertEqual(self.run_focus(), "")
        self.db.execute("insert into task_events values (2,'task_ab','nia')")
        self.assertIn("canonical", self.run_focus())
        self.assertEqual(self.run_focus(), "")

    def test_wait_until_live_execution_finishes(self):
        self.db.execute("insert into runs values ('run1','th3','nia','working',null,'a2a','2026-11-09')")
        self.assertEqual(self.run_focus(), "")
        self.db.execute("update runs set state='completed', ended_at='2026-11-09' where id='run1'")
        self.assertIn("run1", self.run_focus())

    def test_closed_focus_does_not_restart_and_dry_does_not_consume_signal(self):
        self.assertIn("canonical", self.run_focus(dry=True))
        self.assertIn("canonical", self.run_focus())
        self.db.execute("update tasks set state='done' where id='task_ab'")
        self.assertEqual(self.run_focus(), "")

    def test_cannot_route_a_card_from_another_project(self):
        self.db.execute("update tasks set project_id='other' where id='task_ab'")
        with self.assertRaisesRegex(SystemExit, "not found"):
            self.run_focus()


if __name__ == "__main__":
    unittest.main()
