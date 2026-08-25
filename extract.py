"""Step 1 (extract) and the model half of step 2 (match).

Both LLM calls live here so the resolver stays pure and testable.
"""
import hashlib
import json
import os
import time
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

is_task is FALSE for anything with no deliverable: social plans, logistics,
questions, complaints, greetings. Many of these mention a time ("football at
6?", "class at 9 tmrw?"). A time is not a deadline. Judge the intent, not the
presence of a date.

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

Resolve relative dates against the message date given in the input."""

MATCH_PROMPT = """\
You decide whether a newly extracted task refers to one the student already
has, so that corrections update the existing task instead of duplicating it.

UPDATE - the same real-world deliverable, described again with new or changed
detail. Different wording for the same thing still counts: "the DBMS report",
"DBMS Assignment 2" and "that database submission" are one task.

DUPLICATE - the same deliverable with nothing new. Reminders and forwards.

NEW - a genuinely different deliverable. Two quizzes in the same course are
different tasks. When unsure between NEW and UPDATE, choose NEW: a spurious
duplicate is a smaller harm than silently overwriting an unrelated deadline.

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
    prompt = (
        f"Message date: {meta['received_at']}\n"
        f"Channel: {meta['source']}\nSender: {meta['sender_role']}\n\n{text}"
    )
    key = hashlib.sha256(f"{MODEL}|{prompt}".encode()).hexdigest()
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
