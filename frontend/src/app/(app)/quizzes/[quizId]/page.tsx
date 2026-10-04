"use client";

import Link from "next/link";
import { use, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Play, Plus, Trash2 } from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type {
  AttemptResponse,
  OptionInput,
  PageAttemptResponse,
  QuestionForAuthor,
  QuestionForStudent,
  QuestionType,
  QuizResponse,
} from "@/lib/api/types";
import { QuestionTypeValues } from "@/lib/api/types";
import { useApiMutation, useListState } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  Switch,
  Tabs,
  TabsList,
  TabsPanel,
  TabsTab,
} from "@/components/ui/primitives";
import { Column, DataTable, Pagination } from "@/components/ui/data-table";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, FormActions, FormGrid, Input, Textarea } from "@/components/ui/form";
import { Select, optionsFromValues } from "@/components/ui/select";
import { Stat, StatGrid } from "@/components/ui/stat";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime } from "@/lib/format/datetime";
import { humanise } from "@/lib/utils";

/** MCQ and true/false carry options; the written types do not. */
function needsOptions(type: QuestionType): boolean {
  return type === "MCQ_SINGLE" || type === "MCQ_MULTIPLE" || type === "TRUE_FALSE";
}

function QuestionEditor({
  quizId,
  open,
  onOpenChange,
}: {
  quizId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [text, setText] = useState("");
  const [type, setType] = useState<QuestionType>("MCQ_SINGLE");
  const [points, setPoints] = useState("1");
  const [options, setOptions] = useState<OptionInput[]>([
    { option_text: "", is_correct: true, order: 1 },
    { option_text: "", is_correct: false, order: 2 },
  ]);

  const create = useApiMutation<QuestionForAuthor, void>({
    mutationFn: () =>
      api.post<QuestionForAuthor>(`/quizzes/${segment(quizId)}/questions`, {
        body: {
          question_text: text,
          question_type: type,
          points: Number(points),
          options: needsOptions(type)
            ? options
                .filter((option) => option.option_text.trim() !== "")
                .map((option, index) => ({ ...option, order: index + 1 }))
            : undefined,
        },
      }),
    success: "Question added.",
    invalidate: [["quizzes"]],
    onSuccess: () => {
      setText("");
      setPoints("1");
      setOptions([
        { option_text: "", is_correct: true, order: 1 },
        { option_text: "", is_correct: false, order: 2 },
      ]);
      onOpenChange(false);
    },
  });

  function setTrueFalse() {
    setOptions([
      { option_text: "True", is_correct: true, order: 1 },
      { option_text: "False", is_correct: false, order: 2 },
    ]);
  }

  const valid =
    text.trim() !== "" &&
    (!needsOptions(type) ||
      (options.filter((option) => option.option_text.trim() !== "").length >= 2 &&
        options.some((option) => option.is_correct)));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg">
        <DialogHeader
          title="Add a question"
          description="Options are stored with their answer key. Students receive a shape that has no `is_correct` field at all -- it is absent, not hidden."
        />
        <div className="space-y-4">
          <Field label="Question" required>
            {({ id }) => (
              <Textarea id={id} value={text} onChange={(event) => setText(event.target.value)} />
            )}
          </Field>
          <FormGrid>
            <Field label="Type">
              {({ id }) => (
                <Select
                  id={id}
                  value={type}
                  onValueChange={(value) => {
                    // The question type is required, so a cleared value is
                    // simply ignored rather than written back as null.
                    if (!value) return;
                    const chosen = value as QuestionType;
                    setType(chosen);
                    if (chosen === "TRUE_FALSE") setTrueFalse();
                  }}
                 options={optionsFromValues(QuestionTypeValues, humanise)} />
              )}
            </Field>
            <Field label="Points">
              {({ id }) => (
                <Input
                  id={id}
                  type="number"
                  min={0}
                  step="0.5"
                  value={points}
                  onChange={(event) => setPoints(event.target.value)}
                />
              )}
            </Field>
          </FormGrid>

          {needsOptions(type) ? (
            <div className="space-y-2">
              <p className="text-sm font-medium">Options</p>
              {options.map((option, index) => (
                <div key={index} className="flex items-center gap-2">
                  <input
                    type={type === "MCQ_MULTIPLE" ? "checkbox" : "radio"}
                    name="correct-option"
                    className="size-4 accent-[var(--primary)]"
                    aria-label={`Option ${index + 1} is correct`}
                    checked={option.is_correct ?? false}
                    onChange={(event) =>
                      setOptions((previous) =>
                        previous.map((item, position) =>
                          position === index
                            ? { ...item, is_correct: event.target.checked }
                            : type === "MCQ_MULTIPLE"
                              ? item
                              : { ...item, is_correct: false },
                        ),
                      )
                    }
                  />
                  <Input
                    value={option.option_text}
                    placeholder={`Option ${index + 1}`}
                    disabled={type === "TRUE_FALSE"}
                    onChange={(event) =>
                      setOptions((previous) =>
                        previous.map((item, position) =>
                          position === index ? { ...item, option_text: event.target.value } : item,
                        ),
                      )
                    }
                  />
                  {type !== "TRUE_FALSE" && options.length > 2 ? (
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Remove option ${index + 1}`}
                      onClick={() =>
                        setOptions((previous) => previous.filter((_, position) => position !== index))
                      }
                    >
                      <Trash2 />
                    </Button>
                  ) : null}
                </div>
              ))}
              {type !== "TRUE_FALSE" ? (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() =>
                    setOptions((previous) => [
                      ...previous,
                      { option_text: "", is_correct: false, order: previous.length + 1 },
                    ])
                  }
                >
                  <Plus /> Add option
                </Button>
              ) : null}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              {humanise(type)} answers are marked by a person; there is no answer key to enter.
            </p>
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button loading={create.isPending} disabled={!valid} onClick={() => create.mutate()}>
            Add question
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function QuestionsTab({ quiz }: { quiz: QuizResponse }) {
  const { permissions } = useSession();
  const isAuthor = permissions.has("quiz.update");
  const [addOpen, setAddOpen] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);

  const authorView = useQuery({
    queryKey: ["quizzes", quiz.public_id, "answer-key"],
    queryFn: () => api.get<QuestionForAuthor[]>(`/quizzes/${segment(quiz.public_id)}/answer-key`),
    enabled: isAuthor,
  });

  const studentView = useQuery({
    queryKey: ["quizzes", quiz.public_id, "questions"],
    queryFn: () => api.get<QuestionForStudent[]>(`/quizzes/${segment(quiz.public_id)}/questions`),
    enabled: !isAuthor,
  });

  const remove = useApiMutation<void, string>({
    mutationFn: (questionId) => api.delete<void>(`/questions/${segment(questionId)}`),
    success: "Question removed.",
    invalidate: [["quizzes"]],
    onSuccess: () => setRemoving(null),
  });

  const query = isAuthor ? authorView : studentView;
  const questions: (QuestionForAuthor | QuestionForStudent)[] = isAuthor
    ? (authorView.data ?? [])
    : (studentView.data ?? []);

  return (
    <Card>
      <CardHeader
        title={isAuthor ? "Questions and answer key" : "Questions"}
        description={
          isAuthor
            ? "The answer key is only reachable with quiz.update. The student endpoint returns a shape with no correctness field."
            : "Correct answers are not part of this response."
        }
        actions={
          isAuthor ? (
            <Button size="sm" onClick={() => setAddOpen(true)}>
              <Plus /> Add question
            </Button>
          ) : null
        }
      />
      {query.isPending ? (
        <LoadingState />
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : questions.length === 0 ? (
        <CardBody>
          <p className="text-sm text-muted-foreground">
            No questions yet.{" "}
            {isAuthor ? "Add some before publishing -- an empty quiz cannot be attempted." : null}
          </p>
        </CardBody>
      ) : (
        <ol className="divide-y divide-border-subtle">
          {questions.map((question, index) => (
            <li key={question.public_id} className="space-y-2 px-4 py-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-medium">
                    <span className="mr-2 text-muted-foreground">{index + 1}.</span>
                    {question.question_text}
                  </p>
                  <p className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                    <Badge tone="neutral">{humanise(question.question_type)}</Badge>
                    {question.points} point{question.points === "1" ? "" : "s"}
                  </p>
                </div>
                {isAuthor ? (
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label="Remove question"
                    onClick={() => setRemoving(question.public_id)}
                  >
                    <Trash2 className="text-danger" />
                  </Button>
                ) : null}
              </div>
              {question.options && question.options.length > 0 ? (
                <ul className="ml-6 space-y-1">
                  {question.options.map((option) => (
                    <li key={option.id} className="flex items-center gap-2 text-sm">
                      <span
                        className={
                          "is_correct" in option && option.is_correct
                            ? "font-medium text-success"
                            : "text-muted-foreground"
                        }
                      >
                        {option.option_text}
                      </span>
                      {"is_correct" in option && option.is_correct ? (
                        <Badge tone="success">Correct</Badge>
                      ) : null}
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          ))}
        </ol>
      )}

      <QuestionEditor quizId={quiz.public_id} open={addOpen} onOpenChange={setAddOpen} />

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => (open ? null : setRemoving(null))}
        destructive
        title="Remove this question?"
        description="Attempts that already answered it keep their recorded score."
        confirmLabel="Remove question"
        pending={remove.isPending}
        onConfirm={() => {
          if (removing) remove.mutate(removing);
        }}
      />
    </Card>
  );
}

function GradeAttemptDialog({
  attempt,
  onClose,
}: {
  attempt: AttemptResponse | null;
  onClose: () => void;
}) {
  const [scores, setScores] = useState<Record<string, string>>({});
  const [feedback, setFeedback] = useState("");

  const grade = useApiMutation<AttemptResponse, void>({
    mutationFn: () =>
      api.put<AttemptResponse>(`/attempts/${segment(attempt!.public_id)}/grade`, {
        body: {
          answers: Object.entries(scores)
            .filter(([, value]) => value !== "")
            .map(([question_id, value]) => ({ question_id, score_awarded: Number(value) })),
          feedback: feedback || null,
        },
      }),
    success: "Attempt graded.",
    invalidate: [["attempts"], ["quizzes"], ["gradebook"]],
    onSuccess: () => {
      setScores({});
      setFeedback("");
      onClose();
    },
  });

  return (
    <Dialog
      open={attempt !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent size="lg">
        <DialogHeader
          title={`Grade ${attempt?.student_username ?? "attempt"}`}
          description="Only the answers auto-grading could not mark need a score here."
        />
        <div className="space-y-3">
          {(attempt?.answers ?? []).map((answer) => (
            <div key={answer.question_id} className="rounded-lg border border-border-subtle p-3">
              <p className="text-sm font-medium">{answer.question_text ?? answer.question_id}</p>
              <p className="mt-1 whitespace-pre-wrap break-words text-sm text-muted-foreground">
                {typeof answer.selected_options === "string"
                  ? answer.selected_options
                  : JSON.stringify(answer.selected_options)}
              </p>
              <div className="mt-2 flex items-center gap-2">
                <label className="text-xs text-muted-foreground" htmlFor={`score-${answer.question_id}`}>
                  Score
                </label>
                <Input
                  id={`score-${answer.question_id}`}
                  className="w-28"
                  type="number"
                  step="0.5"
                  min={0}
                  value={scores[answer.question_id] ?? answer.score_awarded ?? ""}
                  onChange={(event) =>
                    setScores((previous) => ({ ...previous, [answer.question_id]: event.target.value }))
                  }
                />
              </div>
            </div>
          ))}
          <Field label="Feedback">
            {({ id }) => (
              <Textarea id={id} value={feedback} onChange={(event) => setFeedback(event.target.value)} />
            )}
          </Field>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button loading={grade.isPending} onClick={() => grade.mutate()}>
            Save grades
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function AttemptsTab({ quiz }: { quiz: QuizResponse }) {
  const { permissions } = useSession();
  const timeZone = useDisplayTimeZone();
  const { limit, offset, setPage } = useListState(25);
  const [grading, setGrading] = useState<AttemptResponse | null>(null);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["attempts", quiz.public_id, limit, offset],
    queryFn: () =>
      api.get<PageAttemptResponse>("/attempts", {
        query: { quiz_id: quiz.public_id, limit, offset },
      }),
  });

  const columns: Column<AttemptResponse>[] = [
    {
      key: "student",
      header: "Student",
      cell: (row) => (
        <Link href={`/users/${row.student_id}`} className="font-medium hover:underline">
          {row.student_username ?? row.student_id}
        </Link>
      ),
    },
    {
      key: "attempt",
      header: "Attempt",
      align: "right",
      secondary: true,
      cell: (row) => <span className="tabular-nums">#{row.attempt_number}</span>,
    },
    {
      key: "finished",
      header: "Finished",
      cell: (row) =>
        row.finished_at ? (
          <span className="flex items-center gap-2">
            {formatDateTime(row.finished_at, { timeZone })}
            {row.submitted_late ? <Badge tone="warning">Late</Badge> : null}
          </span>
        ) : (
          <Badge tone="info">In progress</Badge>
        ),
    },
    {
      key: "score",
      header: "Score",
      align: "right",
      cell: (row) =>
        row.awaiting_manual_grading ? (
          <Badge tone="warning">Needs marking</Badge>
        ) : row.score === null || row.score === undefined ? (
          <span className="text-muted-foreground">—</span>
        ) : (
          <span className="tabular-nums font-medium">
            {row.score}
            {row.is_passed === true ? (
              <Badge tone="success" className="ml-2">
                Pass
              </Badge>
            ) : row.is_passed === false ? (
              <Badge tone="danger" className="ml-2">
                Fail
              </Badge>
            ) : null}
          </span>
        ),
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      cell: (row) =>
        permissions.has("quiz.grade") && row.finished_at ? (
          <Button
            variant="secondary"
            size="sm"
            onClick={async () => {
              // The list response carries answers only sometimes; fetching the
              // single attempt guarantees the grader sees what was written.
              const full = await api.get<AttemptResponse>(`/attempts/${segment(row.public_id)}`);
              setGrading(full);
            }}
          >
            {row.awaiting_manual_grading ? "Mark" : "Re-mark"}
          </Button>
        ) : null,
    },
  ];

  return (
    <Card>
      <CardHeader title="Attempts" />
      {isPending ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : (
        <>
          <DataTable
              columnsKey="quiz-attempts"
            columns={columns}
            rows={data?.items ?? []}
            rowKey={(row) => row.public_id}
            emptyMessage="Nobody has attempted this quiz."
          />
          <Pagination
            total={data?.total ?? 0}
            limit={limit}
            offset={offset}
            onChange={setPage}
            label="attempts"
          />
        </>
      )}
      <GradeAttemptDialog attempt={grading} onClose={() => setGrading(null)} />
    </Card>
  );
}

function TakeQuizPanel({ quiz }: { quiz: QuizResponse }) {
  const [attempt, setAttempt] = useState<AttemptResponse | null>(null);
  const [answers, setAnswers] = useState<Record<string, { options: number[]; text: string }>>({});

  const questions = useQuery({
    queryKey: ["quizzes", quiz.public_id, "questions"],
    queryFn: () => api.get<QuestionForStudent[]>(`/quizzes/${segment(quiz.public_id)}/questions`),
    enabled: attempt !== null,
  });

  const start = useApiMutation<AttemptResponse, void>({
    mutationFn: () => api.post<AttemptResponse>(`/quizzes/${segment(quiz.public_id)}/attempts`),
    success: "Attempt started.",
    invalidate: [["quizzes"]],
    onSuccess: (created) => setAttempt(created),
  });

  const submit = useApiMutation<AttemptResponse, void>({
    mutationFn: () =>
      api.post<AttemptResponse>(`/attempts/${segment(attempt!.public_id)}/submit`, {
        body: {
          answers: Object.entries(answers).map(([question_id, value]) => ({
            question_id,
            selected_option_ids: value.options.length > 0 ? value.options : null,
            text_answer: value.text || null,
          })),
        },
      }),
    success: "Attempt submitted.",
    invalidate: [["attempts"], ["quizzes"], ["dashboard"]],
    onSuccess: (result) => setAttempt(result),
  });

  const attemptsLeft = quiz.attempts_allowed - (quiz.my_attempts_used ?? 0);

  if (!attempt) {
    return (
      <Card>
        <CardHeader
          title="Take this quiz"
          description={
            quiz.duration_minutes
              ? `${quiz.duration_minutes} minutes once started. ${attemptsLeft} attempt(s) left.`
              : `Untimed. ${attemptsLeft} attempt(s) left.`
          }
        />
        <CardBody className="space-y-3">
          {quiz.instructions ? (
            <p className="whitespace-pre-wrap break-words rounded-lg border border-border-subtle bg-surface-muted p-3 text-sm">
              {quiz.instructions}
            </p>
          ) : null}
          <Button
            loading={start.isPending}
            disabled={!quiz.is_published || attemptsLeft <= 0}
            onClick={() => start.mutate()}
          >
            <Play /> Start attempt
          </Button>
          {!quiz.is_published ? (
            <p className="text-sm text-muted-foreground">This quiz is not published yet.</p>
          ) : attemptsLeft <= 0 ? (
            <p className="text-sm text-muted-foreground">You have used all your attempts.</p>
          ) : null}
        </CardBody>
      </Card>
    );
  }

  if (attempt.finished_at) {
    return (
      <Card>
        <CardHeader title="Attempt submitted" />
        <CardBody>
          <StatGrid>
            <Stat label="Score" value={attempt.score ?? null} />
            <Stat
              label="Outcome"
              value={
                attempt.awaiting_manual_grading
                  ? "Awaiting marking"
                  : attempt.is_passed === true
                    ? "Passed"
                    : attempt.is_passed === false
                      ? "Not passed"
                      : null
              }
            />
          </StatGrid>
          {attempt.feedback ? (
            <p className="mt-3 whitespace-pre-wrap break-words text-sm">{attempt.feedback}</p>
          ) : null}
        </CardBody>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader title="Your attempt" description="Answer every question, then submit once." />
      {questions.isPending ? (
        <LoadingState />
      ) : questions.error ? (
        <ErrorState error={questions.error} onRetry={() => void questions.refetch()} />
      ) : (
        <>
          <CardBody className="space-y-4">
            {(questions.data ?? []).map((question, index) => {
              const value = answers[question.public_id] ?? { options: [], text: "" };
              return (
                <div key={question.public_id} className="rounded-lg border border-border-subtle p-3">
                  <p className="text-sm font-medium">
                    <span className="mr-2 text-muted-foreground">{index + 1}.</span>
                    {question.question_text}
                  </p>
                  {question.options && question.options.length > 0 ? (
                    <ul className="mt-2 space-y-1">
                      {question.options.map((option) => (
                        <li key={option.id}>
                          <label className="flex items-center gap-2 text-sm">
                            <input
                              type={question.question_type === "MCQ_MULTIPLE" ? "checkbox" : "radio"}
                              name={`q-${question.public_id}`}
                              className="size-4 accent-[var(--primary)]"
                              checked={value.options.includes(option.id)}
                              onChange={(event) =>
                                setAnswers((previous) => ({
                                  ...previous,
                                  [question.public_id]: {
                                    text: value.text,
                                    options:
                                      question.question_type === "MCQ_MULTIPLE"
                                        ? event.target.checked
                                          ? [...value.options, option.id]
                                          : value.options.filter((id) => id !== option.id)
                                        : [option.id],
                                  },
                                }))
                              }
                            />
                            {option.option_text}
                          </label>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <Textarea
                      className="mt-2"
                      rows={question.question_type === "ESSAY" ? 6 : 2}
                      aria-label={`Answer to question ${index + 1}`}
                      value={value.text}
                      onChange={(event) =>
                        setAnswers((previous) => ({
                          ...previous,
                          [question.public_id]: { options: value.options, text: event.target.value },
                        }))
                      }
                    />
                  )}
                </div>
              );
            })}
          </CardBody>
          <div className="border-t border-border-subtle px-4 py-3">
            <FormActions>
              <Button loading={submit.isPending} onClick={() => submit.mutate()}>
                Submit attempt
              </Button>
            </FormActions>
          </div>
        </>
      )}
    </Card>
  );
}

export default function QuizDetailPage({ params }: { params: Promise<{ quizId: string }> }) {
  const { quizId } = use(params);
  const router = useRouter();
  const { permissions } = useSession();
  const [confirmDelete, setConfirmDelete] = useState(false);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["quizzes", "detail", quizId],
    queryFn: () => api.get<QuizResponse>(`/quizzes/${segment(quizId)}`),
  });

  const publish = useApiMutation<QuizResponse, boolean>({
    mutationFn: (isPublished) =>
      api.put<QuizResponse>(`/quizzes/${segment(quizId)}/publish`, {
        body: { is_published: isPublished },
      }),
    success: "Quiz updated.",
    invalidate: [["quizzes"]],
  });

  const remove = useApiMutation<void, void>({
    mutationFn: () => api.delete<void>(`/quizzes/${segment(quizId)}`),
    success: "Quiz deleted.",
    invalidate: [["quizzes"]],
    onSuccess: () => router.push("/quizzes"),
  });

  if (isPending) return <LoadingState rows={6} />;
  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;
  if (!data) return null;

  const canAttempt = permissions.has("quiz.attempt");
  const canSeeAttempts = permissions.has("grade.read");

  return (
    <div className="space-y-5">
      <PageHeader
        breadcrumbs={[
          { label: "Quizzes", href: "/quizzes" },
          ...(data.course_title ? [{ label: data.course_title, href: `/courses/${data.course_id}` }] : []),
          { label: data.title },
        ]}
        title={data.title}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <Badge tone={data.is_published ? "success" : "neutral"}>
              {data.is_published ? "Published" : "Draft"}
            </Badge>
            <Badge tone="neutral">{data.question_count ?? 0} questions</Badge>
            <Badge tone="neutral">{data.total_points ?? "0"} points</Badge>
            <span className="text-xs">
              Pass at {data.passing_score} · {data.attempts_allowed} attempt(s) ·{" "}
              {data.duration_minutes ? `${data.duration_minutes} min` : "untimed"}
            </span>
          </span>
        }
        actions={
          <div className="flex items-center gap-3">
            {permissions.has("quiz.update") ? (
              <label className="flex items-center gap-2 text-sm">
                <Switch
                  checked={data.is_published}
                  disabled={publish.isPending}
                  onCheckedChange={(checked) => publish.mutate(checked)}
                />
                Published
              </label>
            ) : null}
            {permissions.has("quiz.delete") ? (
              <Button
                variant="ghost"
                size="icon"
                aria-label="Delete quiz"
                onClick={() => setConfirmDelete(true)}
              >
                <Trash2 className="text-danger" />
              </Button>
            ) : null}
          </div>
        }
      />

      <Tabs defaultValue="questions">
        <TabsList>
          <TabsTab value="questions">Questions</TabsTab>
          {canSeeAttempts ? <TabsTab value="attempts">Attempts</TabsTab> : null}
          {canAttempt ? <TabsTab value="take">Take it</TabsTab> : null}
        </TabsList>
        <TabsPanel value="questions">
          <QuestionsTab quiz={data} />
        </TabsPanel>
        {canSeeAttempts ? (
          <TabsPanel value="attempts">
            <AttemptsTab quiz={data} />
          </TabsPanel>
        ) : null}
        {canAttempt ? (
          <TabsPanel value="take">
            <TakeQuizPanel quiz={data} />
          </TabsPanel>
        ) : null}
      </Tabs>

      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        destructive
        title="Delete this quiz?"
        description="Its questions and every attempt go with it."
        confirmPhrase={data.title}
        confirmLabel="Delete quiz"
        pending={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </div>
  );
}
