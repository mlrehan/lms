"use client";

import Link from "next/link";
import { use, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Play, Plus, Trash2 } from "lucide-react";
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
import { MatchingAnswer, OrderingAnswer, swap } from "@/components/domain/quiz-answers";
import { useSession } from "@/lib/auth/session";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime } from "@/lib/format/datetime";
import { cn, humanise } from "@/lib/utils";
import { RichText, RichTextEditor } from "@/components/domain/rich-text";

/**
 * What shape of answer key each question type needs.
 *
 * Four kinds, and the distinction matters because "machine-marked" and
 * "has options" stopped being the same thing: fill-in-the-blank and numeric
 * are marked automatically from a key kept in `settings`, and ordering and
 * matching have options that are the *material* rather than the key.
 */
const CHOICE_TYPES: QuestionType[] = ["MCQ_SINGLE", "MCQ_MULTIPLE", "TRUE_FALSE"];

/**
 * Names a tutor would recognise.
 *
 * `humanise` turns the enum into "Fill Blank" and "Mcq Single", which are
 * not the names anybody calls these. Only the types it gets wrong are
 * listed; everything else falls through to `humanise`, so a type added to
 * the backend still appears in the picker rather than vanishing from it.
 */
const QUESTION_TYPE_LABELS: Partial<Record<QuestionType, string>> = {
  MCQ_SINGLE: "Multiple choice (one answer)",
  MCQ_MULTIPLE: "Multiple choice (several answers)",
  TRUE_FALSE: "True or false",
  SHORT_ANSWER: "Short answer",
  FILL_BLANK: "Fill in the blank",
  NUMERIC: "Numeric answer",
};

/**
 * The answer key for the two types that keep theirs in `settings`.
 *
 * Returns nothing for every other type, including for a student's copy of a
 * question -- the server strips those fields out of what it serves them, so
 * there is nothing here to leak even if this were rendered on the wrong
 * screen.
 */
function answerKeyLine(question: QuestionForAuthor | QuestionForStudent): string | null {
  const settings = (question.settings ?? {}) as Record<string, unknown>;
  if (question.question_type === "FILL_BLANK") {
    const accepted = Array.isArray(settings.accepted) ? (settings.accepted as unknown[]) : [];
    return accepted.length > 0 ? accepted.map(String).join(" / ") : null;
  }
  if (question.question_type === "NUMERIC") {
    if (settings.answer === undefined || settings.answer === null) return null;
    const tolerance = settings.tolerance;
    return tolerance ? `${String(settings.answer)} ± ${String(tolerance)}` : String(settings.answer);
  }
  return null;
}

function questionTypeLabel(type: string): string {
  return QUESTION_TYPE_LABELS[type as QuestionType] ?? humanise(type);
}

/** Options with a correctness flag. */
function isChoice(type: QuestionType): boolean {
  return CHOICE_TYPES.includes(type);
}

/** Options, but `is_correct` means nothing — the order or the pairing is the key. */
function isSequence(type: QuestionType): boolean {
  return type === "ORDERING" || type === "MATCHING";
}

/** No options at all; the key lives in `settings`. */
function isKeyed(type: QuestionType): boolean {
  return type === "FILL_BLANK" || type === "NUMERIC";
}

function needsOptions(type: QuestionType): boolean {
  return isChoice(type) || isSequence(type);
}

/** Marked by a person, with no key to enter. */
function isWritten(type: QuestionType): boolean {
  return type === "SHORT_ANSWER" || type === "ESSAY";
}

/**
 * The option rows a type starts with.
 *
 * One function rather than three `setX` helpers, because the type picker and
 * the reset after a save both have to answer this question and were answering
 * it differently: saving a True/False question left the type on True/False
 * and replaced its options with two blank rows, so the next question was a
 * true/false with nothing to choose between.
 */
function optionsFor(type: QuestionType): OptionInput[] {
  if (type === "TRUE_FALSE") {
    return [
      { option_text: "True", is_correct: true, order: 1 },
      { option_text: "False", is_correct: false, order: 2 },
    ];
  }
  if (type === "MATCHING") {
    return [
      { option_text: "", match_text: "", is_correct: false, order: 1 },
      { option_text: "", match_text: "", is_correct: false, order: 2 },
    ];
  }
  return [
    { option_text: "", is_correct: true, order: 1 },
    { option_text: "", is_correct: false, order: 2 },
  ];
}

