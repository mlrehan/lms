"""Withdrawn assessments are invisible to every query, by one hook.

Deleting an assignment, quiz or exam sets `deleted_at` rather than removing the
row, so students' submissions, marks and transcripts are never cascaded away.
That only works if *every* read stops seeing the row -- listings, counts,
reports, the calendar feed, the grade-book sweep, the assistant's tools.
Thirty-odd queries each remembering a `deleted_at IS NULL` is thirty chances
to forget one, and forgetting is invisible: a withdrawn quiz quietly still
counted in a student's mark.

So the filter is attached once, to every ORM `SELECT` a session runs, with
`with_loader_criteria` -- the same "one hook, so no service has to remember"
choice the realtime topics made (`core/topics.py`).

Two things it deliberately does not touch:

* **Relationship loads.** `submission.assignment` must still load for a
  withdrawn assignment's submission, or every place that reads it would meet
  a `None` it was never written for. Top-level queries are what decide what
  is listed; a relationship is following a row that was already admitted.
* **Callers that ask for withdrawn rows** with
  `execution_options(include_withdrawn=True)` -- the permanent-deletion
  preview, an audit view.
"""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from backend.models.assignment import Assignment
from backend.models.exam import Exam
from backend.models.quiz import Quiz

WITHDRAWABLE = (Assignment, Quiz, Exam)


@event.listens_for(Session, "do_orm_execute")
def _hide_withdrawn(state: ORMExecuteState) -> None:
    if not state.is_select or state.is_relationship_load or state.is_column_load:
        return
    if state.execution_options.get("include_withdrawn"):
        return
    state.statement = state.statement.options(
        *(
            with_loader_criteria(model, model.deleted_at.is_(None), include_aliases=True)
            for model in WITHDRAWABLE
        )
    )
