"""Typed contracts between the LLM and the resolver."""
from typing import Literal

from pydantic import BaseModel, Field

Kind = Literal["assignment", "quiz", "exam", "project", "lab", "registration", "other"]


class Extraction(BaseModel):
    """Step 1 output. is_task=False means noise - everything else is ignored."""

    is_task: bool = Field(description="False for chit-chat, logistics, or anything with no deliverable")
    reason: str = Field(description="One short line on why this is or isn't a task")

    title: str | None = None
    course: str | None = Field(default=None, description="Course code or name, e.g. DBMS, OS")
    kind: Kind | None = None
    weightage: str | None = Field(default=None, description="Verbatim, e.g. '20%', '10 marks'")

    due_at: str | None = Field(
        default=None,
        description="ISO date YYYY-MM-DD. NULL when no date is stated. Never infer one.",
    )
    due_precision: Literal["exact", "date_only", "unknown"] = "unknown"

    # Signals the resolver needs to tell a correction from a contradiction.
    correction_signal: bool = Field(
        default=False,
        description="True for 'moved to', 'rescheduled', 'not the 28th', 'updated'",
    )
    references_old_value: str | None = Field(
        default=None, description="The superseded value if quoted, e.g. '28th'"
    )
    is_hearsay: bool = Field(
        default=False, description="True for 'I heard', 'someone said', 'apparently'"
    )


class MatchVerdict(BaseModel):
    """Step 2 output: does this extraction belong to an existing task?"""

    decision: Literal["NEW", "UPDATE", "DUPLICATE"]
    task_id: int | None = Field(default=None, description="Required when decision is UPDATE or DUPLICATE")
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
