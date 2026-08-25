"""Step 1 (extract) and the model half of step 2 (match).

Both LLM calls live here so the resolver stays pure and testable.
"""
import os
from functools import cache

from dotenv import load_dotenv
from pydantic_ai import Agent

import db
from models import Extraction, MatchVerdict

load_dotenv()

MODEL = os.environ.get("MODEL", "anthropic:claude-haiku-4-5-20251001")

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
    prompt = (
        f"Message date: {meta['received_at']}\n"
        f"Channel: {meta['source']}\nSender: {meta['sender_role']}\n\n{text}"
    )
    return _agent("extract").run_sync(prompt).output


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
    return _agent("match").run_sync(prompt).output
