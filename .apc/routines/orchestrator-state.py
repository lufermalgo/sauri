#!/usr/bin/env python3
"""Pre-command of an orchestrator routine: the state of one project computed without the model.

Prints a compact summary only when the orchestrator has something to act on; prints nothing otherwise, and the
routine (`--call output`) then does not call the model at all. It replaces the model re-reading the board, the jobs
and the PRs on every wake-up, and replaces the handoff file as the cross-run memory.

Wakes (any one prints):
  [changed]  something outside the orchestrator changed since the last wake: a task event by another agent or the
             owner, a specialist run that ended, a PR whose head/state/checks changed, a new pending question
  [dispatch] at least one specialist is free and there is unassigned work, a proposal, an unreviewed card or a card
             waiting on the owner (at most every DISPATCH_MIN minutes)
  [hourly]   a full review at least every FULL_MIN minutes
Read-only on APX's database. State: <home>/work/orch-state/<project>.json.
Usage: orchestrator-state.py <project_id> <agent_prefix> <orchestrator_agent_id> <owner/repo> [--dry] [--focus=task_ID]
Env for tests: ORCH_DB, ORCH_NOW (ISO), ORCH_STATE_DIR, ORCH_NO_GH=1.
"""
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone

DB = os.environ.get("ORCH_DB", os.path.expanduser("~/.apx/v2/apx.db"))
STATE_DIR = os.environ.get("ORCH_STATE_DIR", os.path.expanduser("~/.apx/v2/work/orch-state"))
FULL_MIN = 60
DISPATCH_MIN = 30
QUIET_MIN = 2  # a hand-off may still be in flight
STALE_RUN_H = 6  # a run "working" for longer than this is not counted as busy
MAX_CARDS = 12  # cards listed in the summary; the whole output stays under the 8,000-character step limit


def now():
    v = os.environ.get("ORCH_NOW")
    return datetime.fromisoformat(v.replace("Z", "+00:00")) if v else datetime.now(timezone.utc)


