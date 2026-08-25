"""Step 1 (extract) and the model half of step 2 (match).

Both LLM calls live here so the resolver stays pure and testable.
"""
import hashlib
import json
import os
import time
from datetime import date
from functools import cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError

from models import Extraction, MatchVerdict

load_dotenv()

MODEL = os.environ.get("MODEL", "google:gemini-2.5-flash")

# Free tiers are rate limited per minute and per day, and one pass over the
# corpus is ~110 calls. Both knobs below exist so a full ingest survives that.
RPM = int(os.environ.get("RPM", "10"))
CACHE = Path(os.environ.get("CACHE_DIR", ".cache")) / "extractions.json"

_last_call = 0.0


def _throttle():
    global _last_call
    gap = 60.0 / RPM - (time.monotonic() - _last_call)
    if gap > 0:
        time.sleep(gap)
    _last_call = time.monotonic()


def _call(agent: Agent, prompt: str):
    """Throttled, with a bounded retry - free tiers return 429 readily."""
    for attempt in range(4):
        _throttle()
        try:
            return agent.run_sync(prompt).output
        except ModelHTTPError as e:
            if e.status_code not in (429, 503) or attempt == 3:
                raise
            wait = 12 * (attempt + 1)
            print(f"    rate limited, waiting {wait}s")
            time.sleep(wait)


def _cache_load() -> dict:
    try:
        return json.loads(CACHE.read_text())
    except (OSError, ValueError):
        return {}


def _cache_save(store: dict):
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(store))

EXTRACT_PROMPT = """\
You read one message forwarded by a student - a class announcement, a group
chat message, an email, or a syllabus snippet - and pull out the deliverable
it describes, if any.

is_task is FALSE for anything the student does not have to hand in or sign up
for: social plans, questions, complaints, greetings, and logistics. Many of
these mention a time ("football at 6?", "class at 9 tmrw?", "cricket on
Sunday 4pm") - a time is not a deadline. Room changes, cancelled or shifted
classes, timetable and bus-timing changes are logistics, not deliverables
("lab 3, they shifted it" is not a task). Judge the intent, not the presence
of a date.

due_at is the hard rule of this system: an ISO date only when the message
actually states or clearly implies one relative to the message date. If the
message says "soon", "TBA", "will be announced", or gives no date at all,
due_at MUST be null and due_precision MUST be "unknown". Never infer a
plausible date. A wrong date is far worse than no date.

due_precision is "exact" when a time of day is given, "date_only" for a bare
date, "unknown" when there is none.

correction_signal is true when the message revises something previously
stated - "moved to", "rescheduled", "postponed", "now due", "not the 28th",
"correction". Put the superseded value in references_old_value verbatim.

is_hearsay is true when the sender is relaying someone else - "I heard",
"someone said", "apparently", "they're saying".

Resolve relative dates against the message date in the input, whose weekday
is given. A weekday, with or without "this" or "next", means the next occurrence of it
strictly after the message date - never the message date itself, even when
the message was sent on that weekday. Count the days out one by one before answering - a deadline on
the wrong day is the worst failure this system has."""

MATCH_PROMPT = """\
You decide whether a newly extracted task refers to one the student already
has, so that corrections update the existing task instead of duplicating it.

Start from the assumption that a message about a course you already have a
task for is about THAT task. Students rarely announce two quizzes in one
course in the same week; they talk about the same one repeatedly.

UPDATE - the same real-world deliverable, described again with new or changed
detail. Different wording still counts: "the DBMS report", "DBMS Assignment
2" and "that database submission" are one task. So do vague mentions and
second-hand rumours - "don't forget the DBMS quiz", "I heard the DAA quiz
moved" refer to the quiz already on the list, not to new ones. A message
carrying no date at all is almost never a new task.

DUPLICATE - the same deliverable with nothing new to record. Reminders that
restate a date you already hold.

NEW - a genuinely distinct deliverable. Matching course and kind is strong
evidence of sameness, so choose NEW only when something actually
distinguishes them: a different number ("Assignment 2" vs "Assignment 3"), a
different unit or topic, or a date far outside the existing one's window.

Silently duplicating a task is the failure this step exists to prevent. When
course and kind both match and nothing distinguishes them, choose UPDATE.

Return task_id for UPDATE and DUPLICATE."""


@cache
def _agent(kind: str) -> Agent:
    if kind == "extract":
        return Agent(MODEL, output_type=Extraction, system_prompt=EXTRACT_PROMPT)
    return Agent(MODEL, output_type=MatchVerdict, system_prompt=MATCH_PROMPT)


def extract(text: str, meta: dict) -> Extraction:
    """Cached on the message body: extraction is a pure function of the text,
    so re-running the corpus after a reset costs nothing. On a free tier that
    is the difference between rehearsing the demo once and rehearsing it."""
    # The weekday is spelled out because models reliably miscount it.
    # "moved to Friday" was landing on a Saturday without this.
    day = date.fromisoformat(meta["received_at"][:10])
    prompt = (
        f"Message date: {day.isoformat()} ({day.strftime('%A')})\n"
        f"Channel: {meta['source']}\nSender: {meta['sender_role']}\n\n{text}"
    )
    # The system prompt is part of the key: tuning it must invalidate the
    # cache, or prompt changes silently have no effect.
    key = hashlib.sha256(f"{MODEL}|{EXTRACT_PROMPT}|{prompt}".encode()).hexdigest()
    store = _cache_load()
    if key in store:
        return Extraction(**store[key])

    result = _call(_agent("extract"), prompt)
    store[key] = result.model_dump()
    _cache_save(store)
    return result


def match(ex: Extraction, candidates: list) -> MatchVerdict:
    listing = "\n".join(
        f"- id={t['id']} | {t['title']} | course={t['course']} | kind={t['kind']}"
        f" | due={t['due_at'] or 'unknown'}"
        for t in candidates
    )
    prompt = (
        f"NEW EXTRACTION\n  title: {ex.title}\n  course: {ex.course}\n  kind: {ex.kind}\n"
        f"  due: {ex.due_at or 'unknown'}\n  correction: {ex.correction_signal}"
        f" (references {ex.references_old_value})\n\nEXISTING OPEN TASKS\n{listing}"
    )
    return _call(_agent("match"), prompt)
