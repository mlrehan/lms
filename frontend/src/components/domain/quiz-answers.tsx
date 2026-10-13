"use client";

import { ArrowDown, ArrowUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import type { QuestionForStudent } from "@/lib/api/types";

/**
 * Move one item of a list, returning a new list.
 *
 * Out-of-range indices return the list unchanged rather than writing
 * `undefined` into it: every caller guards its own buttons, and a silent
 * hole in an answer sequence would be marked as a wrong answer.
 */
export function swap<T>(items: T[], from: number, to: number): T[] {
  const a = items[from];
  const b = items[to];
  if (a === undefined || b === undefined) return items;
  const next = [...items];
  next[from] = b;
  next[to] = a;
  return next;
}

/**
 * Putting items in order.
 *
 * Numbered and moved with buttons rather than dragged: a drag needs a
 * pointer, and this has to work on a phone and from a keyboard.
 *
 * The sequence submitted is the sequence shown, top to bottom. Nothing here
 * may sort the list -- for an ORDERING question that order *is* the answer,
 * and the server stores it as given for the same reason.
 */
export function OrderingAnswer({
  question,
  chosen,
  onChange,
}: {
  question: QuestionForStudent;
  chosen: number[];
  onChange: (options: number[]) => void;
}) {
  const served = (question.options ?? []).map((option) => option.id);
  // Until the student moves something, the order is the one they were served
  // -- which is scrambled by the server on purpose. It is still submitted:
  // a sequence left alone is an answer, and refusing to send it would mark
  // them absent rather than wrong.
  const current = chosen.length === served.length ? chosen : served;
  const label = new Map((question.options ?? []).map((option) => [option.id, option.option_text]));

  return (
    <ol className="mt-2 space-y-1">
      {current.map((id, index) => (
        <li key={id} className="flex items-center gap-2 text-sm">
          <span className="w-6 text-right text-xs tabular-nums text-muted-foreground">
            {index + 1}.
          </span>
          <span className="flex-1 rounded border border-border-subtle px-2 py-1">
            {label.get(id)}
          </span>
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Move ${label.get(id)} up`}
            disabled={index === 0}
            onClick={() => onChange(swap(current, index, index - 1))}
          >
            <ArrowUp />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Move ${label.get(id)} down`}
            disabled={index === current.length - 1}
            onClick={() => onChange(swap(current, index, index + 1))}
          >
            <ArrowDown />
          </Button>
        </li>
      ))}
    </ol>
  );
}

/**
 * Pairing a left-hand prompt with a right-hand item.
 *
 * The right-hand column arrives **detached** from the prompts: the server
 * sends it in its own order precisely so that it carries no hint about the
 * pairing. So the choices are gathered from every option in the question,
 * never read off the one being answered -- doing the latter would both show
 * each prompt its own answer and offer a list of one.
 */
export function MatchingAnswer({
  question,
  chosen,
  onChange,
}: {
  question: QuestionForStudent;
  chosen: Record<string, string>;
  onChange: (matches: Record<string, string>) => void;
}) {
  const column = (question.options ?? [])
    .map((option) => option.match_text ?? "")
    .filter((text) => text !== "");

  return (
    <ul className="mt-2 space-y-2">
      {(question.options ?? []).map((option) => (
        <li key={option.id} className="flex flex-wrap items-center gap-2 text-sm">
          <span className="min-w-32 flex-1">{option.option_text}</span>
          <Select
            aria-label={`Match for ${option.option_text}`}
            className="min-w-44"
            value={chosen[String(option.id)] ?? ""}
            onValueChange={(value) => {
              const next = { ...chosen };
              // A cleared choice is removed rather than stored as "", which
              // the server would read as a pairing with an empty item.
              if (!value) delete next[String(option.id)];
              else next[String(option.id)] = value;
              onChange(next);
            }}
            options={column.map((text) => ({ value: text, label: text }))}
          />
        </li>
      ))}
    </ul>
  );
}