def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def focus_pass(q, project, orch, task, state_file, dry):
    # The scope is supplied by the operator, not inferred from an idle agent or a PR title.
    if not re.fullmatch(r"task_[a-f0-9]+", task):
        raise SystemExit("invalid focus card id")
    rows = q(
        "select id,status,state,assignee,reviewer,proposed,awaits_owner,title,thread_id "
        "from tasks where project_id=? and (id=? or parent_id=?) order by id",
        (project, task, task),
    )
    root = next((row for row in rows if row[0] == task), None)
    if root is None:
        raise SystemExit("focus card not found in this project")
    if root[2] != "open":
        return
    ids = [row[0] for row in rows]
    slots = ",".join("?" for _ in ids)
    # Review and mention consultations use context.consult.task instead of thread.task_id.
    linked = "coalesce(t.task_id,json_extract(case when json_valid(t.context) then t.context else '{}' end,'$.consult.task'))"
    runs = q(
        f"select {linked},r.id,r.agent_id,r.state,r.ended_at from runs r "
        f"join threads t on t.id=r.thread_id where t.project_id=? "
        f"and {linked} in ({slots}) and r.trigger!='routine' "
        f"order by r.started_at desc,r.id desc",
        (project, *ids),
    )
    if any(run[3] in ("working", "queued", "waiting", "scheduled") and run[4] is None for run in runs):
        return
    latest = {}
    for run in runs:
        latest.setdefault(run[0], run[1:4])
    event = q(
        f"select coalesce(max(n),0) from task_events where task_id in ({slots}) and by!=?",
        (*ids, orch),
    )[0][0]
    signal = hashlib.sha256(json.dumps([rows, latest, event]).encode()).hexdigest()
    try:
        with open(state_file) as f:
            if json.load(f).get("signal") == signal:
                return
    except (OSError, ValueError, AttributeError):
        pass
    print(f"FOCUS: {task}; authorized scope is only this delivery and named prerequisites.")
    for tid, status, state, assignee, reviewer, prop, waits, title, _ in rows[:MAX_CARDS]:
        print(f"{tid} | {status}/{state} | {assignee or '-'} | reviewer={reviewer or '-'} "
              f"| proposal={prop} owner={waits} | {str(title)[:90]} | latest run={latest.get(tid)}")
    if not dry:
        with open(state_file + ".tmp", "w") as f:
            json.dump({"signal": signal}, f)
        os.replace(state_file + ".tmp", state_file)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv
    project, prefix, orch, repo = args[:4]
    t = now()
    os.makedirs(STATE_DIR, exist_ok=True)
    sf = os.path.join(STATE_DIR, project + ".json")
    try:
        st = json.load(open(sf))
    except Exception:
        st = {}
    last = st.get("last_wake") or iso(t - timedelta(hours=1))
    con = sqlite3.connect("file:" + DB + "?mode=ro", uri=True, timeout=5)
    q = lambda sql, p=(): con.execute(sql, p).fetchall()

    focus = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--focus=")), None)
    if focus is not None:
        focus_pass(q, project, orch, focus, os.path.join(STATE_DIR, project + ".focus.json"), dry)
        return

    agents = {a: (n, r) for a, n, r in q("select id, name, role from agents where project_id=? and coalesce(archived,0)=0", (project,))}
    specialists = [a for a in agents if a != orch]
    busy = {
        a: (title or "")
        for a, title in q(
            "select r.agent_id, coalesce(k.title, th.title) from runs r join threads th on th.id=r.thread_id "
            "left join tasks k on k.id=th.task_id where r.agent_id like ? and r.ended_at is null and r.state='working' "
            "and r.trigger!='routine' and r.started_at>?",
            (prefix + "%", iso(t - timedelta(hours=STALE_RUN_H))),
        )
        if a != orch
    }
    free = [a for a in specialists if a not in busy and agents[a][1] != "product-owner"]

    counts = dict(
        q("select status, count(*) from tasks where project_id=? and state='open' group by 1", (project,))
    )
    one = lambda sql, p=(): q(sql, p)[0][0]
    n_prop = one("select count(*) from tasks where project_id=? and state='open' and proposed=1", (project,))
    n_owner = one("select count(*) from tasks where project_id=? and state='open' and awaits_owner=1", (project,))
    n_noreviewer = one(
        "select count(*) from tasks where project_id=? and state='open' and status='review' and (reviewer is null or reviewer='')",
        (project,),
    )
    # Dispatch only cards that are open, unassigned and actionable now. Proposals and
    # cards waiting on Fer stay visible in their separate queues, not as assignable work.
    n_unassigned = one(
        "select count(*) from tasks where project_id=? and state='open' and assignee is null "
        "and status in ('todo','backlog') and coalesce(proposed,0)=0 and coalesce(awaits_owner,0)=0",
        (project,),
    )
    ready_cards = q(
        "select id, status, priority, substr(title,1,70) from tasks where project_id=? and state='open' "
        "and assignee is null and status in ('todo','backlog') and coalesce(proposed,0)=0 "
        "and coalesce(awaits_owner,0)=0 order by case priority when 'urgent' then 0 when 'high' then 1 "
        "when 'normal' then 2 else 3 end, activity_at desc limit ?",
        (project, MAX_CARDS + 1),
    )
    pend = [r[0] for r in q("select id from pending_inputs where state='pending' and agent_id like ?", (prefix + "%",))]

    # outside changes since the last wake
    ext_events = q(
        "select e.by, substr(k.title,1,60), substr(e.data,1,90), k.id from task_events e join tasks k on k.id=e.task_id "
        "where k.project_id=? and e.at>? and e.by!=? and e.at<=? order by e.at limit 25",
        (project, last, orch, iso(t - timedelta(minutes=QUIET_MIN))),
    )
    ended = q(
        "select r.agent_id, substr(coalesce(k.title, th.title),1,60) from runs r join threads th on th.id=r.thread_id "
        "left join tasks k on k.id=th.task_id where r.agent_id like ? and r.agent_id!=? and r.trigger!='routine' "
        "and r.ended_at>? and r.ended_at<=? order by r.ended_at limit 25",
        (prefix + "%", orch, last, iso(t - timedelta(minutes=QUIET_MIN))),
    )
    prs, pr_note = [], ""
    if not os.environ.get("ORCH_NO_GH"):
        try:
            out = subprocess.run(
                ["gh", "pr", "list", "--repo", repo, "--state", "open", "--limit", "60", "--json",
                 "number,title,headRefOid,mergeStateStatus,statusCheckRollup"],
                capture_output=True, text=True, timeout=40,
            )
            for p in json.loads(out.stdout or "[]"):
                checks = [c.get("conclusion") or c.get("status") or "?" for c in p.get("statusCheckRollup") or []]
                ci = "red" if any(c in ("FAILURE", "CANCELLED", "TIMED_OUT") for c in checks) else (
                    "running" if any(c in ("IN_PROGRESS", "QUEUED", "PENDING") for c in checks) else ("green" if checks else "no checks"))
                prs.append((p["number"], p["headRefOid"][:7], p["mergeStateStatus"], ci, p["title"][:55]))
        except Exception as ex:  # keep going: a failed gh call must not hide the rest
            pr_note = f"(GitHub did not answer: {type(ex).__name__})"
    pr_sig = hashlib.sha1(json.dumps(sorted(prs)).encode()).hexdigest()[:12]
    pr_changed = st.get("pr_sig") not in (None, pr_sig) and not pr_note
    new_pending = [i for i in pend if i not in st.get("pending", [])]

    reasons = []
    if ext_events or ended or pr_changed or new_pending:
        reasons.append("changed")
    last_dispatch = st.get("last_dispatch")
    if free and (n_unassigned or n_prop or n_noreviewer or n_owner):
        if not last_dispatch or datetime.fromisoformat(last_dispatch.replace("Z", "+00:00")) < t - timedelta(minutes=DISPATCH_MIN):
            reasons.append("dispatch")
    last_full = st.get("last_full")
    if not last_full or datetime.fromisoformat(last_full.replace("Z", "+00:00")) < t - timedelta(minutes=FULL_MIN):
        reasons.append("hourly")
    if not reasons:
        return

    stamp = t.astimezone().strftime("%H:%M")
    L = [
        f"SYSTEM STATE computed without the model ({stamp}). Use it instead of reading the board, the jobs and "
        f"the PRs; open only the cards you will move. Woken because: {', '.join(reasons)}."
    ]
    nm = lambda a: agents[a][0] if a in agents else a.replace(prefix, "")
    L.append("Team: " + "; ".join(
        [f"{agents[a][0]} [{a}] ({agents[a][1] or 'role unknown'}) BUSY ({busy[a][:40]})" for a in busy]
        + [f"{agents[a][0]} [{a}] ({agents[a][1] or 'role unknown'}) FREE" for a in free]
    ))
    L.append(
        "Open cards: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
        + f" | unassigned in todo/backlog: {n_unassigned} | proposals: {n_prop} | waiting on the owner: {n_owner}"
        + f" | in review without reviewer: {n_noreviewer} | pending questions: {len(pend)}"
    )
    if ext_events or ended:
        L.append("Changes since the last wake:")
        for by, title, data, _tid in ext_events[:8]:
            L.append(f"  - {by.replace(prefix, '')} changed '{title}' {data[:60]}")
        for a, title in ended[:6]:
            L.append(f"  - {nm(a)} finished a run on '{title}'")
    if prs or pr_note:
        L.append("Open PRs: " + (pr_note or "; ".join(f"#{n} {ms.lower()} CI {ci} '{ti}'" for n, h, ms, ci, ti in prs[:14])))
    # The cards to act on, with what the orchestrator needs to decide without opening each one.
    def handoff_tail(desc):
        d = desc or ""
        i = d.rfind("HAND-OFF")
        s = d[i:] if i >= 0 else d[-400:]
        return " ".join(s.split())[:200]
    picked, seen = [], set()
    def add(label, rows):
        for r in rows:
            if r[0] in seen or len(picked) >= MAX_CARDS:
                continue
            seen.add(r[0]); picked.append((label,) + tuple(r))
    cols = "id, status, coalesce(assignee,''), proposed, awaits_owner, coalesce(reviewer,''), substr(title,1,70), description"
    base = f"select {cols} from tasks where project_id=? and state='open'"
    changed_ids = list(dict.fromkeys(e[3] for e in ext_events))
    if changed_ids:
        add("changed", q(base + f" and id in ({','.join('?' * len(changed_ids))})", (project, *changed_ids)))
    add("returned to you", q(base + " and assignee=? and status in ('todo','doing','review') order by activity_at desc limit 6", (project, orch)))
    add("proposal", q(base + " and proposed=1 order by activity_at desc limit 4", (project,)))
    add("waiting on the owner", q(base + " and awaits_owner=1 order by activity_at desc limit 3", (project,)))
    add("review without reviewer", q(base + " and status='review' and (reviewer is null or reviewer='') order by activity_at asc limit 4", (project,)))
    add("ready, unassigned", q(base + " and assignee is null and status in ('todo','backlog') "
        "and coalesce(proposed,0)=0 and coalesce(awaits_owner,0)=0 order by activity_at desc limit 4", (project,)))
    if picked:
        L.append("Cards to act on (open only the ones you will move):")
        for label, tid, status, assignee, prop, owner, reviewer, title, desc in picked:
            flags = " ".join(f for f, on in (("proposed", prop), ("waits-owner", owner)) if on)
            who = nm(assignee) if assignee else "unassigned"
            rv = f" reviewer {nm(reviewer)}" if reviewer else ""
            L.append(f"  - [{label}] {tid} | {status} | {who}{rv} {flags} | {title}")
            tail = handoff_tail(desc)
            if tail:
                L.append(f"      {tail}")
    if ready_cards:
        L.append("Assignable backlog/todo (open, unassigned, not proposed, not waiting on owner):")
        for tid, status, priority, title in ready_cards[:MAX_CARDS]:
            L.append(f"  - {tid} | {status} | {priority or 'normal'} | {title}")
        if len(ready_cards) > MAX_CARDS:
            L.append(f"  - … {len(ready_cards) - MAX_CARDS} more eligible card(s) omitted")
    out = "\n".join(L)
    print(out[:7500])
    if dry:
        return
    st.update(last_wake=iso(t), pr_sig=pr_sig if not pr_note else st.get("pr_sig"), pending=pend)
    if "hourly" in reasons:
        st["last_full"] = iso(t)
    if "dispatch" in reasons:
        st["last_dispatch"] = iso(t)
    if "hourly" not in reasons and not st.get("last_full"):
        st["last_full"] = iso(t)
    json.dump(st, open(sf + ".tmp", "w"))
    os.replace(sf + ".tmp", sf)


if __name__ == "__main__":
    main()
