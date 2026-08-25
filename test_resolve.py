"""Offline tests for the resolver. No API key, no network - the model call is
replaced by a canned verdict so every branch is deterministic.

    python test_resolve.py
"""
import os

os.environ["NOW"] = "2026-08-25"

import db
from models import Extraction, MatchVerdict
from resolve import authority, resolve

WHATSAPP = {"source": "whatsapp group", "sender_role": "student", "received_at": "2026-08-20"}
PROF_MAIL = {"source": "prof email", "sender_role": "professor", "received_at": "2026-08-21"}
TA_MAIL = {"source": "TA email", "sender_role": "ta", "received_at": "2026-08-21"}
CLASSMATE = {"source": "whatsapp group", "sender_role": "student", "received_at": "2026-08-22"}


def task(**kw):
    base = dict(is_task=True, reason="deliverable named", title="DBMS report",
                course="DBMS", kind="assignment", due_precision="date_only")
    return Extraction(**{**base, **kw})


def feed(conn, text, meta, ex, verdict=None):
    mid = db.add_message(conn, text, meta["source"], meta["sender_role"], meta["received_at"])
    assert mid is not None, "duplicate body hash"
    return resolve(conn, mid, meta, ex, lambda e, c: verdict)


def fresh():
    return db.connect(":memory:")


def check(name, fn):
    fn()
    print(f"  ok  {name}")


# --------------------------------------------------------------------------
def test_noise_is_ignored():
    c = fresh()
    out = feed(c, "anyone up for football at 6?", WHATSAPP,
               Extraction(is_task=False, reason="social plan, no deliverable"))
    assert out.action == "ignored"
    assert c.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0


def test_new_task_with_date():
    c = fresh()
    out = feed(c, "DBMS report due 28th", TA_MAIL, task(due_at="2026-08-28"))
    assert out.action == "created" and not out.flagged
    t = db.get_task(c, out.task_id)
    assert t["due_at"] == "2026-08-28" and t["needs_confirmation"] == 0
    assert t["due_authority"] == 3


def test_unknown_deadline_is_flagged_never_guessed():
    c = fresh()
    out = feed(c, "OS lab report - submit soon, date will be announced", PROF_MAIL,
               task(title="OS lab report", course="OS", kind="lab",
                    due_at=None, due_precision="unknown"))
    assert out.action == "created" and out.flagged
    t = db.get_task(c, out.task_id)
    assert t["due_at"] is None, "a deadline was invented"
    assert t["due_precision"] == "unknown" and t["needs_confirmation"] == 1
    assert "No deadline stated" in t["confirm_reason"]


def test_clean_correction_updates_and_unflags():
    c = fresh()
    a = feed(c, "DBMS quiz on Wednesday", PROF_MAIL,
             task(title="DBMS quiz", kind="quiz", due_at="2026-08-26"))
    b = feed(c, "quiz moved to Friday", PROF_MAIL,
             task(title="DBMS quiz", kind="quiz", due_at="2026-08-28",
                  correction_signal=True, references_old_value="Wednesday"),
             MatchVerdict(decision="UPDATE", task_id=a.task_id, confidence=.95, reason="same quiz"))
    assert b.action == "updated" and not b.flagged
    assert c.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1, "correction made a duplicate"
    t = db.get_task(c, a.task_id)
    assert t["due_at"] == "2026-08-28" and t["needs_confirmation"] == 0
    ev = [e for e in db.events_for(c, a.task_id) if e["field"] == "due_at"][0]
    assert (ev["old_value"], ev["new_value"]) == ("2026-08-26", "2026-08-28")


def test_true_contradiction_flags_and_keeps_both():
    c = fresh()
    a = feed(c, "DBMS report due 25th", TA_MAIL, task(due_at="2026-08-25"))
    b = feed(c, "DBMS report deadline is 28th", {**TA_MAIL, "source": "TA email #2"},
             task(due_at="2026-08-28"),
             MatchVerdict(decision="UPDATE", task_id=a.task_id, confidence=.9, reason="same report"))
    assert b.action == "updated" and b.flagged
    t = db.get_task(c, a.task_id)
    assert t["needs_confirmation"] == 1
    assert "25" in t["confirm_reason"] and "28" in t["confirm_reason"], "both versions must show"
    ev = [e for e in db.events_for(c, a.task_id) if e["field"] == "due_at"][0]
    assert ev["old_value"] == "2026-08-25" and ev["new_value"] == "2026-08-28"


def test_higher_authority_overrides_without_correction_language():
    c = fresh()
    a = feed(c, "heard DBMS report is 25th", WHATSAPP, task(due_at="2026-08-25"))
    b = feed(c, "DBMS report deadline 28th", PROF_MAIL, task(due_at="2026-08-28"),
             MatchVerdict(decision="UPDATE", task_id=a.task_id, confidence=.9, reason="same report"))
    assert b.action == "updated" and not b.flagged
    t = db.get_task(c, a.task_id)
    assert t["due_at"] == "2026-08-28" and t["due_authority"] == 4


