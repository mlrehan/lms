import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Combobox, MultiCombobox } from "@/components/ui/combobox";
import type { SelectOption } from "@/components/ui/select";

/**
 * The behaviour these tests exist for is **label preservation across async
 * result changes**.
 *
 * An async picker's options are whatever the last search returned. The item
 * the person already chose is usually *not* in that list — they have typed a
 * new term, or the result page has moved on. A control that reads its label
 * out of `options` therefore shows a raw id at exactly the moment the user is
 * reviewing their choice, and nothing about the code looks wrong.
 *
 * Everything else here (chips, removal, clearing) would be caught by using
 * the control once; that one would not.
 */

const PEOPLE: SelectOption[] = [
  { value: "u1", label: "Ada Lovelace", description: "ada@example.test" },
  { value: "u2", label: "Grace Hopper", description: "grace@example.test" },
];

function SingleHarness({ initial = null }: { initial?: string | null }) {
  const [value, setValue] = useState<string | null>(initial);
  const [options, setOptions] = useState<SelectOption[]>(PEOPLE);
  return (
    <div>
      <Combobox
        aria-label="Person"
        value={value}
        onValueChange={(next) => setValue(next)}
        options={options}
        onSearch={() => undefined}
      />
      <button type="button" onClick={() => setOptions([])}>
        drop options
      </button>
      <output data-testid="value">{value ?? "none"}</output>
    </div>
  );
}

describe("Combobox", () => {
  it("renders the chosen option's label, not its id", async () => {
    const user = userEvent.setup();
    render(<SingleHarness />);

    await user.click(screen.getByLabelText("Person"));
    await user.click(await screen.findByText("Ada Lovelace"));

    expect(screen.getByTestId("value")).toHaveTextContent("u1");
    // The label survives as the input's own display text.
    await waitFor(() =>
      expect(screen.getByLabelText("Person")).toHaveAttribute("placeholder", "Ada Lovelace"),
    );
  });

  it("keeps showing the label after the options list no longer contains it", async () => {
    const user = userEvent.setup();
    render(<SingleHarness />);

    await user.click(screen.getByLabelText("Person"));
    await user.click(await screen.findByText("Ada Lovelace"));

    // Simulates the next server search returning a different page entirely.
    await user.click(screen.getByText("drop options"));

    // Without the label cache this reads "u1".
    await waitFor(() =>
      expect(screen.getByLabelText("Person")).toHaveAttribute("placeholder", "Ada Lovelace"),
    );
  });

  it("reports the option alongside the value so callers need no second lookup", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <Combobox aria-label="Person" value={null} onValueChange={onChange} options={PEOPLE} />,
    );

    await user.click(screen.getByLabelText("Person"));
    await user.click(await screen.findByText("Grace Hopper"));

    expect(onChange).toHaveBeenCalledWith(
      "u2",
      expect.objectContaining({ value: "u2", label: "Grace Hopper" }),
    );
  });

  it("filters on the client only when no server search is supplied", async () => {
    const user = userEvent.setup();
    render(<Combobox aria-label="Person" value={null} onValueChange={() => {}} options={PEOPLE} />);

    // Typed without a preceding click: clicking an already-open combobox
    // toggles the popup shut, which would make this pass for the wrong reason.
    await user.type(screen.getByLabelText("Person"), "grace");

    await waitFor(() => expect(screen.getByText("Grace Hopper")).toBeInTheDocument());
    expect(screen.queryByText("Ada Lovelace")).not.toBeInTheDocument();
  });

  it("does not filter the server's own results a second time", async () => {
    const user = userEvent.setup();
    const onSearch = vi.fn();
    // The server answered "grace" with a row whose label does not contain it;
    // client filtering would hide a row the server deliberately returned.
    render(
      <Combobox
        aria-label="Person"
        value={null}
        onValueChange={() => {}}
        options={[{ value: "u9", label: "Rear Admiral Hopper" }]}
        onSearch={onSearch}
      />,
    );

    await user.type(screen.getByLabelText("Person"), "grace");

    expect(onSearch).toHaveBeenCalled();
    expect(screen.getByText("Rear Admiral Hopper")).toBeInTheDocument();
  });

  it("announces loading while there is nothing to show yet", async () => {
    const user = userEvent.setup();
    render(
      <Combobox aria-label="Person" value={null} onValueChange={() => {}} options={[]} loading />,
    );
    await user.click(screen.getByLabelText("Person"));
    // Matched by accessible *name*, not by role alone: Base UI's own
    // `Combobox.Empty` is a `role="status"` announcer that is present whenever
    // there are matches, so a bare role query passes with no spinner at all.
    expect(await screen.findByRole("status", { name: /loading options/i })).toBeInTheDocument();
  });

  it("keeps showing results while a refining search is in flight", async () => {
    const user = userEvent.setup();
    // `loading` is true *and* there are results: refining a search must not
    // blank the list on every keystroke, which makes it unreadable.
    render(
      <Combobox
        aria-label="Person"
        value={null}
        onValueChange={() => {}}
        options={PEOPLE}
        loading
      />,
    );
    await user.click(screen.getByLabelText("Person"));

    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: /loading options/i })).not.toBeInTheDocument();
  });

  it("offers a retry when the search failed", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(
      <Combobox
        aria-label="Person"
        value={null}
        onValueChange={() => {}}
        options={[]}
        error="Could not reach the server."
        onRetry={onRetry}
      />,
    );

    await user.click(screen.getByLabelText("Person"));
    expect(await screen.findByText("Could not reach the server.")).toBeInTheDocument();
    await user.click(screen.getByText("Try again"));
    expect(onRetry).toHaveBeenCalled();
  });
});