/** What an option row is called. True/False rows are named, not numbered. */
function optionLabel(type: QuestionType, index: number): string {
  if (type === "TRUE_FALSE") return index === 0 ? "True" : "False";
  return `Option ${index + 1}`;
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
  const [explanation, setExplanation] = useState("");
  // Fill-in-the-blank: one accepted answer per line, so a tutor can add
  // spellings and synonyms without a repeating field group.
  const [accepted, setAccepted] = useState("");
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [numericAnswer, setNumericAnswer] = useState("");
  const [tolerance, setTolerance] = useState("");
  const [options, setOptions] = useState<OptionInput[]>(() => optionsFor("MCQ_SINGLE"));

  const acceptedList = accepted
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line !== "");

  function keyedSettings(): Record<string, unknown> | undefined {
    if (type === "FILL_BLANK") {
      return { accepted: acceptedList, case_sensitive: caseSensitive };
    }
    if (type === "NUMERIC") {
      return {
        answer: numericAnswer,
        // Omitted rather than zero when blank: the server reads a missing
        // tolerance as exact, and sending `0` says the same thing with a
        // number somebody later has to interpret.
        ...(tolerance.trim() === "" ? {} : { tolerance: tolerance.trim() }),
      };
    }
    return undefined;
  }

  // Which button was pressed. A tutor entering twenty questions should not
  // have to reopen the dialog twenty times, and the difference between the
  // two actions is only what happens after the save succeeds.
  const [keepOpen, setKeepOpen] = useState(false);

  const create = useApiMutation<QuestionForAuthor, void>({
    mutationFn: () =>
      api.post<QuestionForAuthor>(`/quizzes/${segment(quizId)}/questions`, {
        body: {
          question_text: text,
          question_type: type,
          points: Number(points),
          explanation: explanation.trim() || null,
          settings: keyedSettings(),
          options: needsOptions(type)
            ? options
                .filter((option) => option.option_text.trim() !== "")
                // `order` is reassigned from the list position, which is the
                // answer for an ORDERING question: the row a tutor dragged to
                // the top is position 1, and a stale stored order would make
                // the key disagree with what they see.
                .map((option, index) => ({
                  ...option,
                  order: index + 1,
                  match_text: type === "MATCHING" ? (option.match_text ?? "") : null,
                }))
            : undefined,
        },
      }),
    success: "Question added.",
    invalidate: [["quizzes"]],
    onSuccess: () => {
      setText("");
      setExplanation("");
      setAccepted("");
      setCaseSensitive(false);
      setNumericAnswer("");
      setTolerance("");
      // The type and its point value are kept: a tutor writing a paper is
      // usually writing ten of the same kind, and re-choosing both every
      // time is the friction "add another" exists to remove. The options are
      // re-seeded *for that type*, which is what makes keeping it safe.
      setOptions(optionsFor(type));
      if (!keepOpen) onOpenChange(false);
    },
  });

  const filled = options.filter((option) => option.option_text.trim() !== "");
  // The same rules the server applies (`answer_key_problem`), so the button
  // is dead rather than the request refused -- but the server stays the
  // authority, and its message is what a mismatch shows.
  const valid =
    text.trim() !== "" &&
    (isChoice(type)
      ? filled.length >= 2 && options.some((option) => option.is_correct)
      : type === "ORDERING"
        ? filled.length >= 2
        : type === "MATCHING"
          ? filled.length >= 2 &&
            filled.every((option) => (option.match_text ?? "").trim() !== "") &&
            new Set(filled.map((option) => option.option_text.trim())).size === filled.length
          : type === "FILL_BLANK"
            ? acceptedList.length > 0
            : type === "NUMERIC"
              ? numericAnswer.trim() !== "" && !Number.isNaN(Number(numericAnswer))
              : true);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg">
        <DialogHeader
          title="Add a question"
          description="Options are stored with their answer key. Students receive a shape that has no `is_correct` field at all -- it is absent, not hidden."
        />
        <div className="space-y-4">
          <Field
            label="Question"
            required
            hint="Tables and code blocks are kept. Styling and scripts are stripped on save."
          >
            {() => (
              <RichTextEditor
                ariaLabel="Question"
                placeholder="What are you asking?"
                value={text}
                onChange={setText}
              />
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
                    // Re-seed only when the *shape* changes. Moving between
                    // two ordinary choice types keeps what has been typed;
                    // leaving True/False behind would otherwise ship a
                    // multiple-choice question whose options are True and
                    // False.
                    if (chosen === "TRUE_FALSE" || chosen === "MATCHING" ||
                        type === "TRUE_FALSE" || type === "MATCHING") {
                      setOptions(optionsFor(chosen));
                    }
                  }}
                 options={optionsFromValues(QuestionTypeValues, questionTypeLabel)} />
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

          {isKeyed(type) ? (
            <div className="space-y-3 rounded-lg border border-border-subtle p-3">
              {type === "FILL_BLANK" ? (
                <>
                  <Field
                    label="Accepted answers"
                    hint="One per line. Spacing and capitals are ignored when marking, so you only need genuinely different answers."
                    required
                  >
                    {({ id }) => (
                      <Textarea
                        id={id}
                        rows={3}
                        value={accepted}
                        placeholder={"Paris\nCity of Paris"}
                        onChange={(event) => setAccepted(event.target.value)}
                      />
                    )}
                  </Field>
                  <label className="flex items-center gap-3 text-sm">
                    <Switch checked={caseSensitive} onCheckedChange={setCaseSensitive} />
                    <span>
                      The capitals matter
                      <span className="block text-xs text-muted-foreground">
                        For a chemical symbol or an identifier, where Na and NA are different
                        answers.
                      </span>
                    </span>
                  </label>
                </>
              ) : (
                <FormGrid>
                  <Field label="Correct answer" required>
                    {({ id }) => (
                      <Input
                        id={id}
                        value={numericAnswer}
                        inputMode="decimal"
                        placeholder="3.14"
                        onChange={(event) => setNumericAnswer(event.target.value)}
                      />
                    )}
                  </Field>
                  <Field label="Tolerance" hint="Blank means it must be exact.">
                    {({ id }) => (
                      <Input
                        id={id}
                        value={tolerance}
                        inputMode="decimal"
                        placeholder="0.01"
                        onChange={(event) => setTolerance(event.target.value)}
                      />
                    )}
                  </Field>
                </FormGrid>
              )}
            </div>
          ) : null}

          {type === "ORDERING" ? (
            <div className="space-y-2">
              <p className="text-sm font-medium">
                Items, in the correct order
                <span className="ml-2 font-normal text-xs text-muted-foreground">
                  Students are shown them scrambled.
                </span>
              </p>
              {options.map((option, index) => (
                <div key={index} className="flex items-center gap-2">
                  <span className="w-6 text-right text-xs tabular-nums text-muted-foreground">
                    {index + 1}.
                  </span>
                  <Input
                    value={option.option_text}
                    placeholder={`Item ${index + 1}`}
                    onChange={(event) =>
                      setOptions((previous) =>
                        previous.map((item, position) =>
                          position === index ? { ...item, option_text: event.target.value } : item,
                        ),
                      )
                    }
                  />
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Move item ${index + 1} up`}
                    disabled={index === 0}
                    onClick={() => setOptions((previous) => swap(previous, index, index - 1))}
                  >
                    <ArrowUp />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Move item ${index + 1} down`}
                    disabled={index === options.length - 1}
                    onClick={() => setOptions((previous) => swap(previous, index, index + 1))}
                  >
                    <ArrowDown />
                  </Button>
                  {options.length > 2 ? (
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Remove item ${index + 1}`}
                      onClick={() =>
                        setOptions((previous) => previous.filter((_, position) => position !== index))
                      }
                    >
                      <Trash2 />
                    </Button>
                  ) : null}
                </div>
              ))}
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
                <Plus /> Add item
              </Button>
            </div>
          ) : null}

          {type === "MATCHING" ? (
            <div className="space-y-2">
              <p className="text-sm font-medium">
                Pairs
                <span className="ml-2 font-normal text-xs text-muted-foreground">
                  Students see the left column in one order and the right column in another.
                </span>
              </p>
              {options.map((option, index) => (
                <div key={index} className="flex items-center gap-2">
                  <Input
                    value={option.option_text}
                    placeholder="Prompt"
                    onChange={(event) =>
                      setOptions((previous) =>
                        previous.map((item, position) =>
                          position === index ? { ...item, option_text: event.target.value } : item,
                        ),
                      )
                    }
                  />
                  <span className="text-muted-foreground">=</span>
                  <Input
                    value={option.match_text ?? ""}
                    placeholder="Matches"
                    onChange={(event) =>
                      setOptions((previous) =>
                        previous.map((item, position) =>
                          position === index ? { ...item, match_text: event.target.value } : item,
                        ),
                      )
                    }
                  />
                  {options.length > 2 ? (
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Remove pair ${index + 1}`}
                      onClick={() =>
                        setOptions((previous) => previous.filter((_, position) => position !== index))
                      }
                    >
                      <Trash2 />
                    </Button>
                  ) : null}
                </div>
              ))}
              <Button
                variant="secondary"
                size="sm"
                onClick={() =>
                  setOptions((previous) => [
                    ...previous,
                    { option_text: "", match_text: "", is_correct: false, order: previous.length + 1 },
                  ])
                }
              >
                <Plus /> Add pair
              </Button>
            </div>
          ) : null}

          {isChoice(type) ? (
            <div className="space-y-2">
              <p className="text-sm font-medium">Options</p>
              {options.map((option, index) => (
                <div key={index} className="flex items-center gap-2">
                  <input
                    type={type === "MCQ_MULTIPLE" ? "checkbox" : "radio"}
                    name="correct-option"
                    className="size-4 accent-[var(--primary)]"
                    aria-label={`${optionLabel(type, index)} is correct`}
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
                    placeholder={optionLabel(type, index)}
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
                      aria-label={`Remove ${optionLabel(type, index).toLowerCase()}`}
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
          ) : null}

          {isWritten(type) ? (
            <p className="text-sm text-muted-foreground">
              {questionTypeLabel(type)} answers are marked by a person; there is no answer key to
              enter.
            </p>
          ) : null}

          <Field
            label="Explanation"
            hint="Why the answer is the answer. Shown to students only if this quiz is set to show explanations, and only once its results are out."
          >
            {({ id }) => (
              <Textarea
                id={id}
                rows={2}
                value={explanation}
                onChange={(event) => setExplanation(event.target.value)}
              />
            )}
          </Field>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="secondary"
            loading={create.isPending && keepOpen}
            disabled={!valid || create.isPending}
            onClick={() => {
              setKeepOpen(true);
              create.mutate();
            }}
          >
            <Plus /> Save &amp; add another
          </Button>
          <Button
            loading={create.isPending && !keepOpen}
            disabled={!valid || create.isPending}
            onClick={() => {
              setKeepOpen(false);
              create.mutate();
            }}
          >
            Add question
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Every quiz setting, in one place, editable.
 *
 * Six of these were stored at creation and shown nowhere afterwards -- the
 * API did not even return them -- so a tutor could not see what they had
 * set, let alone change it. Five of them also did nothing at all until the
 * server learned to read them; see `alembic/versions/f17c4a9b0e23`.
 *
 * Deliberately a separate tab rather than more fields on the create dialog:
 * these are decisions a tutor revisits (withhold the marks, then release
 * them), and the create form's job is to get a quiz into existence.
 */
function SettingsTab({ quiz }: { quiz: QuizResponse }) {
  const { permissions } = useSession();
  const canEdit = permissions.has("quiz.update");
  const canMark = permissions.has("quiz.grade");
  const [draft, setDraft] = useState({
    duration_minutes: quiz.duration_minutes ? String(quiz.duration_minutes) : "",
    attempts_allowed: String(quiz.attempts_allowed),
    passing_score: String(quiz.passing_score),
    total_marks: quiz.total_marks == null ? "" : String(quiz.total_marks),
    questions_per_attempt: quiz.questions_per_attempt ? String(quiz.questions_per_attempt) : "",
    shuffle_questions: quiz.shuffle_questions ?? false,
    shuffle_answers: quiz.shuffle_answers ?? false,
    show_result_immediately: quiz.show_result_immediately ?? true,
    show_correct_answers: quiz.show_correct_answers ?? false,
    show_explanations: quiz.show_explanations ?? false,
    auto_submit_on_expiry: quiz.auto_submit_on_expiry ?? true,
  });

  const save = useApiMutation<QuizResponse, void>({
    mutationFn: () =>
      api.patch<QuizResponse>(`/quizzes/${segment(quiz.public_id)}`, {
        body: {
          duration_minutes: draft.duration_minutes ? Number(draft.duration_minutes) : null,
          attempts_allowed: Number(draft.attempts_allowed),
          passing_score: Number(draft.passing_score),
          // Blank means "no stated total", which is a real setting and not
          // a missing one -- sending `0` would be a ceiling no question
          // could fit under.
          total_marks: draft.total_marks.trim() === "" ? null : Number(draft.total_marks),
          // Blank means "every question", which is a real setting and not a
          // missing one -- so it is sent as null rather than omitted.
          questions_per_attempt: draft.questions_per_attempt
            ? Number(draft.questions_per_attempt)
            : null,
          shuffle_questions: draft.shuffle_questions,
          shuffle_answers: draft.shuffle_answers,
          show_result_immediately: draft.show_result_immediately,
          show_correct_answers: draft.show_correct_answers,
          show_explanations: draft.show_explanations,
          auto_submit_on_expiry: draft.auto_submit_on_expiry,
        },
      }),
    success: "Settings saved.",
    invalidate: [["quizzes"]],
  });

  const release = useApiMutation<QuizResponse, boolean>({
    mutationFn: (isReleased) =>
      api.put<QuizResponse>(`/quizzes/${segment(quiz.public_id)}/results`, {
        body: { is_released: isReleased },
      }),
    success: "Result visibility updated.",
    invalidate: [["quizzes"], ["attempts"]],
  });

  const closeExpired = useApiMutation<{ closed: number }, void>({
    mutationFn: () =>
      api.post<{ closed: number }>(
        `/quizzes/${segment(quiz.public_id)}/close-expired-attempts`,
      ),
    success: "Expired attempts closed.",
    invalidate: [["attempts"], ["quizzes"]],
  });

  function toggle(key: keyof typeof draft) {
    return (value: boolean) => setDraft((previous) => ({ ...previous, [key]: value }));
  }

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title="How this quiz runs"
          description="Saved settings apply to attempts started afterwards. The whole quiz locks once anybody has sat it — changing the pass mark or the number of questions then would rewrite what their result means."
        />
        <CardBody className="space-y-4">
          <FormGrid columns={3}>
            <Field label="Duration (minutes)" hint="Blank means untimed.">
              {({ id }) => (
                <Input
                  id={id}
                  type="number"
                  min={1}
                  disabled={!canEdit}
                  value={draft.duration_minutes}
                  onChange={(event) =>
                    setDraft((p) => ({ ...p, duration_minutes: event.target.value }))
                  }
                />
              )}
            </Field>
            <Field label="Attempts allowed">
              {({ id }) => (
                <Input
                  id={id}
                  type="number"
                  min={1}
                  disabled={!canEdit}
                  value={draft.attempts_allowed}
                  onChange={(event) =>
                    setDraft((p) => ({ ...p, attempts_allowed: event.target.value }))
                  }
                />
              )}
            </Field>
            <Field label="Passing score (%)">
              {({ id }) => (
                <Input
                  id={id}
                  type="number"
                  min={0}
                  step="0.01"
                  disabled={!canEdit}
                  value={draft.passing_score}
                  onChange={(event) =>
                    setDraft((p) => ({ ...p, passing_score: event.target.value }))
                  }
                />
              )}
            </Field>
            <Field
              label="Total marks"
              hint={
                quiz.total_marks == null
                  ? "Optional. Set one and questions are refused past it."
                  : `${quiz.total_points} of ${quiz.total_marks} written so far.`
              }
            >
              {({ id }) => (
                <Input
                  id={id}
                  type="number"
                  min={0}
                  step="0.01"
                  placeholder="No limit"
                  disabled={!canEdit}
                  value={draft.total_marks}
                  onChange={(event) =>
                    setDraft((p) => ({ ...p, total_marks: event.target.value }))
                  }
                />
              )}
            </Field>
          </FormGrid>

          <Field
            label="Questions per attempt"
            hint={`Blank means all ${quiz.question_count ?? 0}. A number draws that many at random from the bank, and the attempt is marked out of what it drew.`}
          >
            {({ id }) => (
              <Input
                id={id}
                type="number"
                min={1}
                className="max-w-40"
                disabled={!canEdit}
                value={draft.questions_per_attempt}
                onChange={(event) =>
                  setDraft((p) => ({ ...p, questions_per_attempt: event.target.value }))
                }
              />
            )}
          </Field>

          <div className="space-y-2">
            <label className="flex items-center gap-3 text-sm">
              <Switch
                checked={draft.shuffle_questions}
                disabled={!canEdit}
                onCheckedChange={toggle("shuffle_questions")}
              />
              Shuffle the question order for each attempt
            </label>
            <label className="flex items-center gap-3 text-sm">
              <Switch
                checked={draft.shuffle_answers}
                disabled={!canEdit}
                onCheckedChange={toggle("shuffle_answers")}
              />
              Shuffle the answer options within each question
            </label>
            <label className="flex items-center gap-3 text-sm">
              <Switch
                checked={draft.auto_submit_on_expiry}
                disabled={!canEdit}
                onCheckedChange={toggle("auto_submit_on_expiry")}
              />
              <span>
                Enforce the time limit
                <span className="block text-xs text-muted-foreground">
                  On: nothing is accepted after the timer runs out, and an abandoned attempt is
                  closed and marked on what was submitted — which is nothing, if they submitted
                  nothing. Off: the limit is advisory, a late submission is still marked, and it is
                  flagged for you.
                </span>
              </span>
            </label>
          </div>
        </CardBody>
        {canEdit ? (
          <div className="border-t border-border-subtle px-4 py-3">
            <FormActions>
              {/*
                Not disabled once the quiz has attempts: the response does not
                say whether it has any, and guessing would either block a
                tutor who could still edit or promise one who cannot. The
                server's 409 is the gate, and it explains itself.
              */}
              <Button loading={save.isPending} onClick={() => save.mutate()}>
                Save settings
              </Button>
            </FormActions>
          </div>
        ) : null}
      </Card>

      <Card>
        <CardHeader
          title="What students see afterwards"
          description="Marking and releasing are separate acts. These three decide how much of a marked attempt reaches the student and their guardian; you always see all of it."
        />
        <CardBody className="space-y-3">
          <label className="flex items-center gap-3 text-sm">
            <Switch
              checked={draft.show_result_immediately}
              disabled={!canEdit}
              onCheckedChange={toggle("show_result_immediately")}
            />
            <span>
              Show the mark as soon as it is marked
              <span className="block text-xs text-muted-foreground">
                Off: the mark is withheld until you release it below.
              </span>
            </span>
          </label>
          <label className="flex items-center gap-3 text-sm">
            <Switch
              checked={draft.show_correct_answers}
              disabled={!canEdit}
              onCheckedChange={toggle("show_correct_answers")}
            />
            <span>
              Show the correct answers
              <span className="block text-xs text-muted-foreground">
                Leave off to reuse this question bank next term.
              </span>
            </span>
          </label>
          <label className="flex items-center gap-3 text-sm">
            <Switch
              checked={draft.show_explanations}
              disabled={!canEdit}
              onCheckedChange={toggle("show_explanations")}
            />
            <span>
              Show each question&apos;s explanation
              <span className="block text-xs text-muted-foreground">
                Only questions you gave an explanation to have anything to show.
              </span>
            </span>
          </label>

          {draft.show_result_immediately ? null : (
            <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border-subtle bg-surface-muted p-3">
              <Badge tone={quiz.results_released_at ? "success" : "warning"}>
                {quiz.results_released_at ? "Results released" : "Results withheld"}
              </Badge>
              {canMark ? (
                <Button
                  variant="secondary"
                  size="sm"
                  loading={release.isPending}
                  onClick={() => release.mutate(!quiz.results_released_at)}
                >
                  {quiz.results_released_at ? "Withhold again" : "Release results"}
                </Button>
              ) : null}
              <span className="text-xs text-muted-foreground">
                Releasing notifies every student with a marked attempt, and their guardians.
              </span>
            </div>
          )}
        </CardBody>
      </Card>

      {canMark ? (
        <Card>
          <CardHeader
            title="Housekeeping"
            description="An attempt whose timer ran out is normally closed the next time that student starts the quiz. Somebody who has used every attempt never triggers that, so their sitting would stay open and you would be marking a result that cannot arrive."
          />
          <CardBody>
            <Button
              variant="secondary"
              loading={closeExpired.isPending}
              onClick={() => closeExpired.mutate()}
            >
              Close expired attempts
            </Button>
          </CardBody>
        </Card>
      ) : null}
    </div>
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

  /*
   * Counted from the questions on screen rather than from `quiz.total_points`.
   *
   * Both are the same number, but the list is what a deletion invalidates:
   * removing a question refreshes this query, so the button re-enables with
   * the row that vanished. Reading the quiz's own cached total would leave
   * the gate shut until something else happened to refetch it.
   */
  const written = questions.reduce((sum, question) => sum + Number(question.points ?? 0), 0);
  const full = quiz.total_marks != null && written >= Number(quiz.total_marks);

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
            <div className="flex items-center gap-2">
              {quiz.total_marks != null ? (
                <span
                  className={cn(
                    "text-xs tabular-nums",
                    full ? "text-danger" : "text-muted-foreground",
                  )}
                >
                  {written} / {quiz.total_marks} marks written
                </span>
              ) : null}
              <Button
                size="sm"
                disabled={full}
                // The reason is on the control, not in a toast after the
                // click: a disabled button with no explanation is the same
                // dead end as an unexplained refusal.
                title={
                  full
                    ? `This paper is full at ${quiz.total_marks} marks. Remove a question, or lower one, to make room.`
                    : undefined
                }
                onClick={() => setAddOpen(true)}
              >
                <Plus /> Add question
              </Button>
            </div>
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
                  <div className="flex gap-2 text-sm font-medium">
                    <span className="text-muted-foreground">{index + 1}.</span>
                    {/* Formatted on the way in, so formatted on the way out.
                        `RichText` prints anything written before the editor
                        existed as plain text rather than eating its angle
                        brackets. */}
                    <RichText html={question.question_text} className="min-w-0 flex-1" />
                  </div>
                  <p className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                    <Badge tone="neutral">{questionTypeLabel(question.question_type)}</Badge>
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
                  {question.options.map((option, position) => (
                    <li key={option.id} className="flex items-center gap-2 text-sm">
                      {/*
                        An ordering question's answer *is* the position, and a
                        matching question's is the pairing -- so a list that
                        showed only the option text showed a tutor no answer
                        key at all for two of the five types, on the screen
                        whose whole job is the answer key.
                      */}
                      {question.question_type === "ORDERING" ? (
                        <span className="w-6 text-right text-xs tabular-nums text-muted-foreground">
                          {position + 1}.
                        </span>
                      ) : null}
                      <span
                        className={
                          ("is_correct" in option && option.is_correct) ||
                          (isAuthor &&
                            (question.question_type === "ORDERING" ||
                              question.question_type === "MATCHING"))
                            ? "font-medium text-success"
                            : "text-muted-foreground"
                        }
                      >
                        {option.option_text}
                        {/*
                          The pairing, and only on the author's copy. A
                          student is served the right-hand column detached
                          and in its own order, so printing it beside the
                          prompt here would read as an answer key that is
                          not one -- "France = Lima" is two columns, not a
                          claim.
                        */}
                        {isAuthor && option.match_text ? (
                          <span className="text-muted-foreground"> = {option.match_text}</span>
                        ) : null}
                      </span>
                      {"is_correct" in option && option.is_correct ? (
                        <Badge tone="success">Correct</Badge>
                      ) : null}
                    </li>
                  ))}
                </ul>
              ) : null}
              {/*
                Fill-in-the-blank and numeric keep their key in `settings`,
                so without this the two types a machine marks from text show
                a tutor nothing to check.
              */}
              {!isAuthor && question.question_type === "MATCHING" ? (
                <p className="ml-6 text-sm text-muted-foreground">
                  Match these: {(question.options ?? [])
                    .map((option) => option.match_text)
                    .filter(Boolean)
                    .join(", ")}
                </p>
              ) : null}
              {answerKeyLine(question) ? (
                <p className="ml-6 text-sm">
                  <span className="text-muted-foreground">Accepts: </span>
                  <span className="font-medium text-success">{answerKeyLine(question)}</span>
                </p>
              ) : null}
              {"explanation" in question && question.explanation ? (
                <p className="ml-6 whitespace-pre-wrap break-words text-xs text-muted-foreground">
                  {question.explanation}
                </p>
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

  /*
   * Scores above the question's own maximum, named before the save.
   *
   * The server already refuses these (`grade_attempt` raises "Score exceeds
   * the question's points"), but it refuses the *whole* submission on the
   * first one -- so a tutor marking twelve answers learned about one typo
   * after losing the other eleven. Checked here so the offending row is
   * pointed at and nothing is sent.
   */
  const overAwarded = new Set(
    (attempt?.answers ?? [])
      .filter((answer) => {
        const typed = scores[answer.question_id];
        if (typed === undefined || typed.trim() === "" || answer.points_possible == null) return false;
        return Number(typed) > Number(answer.points_possible);
      })
      .map((answer) => answer.question_id),
  );

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
              <RichText
                html={answer.question_text ?? answer.question_id}
                className="font-medium"
              />
              {/*
                `answer_text` is rendered server-side: the stored payload is
                `{"option_ids": [8055]}`, and an option id tells a marker
                nothing about what the student chose. This used to show the
                raw JSON.
              */}
              <p className="mt-1 whitespace-pre-wrap break-words text-sm text-muted-foreground">
                {answer.answer_text ?? <span className="italic">Left blank</span>}
              </p>
              {answer.needs_marking ? (
                <div className="mt-2 flex items-center gap-2">
                  <label className="text-xs text-muted-foreground" htmlFor={`score-${answer.question_id}`}>
                    {/* The maximum is on the label, not only in the input's
                        `max`: a marker needs to know what they are marking
                        out of before they type, and the server refuses an
                        over-award either way. */}
                    Score / {answer.points_possible ?? "?"}
                  </label>
                  <Input
                    id={`score-${answer.question_id}`}
                    className="w-28"
                    type="number"
                    step="0.5"
                    min={0}
                    max={answer.points_possible ? Number(answer.points_possible) : undefined}
                    aria-invalid={overAwarded.has(answer.question_id) || undefined}
                    value={scores[answer.question_id] ?? ""}
                    onChange={(event) =>
                      setScores((previous) => ({ ...previous, [answer.question_id]: event.target.value }))
                    }
                  />
                  {overAwarded.has(answer.question_id) ? (
                    <span className="text-xs text-danger">
                      More than this question is worth.
                    </span>
                  ) : null}
                </div>
              ) : (
                // Already scored by auto-grading. Shown, not editable here:
                // the dialog says only unmarked answers need a score, and an
                // empty box beside a marked answer invites overwriting it.
                <p className="mt-2 text-xs text-muted-foreground">
                  Marked automatically — {String(answer.score_awarded)}
                </p>
              )}
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
          <Button
            loading={grade.isPending}
            disabled={overAwarded.size > 0}
            onClick={() => grade.mutate()}
          >
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
            {/*
              Not the same thing as late, and the difference is what a tutor
              needs: "ran out of time" explains a zero that "answered wrongly"
              does not.
            */}
            {row.auto_submitted ? <Badge tone="warning">Timed out</Badge> : null}
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

/** One student's working answer to one question, whatever its type. */
type Draft = {
  /** Chosen option ids. For ORDERING the order is the answer, so it is a list. */
  options: number[];
  /** Free text: short answer, essay, fill in the blank, numeric. */
  text: string;
  /** MATCHING: option id to the right-hand item they paired with it. */
  matches: Record<string, string>;
};

const EMPTY_DRAFT: Draft = { options: [], text: "", matches: {} };

function TakeQuizPanel({ quiz }: { quiz: QuizResponse }) {
  const [attempt, setAttempt] = useState<AttemptResponse | null>(null);
  const [answers, setAnswers] = useState<Record<string, Draft>>({});

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
            // Sent in the order the student arranged them: for an ORDERING
            // question that sequence *is* the answer, so sorting it here
            // would discard what is being marked.
            selected_option_ids: value.options.length > 0 ? value.options : null,
            text_answer: value.text || null,
            matches: Object.keys(value.matches).length > 0 ? value.matches : null,
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
    // `results_visible === false` means the quiz withholds marks until the
    // tutor releases them. The score really is absent from the response, so
    // there is nothing to hide here -- the job is to say why it is missing
    // rather than render a blank where a mark should be.
    const withheld = attempt.results_visible === false;
    const review = (attempt.answers ?? []).filter(
      (answer) => answer.correct_answer || answer.explanation,
    );

    return (
      <Card>
        <CardHeader
          title="Attempt submitted"
          description={
            attempt.auto_submitted
              ? "The time limit ran out before this was submitted, so it was closed and marked on what had arrived."
              : attempt.submitted_late
                ? "This arrived after the time limit. Your tutor can see that."
                : undefined
          }
        />
        <CardBody>
          {withheld ? (
            <p className="rounded-lg border border-border-subtle bg-surface-muted p-3 text-sm">
              Your answers are in. This quiz holds its marks back until your tutor releases them —
              you will be notified.
            </p>
          ) : (
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
          )}
          {attempt.feedback ? (
            <p className="mt-3 whitespace-pre-wrap break-words text-sm">{attempt.feedback}</p>
          ) : null}
          {review.length > 0 ? (
            <ol className="mt-4 space-y-2">
              {review.map((answer) => (
                <li
                  key={answer.question_id}
                  className="rounded-lg border border-border-subtle p-3 text-sm"
                >
                  <RichText html={answer.question_text} className="font-medium" />
                  <p className="mt-1 text-muted-foreground">
                    You answered: {answer.answer_text ?? <span className="italic">nothing</span>}
                  </p>
                  {answer.correct_answer ? (
                    <p className="mt-1">
                      <span className="text-muted-foreground">Correct answer: </span>
                      <span className="font-medium text-success">{answer.correct_answer}</span>
                    </p>
                  ) : null}
                  {answer.explanation ? (
                    <p className="mt-1 whitespace-pre-wrap break-words">{answer.explanation}</p>
                  ) : null}
                </li>
              ))}
            </ol>
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
              const value = answers[question.public_id] ?? EMPTY_DRAFT;
              const update = (patch: Partial<Draft>) =>
                setAnswers((previous) => ({
                  ...previous,
                  [question.public_id]: { ...value, ...patch },
                }));
              return (
                <div key={question.public_id} className="rounded-lg border border-border-subtle p-3">
                  <div className="flex gap-2 text-sm font-medium">
                    <span className="text-muted-foreground">{index + 1}.</span>
                    {/* Formatted on the way in, so formatted on the way out.
                        `RichText` prints anything written before the editor
                        existed as plain text rather than eating its angle
                        brackets. */}
                    <RichText html={question.question_text} className="min-w-0 flex-1" />
                  </div>
                  {question.question_type === "ORDERING" ? (
                    <OrderingAnswer
                      question={question}
                      chosen={value.options}
                      onChange={(options) => update({ options })}
                    />
                  ) : question.question_type === "MATCHING" ? (
                    <MatchingAnswer
                      question={question}
                      chosen={value.matches}
                      onChange={(matches) => update({ matches })}
                    />
                  ) : question.question_type === "NUMERIC" || question.question_type === "FILL_BLANK" ? (
                    <Input
                      className="mt-2 max-w-sm"
                      inputMode={question.question_type === "NUMERIC" ? "decimal" : "text"}
                      aria-label={`Answer to question ${index + 1}`}
                      value={value.text}
                      onChange={(event) => update({ text: event.target.value })}
                    />
                  ) : question.options && question.options.length > 0 ? (
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
                                update({
                                  options:
                                    question.question_type === "MCQ_MULTIPLE"
                                      ? event.target.checked
                                        ? [...value.options, option.id]
                                        : value.options.filter((id) => id !== option.id)
                                      : [option.id],
                                })
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
                      onChange={(event) => update({ text: event.target.value })}
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
  const canEditQuiz = permissions.has("quiz.update");

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
          {/* How the paper is run is the author's business. The server
              withholds the fields from a candidate regardless; this stops
              offering them a tab of blanks. */}
          {canEditQuiz ? <TabsTab value="settings">Settings</TabsTab> : null}
          {canAttempt ? <TabsTab value="take">Take it</TabsTab> : null}
        </TabsList>
        <TabsPanel value="questions">
          <QuestionsTab quiz={data} />
        </TabsPanel>
        {canEditQuiz ? (
          <TabsPanel value="settings">
            <SettingsTab quiz={data} />
          </TabsPanel>
        ) : null}
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