def test_lower_authority_cannot_move_the_date():
    c = fresh()
    a = feed(c, "DBMS report due 28th", PROF_MAIL, task(due_at="2026-08-28"))
    b = feed(c, "someone said DBMS report is 25th", CLASSMATE,
             task(due_at="2026-08-25", is_hearsay=True),
             MatchVerdict(decision="UPDATE", task_id=a.task_id, confidence=.8, reason="same report"))
    t = db.get_task(c, a.task_id)
    assert t["due_at"] == "2026-08-28", "rumour overwrote the professor"
    assert b.flagged and t["needs_confirmation"] == 1
    assert any(e["field"] == "due_at_disputed" for e in db.events_for(c, a.task_id))


def test_weak_source_correction_that_quotes_the_old_date():
    """The brief's own example: a group chat saying "due 25th not 28th"
    against a TA's 28th. It must update the task - and flag it, because the
    correction came from the weaker source."""
    c = fresh()
    a = feed(c, "DBMS report due 28th", TA_MAIL, task(due_at="2026-08-28"))
    b = feed(c, "guys the DBMS report is due 25th not 28th", CLASSMATE,
             task(due_at="2026-08-25", correction_signal=True, references_old_value="28th"),
             MatchVerdict(decision="UPDATE", task_id=a.task_id, confidence=.9, reason="same report"))
    assert c.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1, "correction made a duplicate"
    t = db.get_task(c, a.task_id)
    assert t["due_at"] == "2026-08-25", "the correction did not take"
    assert b.flagged and t["needs_confirmation"] == 1, "weak-source correction must be flagged"
    ev = [e for e in db.events_for(c, a.task_id) if e["field"] == "due_at"][0]
    assert ev["old_value"] == "2026-08-28" and ev["new_value"] == "2026-08-25"


def test_correction_quoting_the_wrong_old_date_is_not_trusted():
    c = fresh()
    a = feed(c, "DBMS report due 28th", PROF_MAIL, task(due_at="2026-08-28"))
    feed(c, "DBMS report moved to 25th, not the 21st", CLASSMATE,
         task(due_at="2026-08-25", correction_signal=True, references_old_value="21st"),
         MatchVerdict(decision="UPDATE", task_id=a.task_id, confidence=.7, reason="same report"))
    t = db.get_task(c, a.task_id)
    assert t["due_at"] == "2026-08-28", "corrected a date it never held"
    assert t["needs_confirmation"] == 1


def test_duplicate_creates_nothing():
    c = fresh()
    a = feed(c, "DBMS report due 28th", TA_MAIL, task(due_at="2026-08-28"))
    b = feed(c, "reminder: DBMS report is due Friday guys", CLASSMATE,
             task(due_at="2026-08-28"),
             MatchVerdict(decision="DUPLICATE", task_id=a.task_id, confidence=.9, reason="restated"))
    assert b.action == "duplicate"
    assert c.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1


def test_unknown_deadline_gets_filled_later():
    c = fresh()
    a = feed(c, "OS lab report, date TBA", PROF_MAIL,
             task(title="OS lab", course="OS", due_at=None, due_precision="unknown"))
    b = feed(c, "OS lab report due 30th", PROF_MAIL,
             task(title="OS lab", course="OS", due_at="2026-08-30"),
             MatchVerdict(decision="UPDATE", task_id=a.task_id, confidence=.9, reason="same lab"))
    t = db.get_task(c, a.task_id)
    assert t["due_at"] == "2026-08-30" and t["needs_confirmation"] == 0 and not b.flagged


def test_agreement_clears_an_existing_flag():
    c = fresh()
    a = feed(c, "DBMS report 25th", TA_MAIL, task(due_at="2026-08-25"))
    feed(c, "DBMS report 28th", {**TA_MAIL, "source": "TA email #2"}, task(due_at="2026-08-28"),
         MatchVerdict(decision="UPDATE", task_id=a.task_id, confidence=.9, reason="same"))
    assert db.get_task(c, a.task_id)["needs_confirmation"] == 1
    feed(c, "confirming DBMS report is the 28th", PROF_MAIL, task(due_at="2026-08-28"),
         MatchVerdict(decision="UPDATE", task_id=a.task_id, confidence=.95, reason="same"))
    assert db.get_task(c, a.task_id)["needs_confirmation"] == 0, "agreement should clear the flag"


def test_reingest_is_idempotent():
    c = fresh()
    feed(c, "DBMS report due 28th", TA_MAIL, task(due_at="2026-08-28"))
    assert db.add_message(c, "DBMS report due 28th", "x", "student", "2026-08-20") is None


def test_query_works_from_a_worker_thread():
    """Pydantic AI calls sync tools off the main thread. Without
    check_same_thread=False every `ask` dies before reaching the model."""
    import threading

    import query
    c = fresh()
    feed(c, "DBMS report due 28th", TA_MAIL, task(due_at="2026-08-28"))
    box = {}
    t = threading.Thread(target=lambda: box.update(r=query.find(c)))
    t.start()
    t.join()
    assert box.get("r"), "query failed when called off the main thread"


def test_authority_ladder():
    assert authority("professor", False) > authority("ta", False) > authority("student", False)
    assert authority("professor", True) == 1, "hearsay must cap regardless of who said it"


if __name__ == "__main__":
    print("resolver")
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            check(name[5:].replace("_", " "), fn)
    print("\nall green")