function MultiHarness() {
  const [value, setValue] = useState<string[]>([]);
  const [options, setOptions] = useState<SelectOption[]>(PEOPLE);
  return (
    <div>
      <MultiCombobox
        aria-label="People"
        value={value}
        onValueChange={(next) => setValue(next)}
        options={options}
        onSearch={() => undefined}
      />
      <button type="button" onClick={() => setOptions([])}>
        drop options
      </button>
      <output data-testid="value">{value.join(",") || "none"}</output>
    </div>
  );
}

describe("MultiCombobox", () => {
  it("adds a chip per selection and reports every value", async () => {
    const user = userEvent.setup();
    render(<MultiHarness />);

    await user.click(screen.getByLabelText("People"));
    await user.click(await screen.findByText("Ada Lovelace"));
    await user.click(await screen.findByText("Grace Hopper"));

    await waitFor(() => expect(screen.getByTestId("value")).toHaveTextContent("u1,u2"));
    expect(screen.getByLabelText("Remove Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByLabelText("Remove Grace Hopper")).toBeInTheDocument();
  });

  it("keeps chip labels when the options no longer contain them", async () => {
    const user = userEvent.setup();
    render(<MultiHarness />);

    await user.click(screen.getByLabelText("People"));
    await user.click(await screen.findByText("Ada Lovelace"));
    await user.click(screen.getByText("drop options"));

    // Without the cache the chip reads "u1".
    await waitFor(() => expect(screen.getByLabelText("Remove Ada Lovelace")).toBeInTheDocument());
  });

  it("removes a single selection from its chip", async () => {
    const user = userEvent.setup();
    render(<MultiHarness />);

    await user.click(screen.getByLabelText("People"));
    await user.click(await screen.findByText("Ada Lovelace"));
    await user.click(await screen.findByText("Grace Hopper"));
    await waitFor(() => expect(screen.getByTestId("value")).toHaveTextContent("u1,u2"));

    await user.click(screen.getByLabelText("Remove Ada Lovelace"));
    await waitFor(() => expect(screen.getByTestId("value")).toHaveTextContent("u2"));
  });
});
