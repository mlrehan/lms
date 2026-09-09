from datetime import datetime

from sqlalchemy import (Integer, String, ForeignKey, DateTime,
                        Enum as SQLEnum, Text, Numeric, JSON, Boolean)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List
from backend.models.base import Base, PublicIdMixin
from .helpers import bool_column
from backend.utils.enums import QuestionType


class Quiz(Base, PublicIdMixin):
    """Spec §13."""
    __tablename__ = "quizzes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    course_id: Mapped[int] = mapped_column(Integer, ForeignKey("courses.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    instructions: Mapped[Optional[str]] = mapped_column(Text)
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    attempts_allowed: Mapped[int] = mapped_column(Integer, default=1)
    passing_score: Mapped[Numeric] = mapped_column(Numeric(5, 2), nullable=False)  # e.g. 70.00
    shuffle_questions: Mapped[bool] = bool_column()
    is_auto_graded: Mapped[bool] = bool_column()
    # e.g. {"negative_marking": 0.25, "min_time": 10, "max_time": 60}
    grading_policy: Mapped[Optional[dict]] = mapped_column(JSON)
    is_published: Mapped[bool] = bool_column(default=False)

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
    settings: Mapped[Optional[dict]] = mapped_column(JSON)

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
