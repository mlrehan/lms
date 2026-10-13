import { useState } from "react";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MatchingAnswer, OrderingAnswer } from "@/components/domain/quiz-answers";
import type { QuestionForStudent } from "@/lib/api/types";

/**
 * Two question types whose answer is a *structure*, not a selection, and
 * whose server-side marking is all-or-nothing. Both have a failure mode that
 * no type error can catch:
 *
 * * an ordering answer that loses its order submits a set, and the server
 *   marks a set against a sequence -- every student wrong;
 * * a matching answer that reads each prompt's own `match_text` would offer
 *   a list of one and show the student the answer. The server detaches that
 *   column on purpose, and this is the half of that contract that lives in
 *   the browser.
 */

function ordering(): QuestionForStudent {
  return {
    public_id: "q-order",
    question_text: "Put these in order",
    question_type: "ORDERING",
    points: "1.00",
    order: 0,
    // As served: scrambled, and each option's `order` is its position in
    // *this* list, never the authored one.
    options: [
      { id: 7, option_text: "gamma", order: 0 },
      { id: 5, option_text: "alpha", order: 1 },
      { id: 6, option_text: "beta", order: 2 },
    ],
  };
}

function matching(): QuestionForStudent {
  return {
    public_id: "q-match",
    question_text: "Match country to capital",
    question_type: "MATCHING",
    points: "1.00",
    order: 0,
    options: [
      { id: 11, option_text: "France", order: 0, match_text: "Lima" },
      { id: 12, option_text: "Japan", order: 1, match_text: "Paris" },
      { id: 13, option_text: "Peru", order: 2, match_text: "Tokyo" },
    ],
  };
}

function OrderingHarness() {
  const [chosen, setChosen] = useState<number[]>([]);
  return (
    <div>
      <OrderingAnswer question={ordering()} chosen={chosen} onChange={setChosen} />
      <output data-testid="submitted">{chosen.join(",")}</output>
    </div>
  );
}

function MatchingHarness() {
  const [chosen, setChosen] = useState<Record<string, string>>({});
  return (
    <div>
      <MatchingAnswer question={matching()} chosen={chosen} onChange={setChosen} />
      <output data-testid="submitted">{JSON.stringify(chosen)}</output>
    </div>
  );
}

describe("OrderingAnswer", () => {
  it("shows the items in the order they were served", () => {
    render(<OrderingHarness />);

    const items = screen.getAllByRole("listitem").map((item) => item.textContent ?? "");
    expect(items[0]).toContain("gamma");
    expect(items[1]).toContain("alpha");
    expect(items[2]).toContain("beta");
  });

  it("submits the sequence the student arranged, in that order", async () => {
    const user = userEvent.setup();
    render(<OrderingHarness />);

    await user.click(screen.getByRole("button", { name: "Move alpha up" }));

    // alpha moved above gamma, so the answer is 5,7,6 -- and the order is
    // the whole answer. A component that handed back a sorted or a
    // set-shaped list would read 5,6,7 here and be marked wrong for the
    // student.
    expect(screen.getByTestId("submitted")).toHaveTextContent("5,7,6");
  });

  it("cannot move the first item up or the last one down", () => {
    render(<OrderingHarness />);

    expect(screen.getByRole("button", { name: "Move gamma up" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Move beta down" })).toBeDisabled();
  });
});

describe("MatchingAnswer", () => {
  it("offers every right-hand item against every prompt", () => {
    render(<MatchingHarness />);

    // Three prompts, each with the same three choices. Reading the choices
    // off the option being answered would give each prompt exactly one
    // option -- its own answer.
    for (const prompt of ["France", "Japan", "Peru"]) {
      expect(screen.getByRole("combobox", { name: `Match for ${prompt}` })).toBeInTheDocument();
    }
  });

  it("keys each pairing by the option id the server will read", async () => {
    const user = userEvent.setup();
    render(<MatchingHarness />);

    await user.click(screen.getByRole("combobox", { name: "Match for France" }));
    await user.click(screen.getByRole("option", { name: "Paris" }));

    // `{"11": "Paris"}`: the id of the France option, as a string, because
    // JSON object keys are strings and the server's `matches` field is a
    // `dict[str, str]`.
    expect(screen.getByTestId("submitted")).toHaveTextContent('{"11":"Paris"}');
  });
});
