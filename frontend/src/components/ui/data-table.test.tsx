import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DataTable, type Column } from "@/components/ui/data-table";

/**
 * The table was rebuilt on TanStack Table while keeping its `Column<T>` API,
 * because twenty-seven screens use that API and a rewrite of all of them would
 * risk far more than it gained.
 *
 * So the first thing these tests pin is that **the default rendering did not
 * change**: same rows, same order, same empty and loading shapes. A table that
 * quietly reorders or drops rows after a refactor is the worst possible
 * outcome, and it is invisible to a typecheck.
 *
 * The rest cover the opt-in capabilities, each of which is off unless asked
 * for — including, deliberately, that asking for none of them leaves the
 * markup free of their controls.
 */

interface Person {
  id: string;
  name: string;
  role: string;
}

const PEOPLE: Person[] = [
  { id: "p1", name: "Ada Lovelace", role: "Tutor" },
  { id: "p2", name: "Grace Hopper", role: "Admin" },
  { id: "p3", name: "Alan Turing", role: "Student" },
];

const COLUMNS: Column<Person>[] = [
  { key: "name", header: "Name", cell: (row) => row.name, alwaysVisible: true },
  { key: "role", header: "Role", cell: (row) => row.role },
];

function bodyRowTexts(): string[] {
  const rows = screen.getAllByRole("row");
  // Drop the header row.
  return rows.slice(1).map((row) => row.textContent ?? "");
}

describe("DataTable — React correctness", () => {
  /*
   * React logs a key warning to `console.error` and carries on, so a suite
   * that does not watch `console.error` stays green while every table in the
   * app warns. This one did: each row is wrapped in a fragment to carry its
   * expansion panel, and the key sat on the inner `<tr>` instead of the
   * fragment — found by opening a page, not by any test.
   *
   * Mis-keying is not cosmetic: React then reconciles rows by position, so a
   * reordered list can hand one row's DOM state (an open menu, a checkbox, a
   * focused cell) to a different row.
   */
  it("renders without React warnings, with and without expansion", () => {
    const errors: unknown[][] = [];
    const spy = vi.spyOn(console, "error").mockImplementation((...args) => {
      errors.push(args);
    });
    try {
      const { unmount } = render(
        <DataTable columns={COLUMNS} rows={PEOPLE} rowKey={(r) => r.id} />,
      );
      unmount();
      render(
        <DataTable
          columns={COLUMNS}
          rows={PEOPLE}
          rowKey={(r) => r.id}
          expansion={{ expanded: ["p1"], onChange: () => {}, render: () => <span>x</span> }}
        />,
      );
    } finally {
      spy.mockRestore();
    }
    expect(errors.map((args) => String(args[0]))).toEqual([]);
  });
});

describe("DataTable — unchanged defaults", () => {
  it("renders every row, in the order given", () => {
    render(<DataTable columns={COLUMNS} rows={PEOPLE} rowKey={(r) => r.id} />);

    const texts = bodyRowTexts();
    expect(texts).toHaveLength(3);
    expect(texts[0]).toContain("Ada Lovelace");
    expect(texts[1]).toContain("Grace Hopper");
    expect(texts[2]).toContain("Alan Turing");
  });

  it("adds no selection, expansion or actions controls unless asked", () => {
    render(<DataTable columns={COLUMNS} rows={PEOPLE} rowKey={(r) => r.id} />);

    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Expand row")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Row actions")).not.toBeInTheDocument();
  });

  it("shows the empty state only when there is nothing and nothing is loading", () => {
    const { rerender } = render(
      <DataTable columns={COLUMNS} rows={[]} rowKey={(r) => r.id} emptyMessage="No people yet." />,
    );
    expect(screen.getByText("No people yet.")).toBeInTheDocument();

    rerender(
      <DataTable
        columns={COLUMNS}
        rows={[]}
        rowKey={(r) => r.id}
        emptyMessage="No people yet."
        loading
      />,
    );
    // Loading must not read as "there is nothing here".
    expect(screen.queryByText("No people yet.")).not.toBeInTheDocument();
  });

  it("reports a sort rather than reordering rows itself", async () => {
    const user = userEvent.setup();
    const onSortChange = vi.fn();
    render(
      <DataTable
        columns={[{ ...COLUMNS[0]!, sortable: true }, COLUMNS[1]!]}
        rows={PEOPLE}
        rowKey={(r) => r.id}
        sort={null}
        onSortChange={onSortChange}
      />,
    );

    await user.click(screen.getByRole("button", { name: /name/i }));

    expect(onSortChange).toHaveBeenCalledWith({ key: "name", dir: "asc" });
    // Still the server's order: sorting a page in the browser would reorder
    // only the rows that happen to be loaded.
    expect(bodyRowTexts()[0]).toContain("Ada Lovelace");
  });

  it("shows a retryable error instead of the body", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(
      <DataTable
        columns={COLUMNS}
        rows={[]}
        rowKey={(r) => r.id}
        error={new Error("boom")}
        onRetry={onRetry}
      />,
    );

    await user.click(screen.getByRole("button", { name: /try again|retry/i }));
    expect(onRetry).toHaveBeenCalled();
  });
});

