"""Step 4: answering questions from stored rows.

One filter tool, the model fills its arguments and phrases the answer. Not
text-to-SQL - nothing here is grading query generation, and a filter function
cannot invent a row.
"""
import os
from functools import cache

from dotenv import load_dotenv
from pydantic_ai import Agent

import db

load_dotenv()

MODEL = os.environ.get("MODEL", "google:gemini-2.5-flash")

_conn = None

ANSWER_PROMPT = """\
You answer a student's questions about their deadlines using only find_tasks.

Today is {today}. Resolve relative ranges yourself and pass ISO dates: "this
week" is today through the coming Sunday, "next week" the Monday to Sunday
after that. Call find_tasks with include_undated=true whenever the question
could touch a task whose deadline nobody has stated.

Two rules you never break:

1. If a task's due date is null, say plainly that the deadline is not known
   and that it is flagged for confirmation. Never estimate, never say
   "probably", never fill the gap from the course's other deadlines.
2. If a task is flagged, say so and quote both competing values from
   conflict_note. The student decides which is right; you do not.

Answer in a few plain lines. Lead with what is due soonest. Name the course,
the deadline and the weightage where it is known. If nothing matches, say so
rather than widening the search."""


@cache
def _agent() -> Agent:
    agent = Agent(MODEL, system_prompt=ANSWER_PROMPT.format(today=db.now().isoformat()))

    @agent.tool_plain
    def find_tasks(
        course: str | None = None,
        due_after: str | None = None,
        due_before: str | None = None,
        only_flagged: bool = False,
        include_undated: bool = True,
    ) -> list[dict]:
        """Search stored tasks. Dates are ISO YYYY-MM-DD.

        include_undated keeps tasks whose deadline is unknown in the result
        even when a date range is given - they are exactly the ones a student
        is most likely to be blindsided by.
        """
        return find(_conn, course, due_after, due_before, only_flagged, include_undated)

    return agent


def find(conn, course=None, due_after=None, due_before=None,
         only_flagged=False, include_undated=True) -> list[dict]:
    sql = ["SELECT * FROM tasks WHERE status='open'"]
    args: list = []
    if course:
        sql.append("AND lower(course) LIKE lower(?)")
        args.append(f"%{course}%")
    if only_flagged:
        sql.append("AND needs_confirmation=1")
    if due_after or due_before:
        window = []
        if due_after:
            window.append("due_at >= ?")
            args.append(due_after)
        if due_before:
            window.append("due_at <= ?")
            args.append(due_before)
        clause = " AND ".join(window)
        # An undated task is never silently dropped by a date filter.
        sql.append(f"AND ({clause}{' OR due_at IS NULL' if include_undated else ''})")
    elif not include_undated:
        sql.append("AND due_at IS NOT NULL")
    sql.append("ORDER BY due_at IS NULL, due_at")

    rows = conn.execute(" ".join(sql), args).fetchall()
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "course": r["course"],
            "kind": r["kind"],
            "due_at": r["due_at"],
            "deadline_known": r["due_at"] is not None,
            "weightage": r["weightage"],
            "needs_confirmation": bool(r["needs_confirmation"]),
            "conflict_note": r["confirm_reason"],
        }
        for r in rows
    ]


def ask(conn, question: str) -> str:
    global _conn
    _conn = conn
    return _agent().run_sync(question).output
