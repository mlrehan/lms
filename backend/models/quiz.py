from datetime import datetime

from sqlalchemy import (Integer, String, ForeignKey, DateTime,
                        Enum as SQLEnum, Text, Numeric, JSON, Boolean)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List
from backend.models.base import Base, PublicIdMixin
from .helpers import bool_column, utc_datetime_column
from backend.utils.enums import AssessmentScope, AssessmentState, SubmissionState, QuestionType


class Quiz(Base, PublicIdMixin):
    """Spec §13."""
    __tablename__ = "quizzes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    course_id: Mapped[int] = mapped_column(Integer, ForeignKey("courses.id"), nullable=False)
    batch_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("batches.id", ondelete="CASCADE"), nullable=True
    )
    session_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("batch_sessions.id", ondelete="CASCADE"), nullable=True
    )
    # The same stored-not-inferred scope the assignments table uses. One shape
    # across all three assessment types is what §3 means by not duplicating the
    # implementation -- the eligibility resolver reads these three columns and
    # does not care which table they came from.
    scope: Mapped[AssessmentScope] = mapped_column(
        SQLEnum(AssessmentScope, name="assessment_scope", native_enum=False),
        nullable=False,
        default=AssessmentScope.COURSE,
        server_default=AssessmentScope.COURSE.value,
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    instructions: Mapped[Optional[str]] = mapped_column(Text)
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    attempts_allowed: Mapped[int] = mapped_column(Integer, default=1)
    passing_score: Mapped[Numeric] = mapped_column(Numeric(5, 2), nullable=False)  # e.g. 70.00
    # The paper's stated total, against which question marks are checked.
    # Nullable: a quiz written before this existed has no stated ceiling, and
    # inventing one from its current questions would both fabricate a
    # decision and start refusing the next question added to it.
    total_marks: Mapped[Optional[Numeric]] = mapped_column(Numeric(6, 2), nullable=True)
    shuffle_questions: Mapped[bool] = bool_column()
    is_auto_graded: Mapped[bool] = bool_column()
    # e.g. {"negative_marking": 0.25, "min_time": 10, "max_time": 60}
    grading_policy: Mapped[Optional[dict]] = mapped_column(JSON)
    is_published: Mapped[bool] = bool_column(default=False)
    # -- availability and result visibility (spec §9) -----------------------
    # A quiz that is published but not yet open is an ordinary thing to want,
    # and `is_published` alone could not express it.
    available_from: Mapped[Optional[datetime]] = utc_datetime_column(default=False)
    available_until: Mapped[Optional[datetime]] = utc_datetime_column(default=False)
    shuffle_answers: Mapped[bool] = bool_column(default=False)
    # Null means "every question". A pool draws this many at random from the
    # bank, which is what makes a reusable question bank worth having.
    questions_per_attempt: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    show_result_immediately: Mapped[bool] = bool_column(default=True)
    show_correct_answers: Mapped[bool] = bool_column(default=False)
    show_explanations: Mapped[bool] = bool_column(default=False)
    auto_submit_on_expiry: Mapped[bool] = bool_column(default=True)
    # When `show_result_immediately` is false, this is what the student is
    # waiting for: marking and releasing are separate acts (§14), exactly as
    # they are for assignments and exams. Null means "not released yet", so
    # every existing quiz keeps the behaviour it has today -- which is
    # `show_result_immediately=True`, released on marking.
    results_released_at: Mapped[Optional[datetime]] = utc_datetime_column(default=False)
    weight: Mapped[Numeric] = mapped_column(
        Numeric(6, 3), nullable=False, default=1, server_default="1"
    )

    course: Mapped["Course"] = relationship("Course", lazy="selectin")
    questions: Mapped[List["Question"]] = relationship(back_populates="quiz")
    attempts: Mapped[List["QuizAttempt"]] = relationship(back_populates="quiz")


class Question(Base, PublicIdMixin):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    quiz_id: Mapped[int] = mapped_column(Integer, ForeignKey("quizzes.id"), nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    question_type: Mapped[QuestionType] = mapped_column(SQLEnum(QuestionType, name="question_type", native_enum=False), nullable=False)
    points: Mapped[Numeric] = mapped_column(Numeric(5, 2), nullable=False)
    order: Mapped[int] = mapped_column(Integer)
    # e.g. {"language": "python", "test_cases": [...]}
    #
    # Also carries the answer key for the types whose key is not a set of
    # options: `{"accepted": [...], "case_sensitive": false}` for
    # FILL_BLANK, and `{"answer": 3.14, "tolerance": 0.01}` for NUMERIC.
    # Those shapes live here rather than in columns because they differ per
    # type, and a column per type would be null for every other question.
    settings: Mapped[Optional[dict]] = mapped_column(JSON)
    # Why the answer is the answer. Shown to a student only when the quiz
    # sets `show_explanations` *and* its results have been released -- which
    # is what made that setting unimplementable before: there was nothing to
    # show.
    explanation: Mapped[Optional[str]] = mapped_column(Text)

    quiz: Mapped["Quiz"] = relationship(back_populates="questions")
    options: Mapped[List["QuestionOption"]] = relationship(back_populates="question")
    answers: Mapped[List["QuizAnswer"]] = relationship(back_populates="question")


class QuestionOption(Base):
    __tablename__ = "question_options"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    question_id: Mapped[int] = mapped_column(Integer, ForeignKey("questions.id"), nullable=False)
    option_text: Mapped[str] = mapped_column(Text, nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    order: Mapped[int] = mapped_column(Integer)
    # MATCHING only: the right-hand item this left-hand prompt pairs with.
    # A pair is one row rather than two, so a half-deleted pair cannot
    # exist. ORDERING needs no extra column -- `order` already carries the
    # correct sequence, and the student is served a shuffled copy.
    match_text: Mapped[Optional[str]] = mapped_column(Text)

    question: Mapped["Question"] = relationship(back_populates="options")


class QuizAttempt(Base, PublicIdMixin):
    __tablename__ = "quiz_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    quiz_id: Mapped[int] = mapped_column(Integer, ForeignKey("quizzes.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    score: Mapped[Optional[Numeric]] = mapped_column(Numeric(5, 2))
    is_passed: Mapped[Optional[bool]] = bool_column(nullable=True)
    answers_json: Mapped[Optional[dict]] = mapped_column(JSON, comment="Alternative non-normalized storage")
    feedback: Mapped[Optional[str]] = mapped_column(Text)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # Set when the submission arrived after `started_at + quiz.duration_minutes`.
    # A late submission is still graded rather than discarded -- a network
    # blip must not destroy a student's work -- but without recording the
    # fact, `Quiz.duration_minutes` would be a decorative field: enforced
    # nowhere and invisible to the tutor reviewing the attempt.
    submitted_late: Mapped[bool] = bool_column(default=False)
    # Closed by the time limit rather than by the student (§9's
    # `auto_submit_on_expiry`). Distinct from `submitted_late`, which is the
    # opposite case: a quiz whose timer is advisory, submitted by hand after
    # the deadline. Recorded because "scored zero because they ran out of
    # time" and "scored zero because they answered wrongly" are different
    # facts, and a tutor looking at the attempt needs to tell them apart.
    auto_submitted: Mapped[bool] = bool_column(default=False)

    quiz: Mapped["Quiz"] = relationship(back_populates="attempts")
    student: Mapped["User"] = relationship(back_populates="quiz_attempts")
    answers: Mapped[List["QuizAnswer"]] = relationship(back_populates="attempt")


class QuizAnswer(Base):
    __tablename__ = "quiz_answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    attempt_id: Mapped[int] = mapped_column(Integer, ForeignKey("quiz_attempts.id"), nullable=False)
    question_id: Mapped[int] = mapped_column(Integer, ForeignKey("questions.id"), nullable=False)
    # Stores option id(s) for MCQ, or text for short-answer/essay
    selected_options: Mapped[Optional[dict]] = mapped_column(JSON, comment="Stores option IDs for MCQ or text for essay")
    score_awarded: Mapped[Optional[Numeric]] = mapped_column(Numeric(5, 2))

    attempt: Mapped["QuizAttempt"] = relationship(back_populates="answers")
    question: Mapped["Question"] = relationship(back_populates="answers")
