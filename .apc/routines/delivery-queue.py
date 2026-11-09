#!/usr/bin/env python3
"""Select one approved delivery and dispatch only its explicitly ready, independent jobs."""
import argparse
import fcntl
import hashlib
import json
import os
import re
import sqlite3
import subprocess
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

TASK = re.compile(r"task_[0-9a-f]+")
AGENT = re.compile(r"[A-Za-z0-9_-]+")
# A run may be submitted (before the worker starts) or a consultation without task_id.
TERMINAL = {"completed", "failed", "canceled"}


def load_queue(path):
    data = json.loads(path.read_text())
    if not isinstance(data, list):
        raise ValueError("the queue must be an ordered JSON list")
    seen = set()
    for delivery in data:
        root, jobs = delivery["root"], delivery["jobs"]
        if not delivery["approval"].strip() or not jobs:
            raise ValueError("each delivery needs explicit approval evidence and at least one job")
        for card, entry in [(root, delivery), *((job["card"], job) for job in jobs)]:
            if not TASK.fullmatch(card) or card in seen:
                raise ValueError(f"invalid or duplicate card: {card}")
            seen.add(card)
            deps = entry.get("requires", [])
            if len(set(deps)) != len(deps) or any(not TASK.fullmatch(x) or x == card for x in deps):
                raise ValueError(f"invalid prerequisites: {card}")
        graph = {job["card"]: set(job.get("requires", [])) for job in jobs}
        if root in delivery.get("requires", []) or set(delivery.get("requires", [])) & graph.keys():
            raise ValueError("a delivery cannot wait for one of its own jobs before admission")
        remaining = set(graph)
        while remaining:
            ready = {key for key in remaining if not graph[key] & remaining}
            if not ready or any(root in graph[key] for key in remaining):
                raise ValueError("cyclic delivery dependencies")
            remaining -= ready
        for job in jobs:
            if not re.fullmatch(r"[0-9a-f]{64}", job["packet_sha256"]):
                raise ValueError(f"job {job['card']} needs the approved PACKET SHA-256")
            if not AGENT.fullmatch(job["agent"]) or not job["resources"] or any(
                not isinstance(r, str) or not r.strip() for r in job["resources"]
            ):
                raise ValueError(f"job {job['card']} needs an agent and explicit resource locks")
            for name in ("requires_merges", "completion_merges"):
                if any(type(n) is not int or n <= 0 for n in job.get(name, [])):
                    raise ValueError(f"invalid GitHub issue gate: {job['card']}")
            if job.get("from") is not None and not AGENT.fullmatch(job["from"]):
                raise ValueError(f"invalid current assignee for {job['card']}")
    return data


def save_state(path, state):
    temp = path.with_suffix(".tmp")
    with temp.open("w") as file:
        json.dump(state, file, sort_keys=True)
        file.flush()
        os.fsync(file.fileno())
    temp.replace(path)


class Board:
    def __init__(self, db, project):
        self.db, self.project = db, project

    def snapshot(self):
        with closing(sqlite3.connect(f"file:{self.db}?mode=ro", uri=True, timeout=5)) as con:
            con.row_factory = sqlite3.Row
            con.execute("BEGIN")
            cards = {r["id"]: dict(r) for r in con.execute(
                "select id,state,status,assignee,proposed,awaits_owner,start_at,parent_id,description "
                "from tasks where project_id=?", (self.project,)
            )}
            agents = {r[0] for r in con.execute(
                "select id from agents where project_id=? and coalesce(archived,0)=0", (self.project,)
            )}
            linked = """coalesce(t.task_id,json_extract(
                case when json_valid(t.context) then t.context else '{}' end,'$.consult.task'))"""
            runs = [dict(r) for r in con.execute(
                f"""select r.id,r.agent_id,r.state,r.ended_at,r.created_at,{linked} as card
                    from runs r join threads t on t.id=r.thread_id
                    where t.project_id=? and r.trigger!='routine'
                    order by r.created_at desc,r.id desc""", (self.project,)
            )]
        return cards, agents, runs


def live(run):
    return run["ended_at"] is None and run["state"] not in TERMINAL



class GitHub:
    def __init__(self, gh, repo):
        self.gh, self.repo, self.cache = gh, repo, {}

    def merged_issue(self, issue):
        if issue not in self.cache:
            self.cache[issue] = self._verify(issue)
        return self.cache[issue]

    def _verify(self, issue):
        if not self.gh or not self.repo:
            return False
        def view(kind, number, fields):
            return json.loads(subprocess.check_output(
                [self.gh, "-R", self.repo, kind, "view", str(number), "--json", fields],
                stderr=subprocess.DEVNULL, text=True, timeout=12))
        try:
            info = view("issue", issue, "state,closedByPullRequestsReferences")
            if info["state"] != "CLOSED":
                return False
            for link in info["closedByPullRequestsReferences"]:
                repo = link["repository"]
                if f"{repo['owner']['login']}/{repo['name']}".lower() != self.repo.lower():
                    continue
                pr = view("pr", link["number"], "state,baseRefName,mergeCommit")
                if pr["state"] == "MERGED" and pr["baseRefName"] == "main" and pr["mergeCommit"]:
                    return True
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError):
            return False
        return False


