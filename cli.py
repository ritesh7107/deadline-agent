"""CLI: ingest, ask, tasks, show, reset."""
import argparse
import json
import sys

import db
import query
from resolve import resolve

BOLD, DIM, RED, YEL, GRN, OFF = "\033[1m", "\033[2m", "\033[31m", "\033[33m", "\033[32m", "\033[0m"
ICON = {"created": f"{GRN}+{OFF}", "updated": f"{YEL}~{OFF}",
        "duplicate": f"{DIM}={OFF}", "ignored": f"{DIM}·{OFF}"}


def cmd_ingest(args):
    import extract  # imported late so `tasks`/`show` work without an API key

    conn = db.connect()
    counts = {"created": 0, "updated": 0, "duplicate": 0, "ignored": 0, "skipped": 0}
    with open(args.file) as f:
        messages = [json.loads(line) for line in f if line.strip()]

    for i, m in enumerate(messages, 1):
        meta = {"source": m["source"], "sender_role": m["sender_role"],
                "received_at": m["received_at"]}
        mid = db.add_message(conn, m["text"], m["source"], m["sender_role"], m["received_at"])
        if mid is None:
            counts["skipped"] += 1
            continue
        ex = extract.extract(m["text"], meta)
        out = resolve(conn, mid, meta, ex, extract.match)
        conn.commit()
        counts[out.action] += 1
        flag = f" {RED}[needs confirmation]{OFF}" if out.flagged else ""
        line = f"{ICON[out.action]} {DIM}{i:>3}{OFF} {m['text'][:56]:<56}"
        if args.verbose or out.action != "ignored":
            print(f"{line} {DIM}{out.note[:44]}{OFF}{flag}")

    print(f"\n{BOLD}{len(messages)} messages{OFF}  "
          + "  ".join(f"{k}: {v}" for k, v in counts.items() if v))


def cmd_tasks(args):
    conn = db.connect()
    rows = query.find(conn, course=args.course, only_flagged=args.flagged)
    if not rows:
        print("No open tasks.")
        return
    print(f"\n{BOLD}{len(rows)} open task(s){OFF}   today is {db.now()}\n")
    for t in rows:
        due = t["due_at"] or f"{RED}unknown{OFF}"
        head = f"  {DIM}#{t['id']:<3}{OFF}{BOLD}{t['title']}{OFF}"
        bits = [b for b in (t["course"], t["kind"], t["weightage"]) if b]
        print(f"{head}  {DIM}{' · '.join(bits)}{OFF}")
        print(f"      due {due}")
        if t["needs_confirmation"]:
            print(f"      {RED}⚑ needs confirmation{OFF} {DIM}{t['conflict_note']}{OFF}")
    print()


def cmd_show(args):
    conn = db.connect()
    t = db.get_task(conn, args.task_id)
    if not t:
        sys.exit(f"No task #{args.task_id}")
    print(f"\n{BOLD}#{t['id']} {t['title']}{OFF}  {DIM}{t['course']} · {t['kind']}{OFF}")
    print(f"  due {t['due_at'] or RED + 'unknown' + OFF}  "
          f"{DIM}({t['due_precision']}, source: {t['due_source'] or 'none'}){OFF}")
    if t["needs_confirmation"]:
        print(f"  {RED}⚑ {t['confirm_reason']}{OFF}")
    print(f"\n  {DIM}history{OFF}")
    for e in db.events_for(conn, t["id"]):
        change = f"{e['old_value'] or '-'} → {e['new_value'] or '-'}"
        print(f"    {DIM}{e['field']:<16}{OFF}{change:<26}"
              f"{DIM}{e['source']} (auth {e['authority']}) · {e['reason']}{OFF}")
    print()


def cmd_ask(args):
    conn = db.connect()
    print(f"\n{query.ask(conn, ' '.join(args.question))}\n")


def cmd_reset(args):
    conn = db.connect()
    conn.executescript("DELETE FROM task_events; DELETE FROM tasks; DELETE FROM messages;")
    conn.commit()
    print("Cleared.")


def main():
    p = argparse.ArgumentParser(prog="deadlines", description="Student deadline agent")
    sub = p.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("ingest", help="process a .jsonl of messages")
    i.add_argument("file")
    i.add_argument("-v", "--verbose", action="store_true", help="also print ignored noise")
    i.set_defaults(fn=cmd_ingest)

    t = sub.add_parser("tasks", help="list open tasks")
    t.add_argument("-c", "--course")
    t.add_argument("-f", "--flagged", action="store_true", help="only those needing confirmation")
    t.set_defaults(fn=cmd_tasks)

    s = sub.add_parser("show", help="one task with its full source history")
    s.add_argument("task_id", type=int)
    s.set_defaults(fn=cmd_show)

    a = sub.add_parser("ask", help='e.g. ask "what is due this week?"')
    a.add_argument("question", nargs="+")
    a.set_defaults(fn=cmd_ask)

    sub.add_parser("reset", help="empty the database").set_defaults(fn=cmd_reset)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