function SelectionHarness({ isSelectable }: { isSelectable?: (key: string) => boolean }) {
  const [selected, setSelected] = useState<string[]>([]);
  return (
    <div>
      <DataTable
        columns={COLUMNS}
        rows={PEOPLE}
        rowKey={(r) => r.id}
        selection={{ selected, onChange: setSelected, isSelectable }}
      />
      <output data-testid="selected">{selected.join(",") || "none"}</output>
    </div>
  );
}

describe("DataTable — row selection", () => {
  it("selects and clears a single row", async () => {
    const user = userEvent.setup();
    render(<SelectionHarness />);

    await user.click(screen.getByLabelText("Select row p2"));
    expect(screen.getByTestId("selected")).toHaveTextContent("p2");

    await user.click(screen.getByLabelText("Select row p2"));
    expect(screen.getByTestId("selected")).toHaveTextContent("none");
  });

  it("select-all covers only the rows on this page", async () => {
    const user = userEvent.setup();
    render(<SelectionHarness />);

    await user.click(screen.getByLabelText("Select all on this page"));
    expect(screen.getByTestId("selected")).toHaveTextContent("p1,p2,p3");
  });

  it("never selects a row the caller said is not selectable", async () => {
    const user = userEvent.setup();
    render(<SelectionHarness isSelectable={(key) => key !== "p3"} />);

    await user.click(screen.getByLabelText("Select all on this page"));
    // p3 must be absent: a bulk action over a row the caller excluded is the
    // bug this guard exists for.
    expect(screen.getByTestId("selected")).toHaveTextContent("p1,p2");
    expect(screen.getByLabelText("Select row p3")).toBeDisabled();
  });

  it("offers bulk actions only while something is selected", async () => {
    const user = userEvent.setup();
    function Harness() {
      const [selected, setSelected] = useState<string[]>([]);
      return (
        <DataTable
          columns={COLUMNS}
          rows={PEOPLE}
          rowKey={(r) => r.id}
          selection={{
            selected,
            onChange: setSelected,
            bulkActions: <button type="button">Archive</button>,
          }}
        />
      );
    }
    render(<Harness />);

    expect(screen.queryByText("Archive")).not.toBeInTheDocument();
    await user.click(screen.getByLabelText("Select row p1"));
    expect(screen.getByText("Archive")).toBeInTheDocument();
    expect(screen.getByText("1 selected")).toBeInTheDocument();
  });
});

describe("DataTable — column visibility", () => {
  it("hides a column and leaves an always-visible one alone", () => {
    const { rerender } = render(
      <DataTable
        columns={COLUMNS}
        rows={PEOPLE}
        rowKey={(r) => r.id}
        columnVisibility={{ hidden: [], onChange: () => {} }}
      />,
    );
    expect(screen.getByRole("columnheader", { name: "Role" })).toBeInTheDocument();

    rerender(
      <DataTable
        columns={COLUMNS}
        rows={PEOPLE}
        rowKey={(r) => r.id}
        columnVisibility={{ hidden: ["role", "name"], onChange: () => {} }}
      />,
    );
    expect(screen.queryByRole("columnheader", { name: "Role" })).not.toBeInTheDocument();
    // `alwaysVisible` wins: hiding the identity column would leave rows
    // nobody could tell apart.
    expect(screen.getByRole("columnheader", { name: "Name" })).toBeInTheDocument();
  });
});

describe("DataTable — expandable rows", () => {
  it("renders a panel only for the expanded row", async () => {
    const user = userEvent.setup();
    function Harness() {
      const [expanded, setExpanded] = useState<string[]>([]);
      return (
        <DataTable
          columns={COLUMNS}
          rows={PEOPLE}
          rowKey={(r) => r.id}
          expansion={{
            expanded,
            onChange: setExpanded,
            render: (row) => <span>Detail for {row.name}</span>,
          }}
        />
      );
    }
    render(<Harness />);

    expect(screen.queryByText(/^Detail for/)).not.toBeInTheDocument();

    const rows = screen.getAllByRole("row");
    await user.click(within(rows[2]!).getByLabelText("Expand row"));

    expect(screen.getByText("Detail for Grace Hopper")).toBeInTheDocument();
    expect(screen.queryByText("Detail for Ada Lovelace")).not.toBeInTheDocument();
  });
});