def dispatch_cli(apx, card, agent):
    return subprocess.run([apx, "tasks", "edit", card, "--agent", agent],
                          capture_output=True, text=True, timeout=15)


def tick(queue, state, snapshot, dispatch, persist, now, dry=False, merged_issue=lambda _n: False):
    if dry:
        state = json.loads(json.dumps(state))
        persist = lambda _state: None
    cards, agents, runs = snapshot()
    active_runs = [run for run in runs if live(run)]
    entries = {item["root"]: item for item in queue}

    def done(card):
        row = cards.get(card, {})
        return row.get("state") == "done" and not row.get("proposed")

    def common(card):
        row = cards.get(card)
        if row is None:
            return "missing or outside project"
        if row["state"] != "open":
            return f"state={row['state']}"
        if row["proposed"] or row["awaits_owner"]:
            return "proposal or owner approval pending"
        if row["start_at"] and datetime.fromisoformat(row["start_at"].replace("Z", "+00:00")) > now:
            return "scheduled for later"
        return None

    def scoped(entry):
        return {entry["root"], *(job["card"] for job in entry["jobs"])}

    def job_done(job):
        return done(job["card"]) and all(merged_issue(n) for n in job.get("completion_merges", []))

    def finished(entry):
        return done(entry["root"]) and all(job_done(job) for job in entry["jobs"])

    def ready(job, attempts):
        card, agent = job["card"], job["agent"]
        reason = common(card)
        if reason:
            return reason
        row = cards[card]
        if not row["description"].strip():
            return "missing PACKET"
        if hashlib.sha256(row["description"].encode()).hexdigest() != job["packet_sha256"]:
            return "PACKET differs from its approved SHA-256"
        if row["status"] != "todo" or row["assignee"] != job.get("from") or agent == row["assignee"]:
            return "needs todo and the declared previous assignee"
        if agent not in agents:
            return "agent missing or archived"
        if any(not done(d) for d in job.get("requires", [])):
            return "prerequisites not done: " + ",".join(d for d in job["requires"] if not done(d))
        missing = [n for n in job.get("requires_merges", []) if not merged_issue(n)]
        if missing:
            return "merge into main not verified for " + ",".join(f"#{n}" for n in missing)
        if card in attempts:
            return "already attempted; do not retry automatically"
        if any(run["card"] == card or run["agent_id"] == agent for run in active_runs):
            return "card or agent already has a live run"
        return None

    root = state.get("active")
    if root and root not in entries:
        return [f"QUEUE BLOCKED: active delivery {root} was removed from the manifest; restore or resolve it."]
    if root:
        entry = entries[root]
        if not any(run["card"] in scoped(entry) for run in active_runs) and (
            finished(entry) or cards.get(root, {}).get("state") == "dropped"
        ):
            root = None
    if not root:
        if active_runs:
            return ["QUEUE WAIT: live project runs must finish before another delivery is admitted."]
        reasons = []
        for entry in queue:
            key = entry["root"]
            if finished(entry) or cards.get(key, {}).get("state") == "dropped":
                continue
            issue = common(key)
            if any(cards.get(j["card"], {}).get("parent_id") != key for j in entry["jobs"]):
                issue = "a declared job is not a child of this delivery"
            unmet = [d for d in entry.get("requires", []) if not done(d)]
            candidates = [(j, ready(j, {})) for j in entry["jobs"]]
            if not issue and not unmet and any(not reason for _, reason in candidates):
                root = key
                state.update(active=root, attempts={})
                persist(state)
                break
            details = issue or (("unmet delivery prerequisites " + ",".join(unmet)) if unmet else
                                 "; ".join(f"{j['card']}: {reason}" for j, reason in candidates))
            reasons.append(f"{key}: {details}")
        if not root:
            state.update(active=None, attempts={})
            return ["QUEUE BLOCKED: no approved delivery is ready."] + (reasons or ["No pending approved entries."])

    entry = entries[root]
    ids = scoped(entry)
    attempts = state.setdefault("attempts", {})
    if common(root):
        return [f"QUEUE BLOCKED: keep active {root}; {common(root)}. No rollover."]
    if any(run["card"] not in ids for run in active_runs):
        return [f"QUEUE WAIT: keep active {root}; an unrelated or unlinked project run is live."]
    if any(cards.get(job["card"], {}).get("parent_id") != root for job in entry["jobs"]):
        return [f"QUEUE BLOCKED: keep active {root}; a declared job is not a child of this delivery."]
    declared_jobs = {job["card"] for job in entry["jobs"]}
    if any(run["card"] not in declared_jobs for run in active_runs):
        return [f"QUEUE WAIT: active {root}; its coordinator or an unclassified scoped run is live."]

    locked, workers, lines = set(), set(), [f"QUEUE ACTIVE: {root}"]
    for job in entry["jobs"]:
        card = job["card"]
        if not job_done(job) and (card in attempts or any(run["card"] == card for run in active_runs)):
            locked.update(job["resources"])
            workers.add(job["agent"])
    for job in entry["jobs"]:
        card, agent = job["card"], job["agent"]
        if done(card):
            note = "done" if job_done(job) else "board done; required GitHub merge not verified"
            lines.append(f"{card}: {note}")
            continue
        if card in attempts:
            record = attempts[card]
            observed = next((run for run in runs if run["id"] == record.get("run")), None)
            status = (f"run {observed['id']} {observed['state']}" if observed else record["result"])
            row = cards.get(card, {})
            lines.append(f"{card}: {status}; card={row.get('status')}, owner={row.get('awaits_owner')}, proposal={row.get('proposed')}")
            continue
        reason = ready(job, attempts)
        if reason or locked.intersection(job["resources"]) or agent in workers:
            lines.append(f"{card}: {reason or 'resource or agent already reserved'}")
            continue
        if dry:
            lines.append(f"{card}: would assign {agent}")
            locked.update(job["resources"])
            workers.add(agent)
            continue
        # Recheck immediately before writing. Persist the attempt before the external call.
        cards, agents, runs = snapshot()
        active_runs = [run for run in runs if live(run)]
        other_resources = {r for other in entry["jobs"] for r in other["resources"]
                           if other["card"] != card and any(run["card"] == other["card"] for run in active_runs)}
        if (common(root) or ready(job, attempts) or other_resources.intersection(job["resources"])
                or any(run["card"] not in declared_jobs for run in active_runs)):
            lines.append(f"{card}: state changed before dispatch")
            continue
        old_runs = {run["id"] for run in runs if run["card"] == card}
        attempts[card] = {"result": "dispatch attempted; verify in APX before any retry"}
        persist(state)
        locked.update(job["resources"])
        workers.add(agent)
        try:
            result = dispatch(card, agent)
        except (OSError, subprocess.TimeoutExpired) as exc:
            attempts[card]["result"] = f"dispatch uncertain: {type(exc).__name__}"
        else:
            cards, agents, runs = snapshot()
            matched = next((run for run in runs if run["card"] == card and
                            run["agent_id"] == agent and run["id"] not in old_runs), None)
            if result.returncode or cards.get(card, {}).get("assignee") != agent:
                attempts[card]["result"] = f"assignment failed or did not stick (exit {result.returncode})"
            elif matched:
                attempts[card] = {"run": matched["id"], "result": "verified run"}
            else:
                attempts[card]["result"] = "assignment reported but no matching new run observed"
        persist(state)
        record = attempts[card]
        lines.append(f"{card}: {record.get('run', record['result'])}")
    if all(job_done(job) for job in entry["jobs"]):
        if any(live(run) and run["card"] in ids for run in runs):
            return [f"QUEUE WAIT: active {root}; a scoped run still needs to finish."]
        lines.append("All declared jobs done. Ansel: verify the approved acceptance gates and close the root only with evidence.")
    elif not any(live(run) and run["card"] in ids for run in runs) and not (
        dry and any("would assign" in line for line in lines)
    ):
        # A returned review is actionable for Ansel, not a readiness failure.
        if not any(cards.get(job["card"], {}).get("status") == "review" for job in entry["jobs"]):
            lines[0] = f"QUEUE BLOCKED: active {root} has no live or dispatchable job."
        lines.append("No live job. Ansel: review returned work or report the recorded blockers.")
    if any(live(run) and run["card"] in ids for run in runs):
        lines[0] = f"QUEUE WAIT: {root}; scoped execution is live."
    return lines


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    parser.add_argument("queue", type=Path)
    parser.add_argument("--db", type=Path, default=Path.home()/".apx/v2/apx.db")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--apx", required=True)
    parser.add_argument("--gh")
    parser.add_argument("--repo")
    parser.add_argument("--dry", action="store_true")
    args = parser.parse_args()
    try:
        queue = load_queue(args.queue)
        args.state.parent.mkdir(parents=True, exist_ok=True)
        # Share this lock among routine starts. A dry run never dispatches or consumes a report.
        with args.state.with_suffix(".lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            state = json.loads(args.state.read_text()) if args.state.exists() else {}
            board = Board(args.db, args.project)
            persist = (lambda _s: None) if args.dry else lambda s: save_state(args.state, s)
            lines = tick(queue, state, board.snapshot,
                         lambda card, agent: dispatch_cli(args.apx, card, agent),
                         persist, datetime.now(timezone.utc), args.dry,
                         GitHub(args.gh, args.repo).merged_issue)
            report = "\n".join(lines)[:7500]
            if args.dry or state.get("last_report") != report:
                state["last_report"] = report
                persist(state)
                if args.dry or not report.startswith("QUEUE WAIT:"):
                    print(report)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, sqlite3.Error) as exc:
        print(f"QUEUE BLOCKED: invalid configuration or unavailable APX state ({type(exc).__name__}). Do not dispatch.")


if __name__ == "__main__":
    main()
