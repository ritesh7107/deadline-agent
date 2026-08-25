"""Step 2-4: decide whether an extraction is a new task, an update to an
existing one, or nothing at all - then gate it on confidence.

The three outcomes are kept deliberately distinct. Collapsing "correction"
and "contradiction" into one path is the mistake the brief is about.
"""
from dataclasses import dataclass

import db
from models import Extraction, MatchVerdict

# Who gets to overwrite a deadline. Keyed on sender_role because a professor
# on WhatsApp is still a professor - the channel is weaker evidence than the
# person. Hearsay caps the score regardless of who forwarded it.
AUTHORITY = {"professor": 4, "system": 4, "ta": 3, "student": 2}
HEARSAY_CAP = 1


def authority(sender_role: str, is_hearsay: bool) -> int:
    score = AUTHORITY.get(sender_role, 2)
    return min(score, HEARSAY_CAP) if is_hearsay else score


@dataclass
class Outcome:
    action: str      # created | updated | duplicate | ignored
    task_id: int | None = None
    note: str = ""
    flagged: bool = False


def resolve(conn, message_id, meta: dict, ex: Extraction, match_fn) -> Outcome:
    """meta carries the message envelope: source, sender_role, received_at."""
    if not ex.is_task:
        out = Outcome("ignored", note=ex.reason)
        db.set_outcome(conn, message_id, out.action, out.note)
        return out

    candidates = db.candidate_tasks(conn, ex.course)
    verdict = (
        match_fn(ex, candidates)
        if candidates
        else MatchVerdict(decision="NEW", confidence=1.0, reason="no open tasks to match against")
    )

    if verdict.decision == "UPDATE" and verdict.task_id:
        out = _apply_update(conn, message_id, meta, ex, verdict)
    elif verdict.decision == "DUPLICATE" and verdict.task_id:
        # Restating a known task changes nothing. This is the branch that stops
        # every reminder message from minting a second copy.
        db.update_task(conn, verdict.task_id)
        out = Outcome("duplicate", verdict.task_id, verdict.reason)
    else:
        out = _create(conn, message_id, meta, ex)

    db.set_outcome(conn, message_id, out.action, out.note)
    return out


def _create(conn, message_id, meta, ex: Extraction) -> Outcome:
    auth = authority(meta["sender_role"], ex.is_hearsay)
    unknown = ex.due_at is None
    task_id = db.insert_task(
        conn,
        title=ex.title or "(untitled)",
        course=ex.course,
        kind=ex.kind,
        due_at=ex.due_at,
        due_precision="unknown" if unknown else ex.due_precision,
        due_authority=None if unknown else auth,
        due_source=None if unknown else meta["source"],
        weightage=ex.weightage,
        needs_confirmation=int(unknown),
        confirm_reason="No deadline stated in the source message" if unknown else None,
    )
    db.add_event(
        conn, task_id, message_id, "created", None, ex.due_at,
        meta["source"], auth, ex.reason,
    )
    return Outcome("created", task_id, ex.reason, flagged=unknown)


def _apply_update(conn, message_id, meta, ex: Extraction, verdict: MatchVerdict) -> Outcome:
    task = db.get_task(conn, verdict.task_id)
    tid = task["id"]
    new_auth = authority(meta["sender_role"], ex.is_hearsay)
    old_auth = task["due_authority"] or 0
    old_due = task["due_at"]

    # Non-deadline detail arriving separately ("it's worth 20%").
    _fill_blanks(conn, tid, task, ex)

    if ex.due_at is None:
        return Outcome("updated", tid, "detail added, no deadline in message",
                       flagged=bool(task["needs_confirmation"]))

    # --- the deadline was previously unknown: fill it ---------------------
    if old_due is None:
        db.update_task(conn, tid, due_at=ex.due_at, due_precision=ex.due_precision,
                       due_authority=new_auth, due_source=meta["source"],
                       needs_confirmation=0, confirm_reason=None)
        db.add_event(conn, tid, message_id, "due_at", None, ex.due_at,
                     meta["source"], new_auth, "deadline was unknown, now stated")
        return Outcome("updated", tid, f"deadline filled in: {ex.due_at}")

    # --- the sources agree: corroboration ---------------------------------
    if ex.due_at == old_due:
        if task["needs_confirmation"] and new_auth >= old_auth:
            db.update_task(conn, tid, needs_confirmation=0, confirm_reason=None,
                           due_authority=max(new_auth, old_auth))
            db.add_event(conn, tid, message_id, "confirmed", old_due, ex.due_at,
                         meta["source"], new_auth, "independent source agrees, flag cleared")
            return Outcome("updated", tid, "contradiction resolved by agreement")
        return Outcome("duplicate", tid, "same deadline restated")

    # --- the sources disagree ---------------------------------------------
    # A. Explicit correction from an equal-or-higher source, or a strictly
    #    more authoritative source. Trust it and move on clean.
    if (ex.correction_signal and new_auth >= old_auth) or new_auth > old_auth:
        why = "explicit correction" if ex.correction_signal else "higher-authority source"
        db.update_task(conn, tid, due_at=ex.due_at, due_precision=ex.due_precision,
                       due_authority=new_auth, due_source=meta["source"],
                       needs_confirmation=0, confirm_reason=None)
        db.add_event(conn, tid, message_id, "due_at", old_due, ex.due_at,
                     meta["source"], new_auth, why)
        return Outcome("updated", tid, f"{why}: {old_due} -> {ex.due_at}")

    # B. Equal authority, no correction language. Take the newer value but
    #    only tentatively, and make the disagreement visible.
    if new_auth == old_auth:
        reason = (f"{task['due_source']} says {old_due}, {meta['source']} says {ex.due_at}"
                  " - equally credible sources, unresolved")
        db.update_task(conn, tid, due_at=ex.due_at, due_precision=ex.due_precision,
                       due_source=meta["source"], needs_confirmation=1, confirm_reason=reason)
        db.add_event(conn, tid, message_id, "due_at", old_due, ex.due_at,
                     meta["source"], new_auth, "conflicting source, flagged for confirmation")
        return Outcome("updated", tid, reason, flagged=True)

    # C. Lower authority disagrees. The date does NOT move - but the student
    #    should still see that people are contradicting the official date.
    reason = (f"{task['due_source']} says {old_due}, but {meta['source']} claims"
              f" {ex.due_at} - lower-authority contradiction, date unchanged")
    db.update_task(conn, tid, needs_confirmation=1, confirm_reason=reason)
    db.add_event(conn, tid, message_id, "due_at_disputed", old_due, ex.due_at,
                 meta["source"], new_auth, "lower-authority contradiction, not applied")
    return Outcome("updated", tid, reason, flagged=True)


def _fill_blanks(conn, tid, task, ex: Extraction):
    """Only ever fills NULLs. Never overwrites a known value - that path
    belongs to the authority rules above."""
    patch = {f: getattr(ex, f) for f in ("weightage", "kind", "course")
             if getattr(ex, f) and not task[f]}
    if patch:
        db.update_task(conn, tid, **patch)
