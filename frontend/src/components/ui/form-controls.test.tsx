import { useForm } from "react-hook-form";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FormSelect } from "@/components/ui/form-controls";

/**
 * The failure this guards against is silent.
 *
 * `register("scope")` spreads `onChange`/`ref`/`name` onto a native element.
 * These controls are not native elements — they report a value, not a change
 * event — so a `register`ed one submits whatever the default was, for ever,
 * with no error anywhere. `Controller` is the supported bridge, and these
 * tests prove the bridge actually carries the value.
 */

const OPTIONS = [
  { value: "COURSE", label: "Everyone on the course" },
  { value: "BATCH", label: "One batch" },
];

function Harness({ onSubmit }: { onSubmit: (values: { scope: string }) => void }) {
  const { control, handleSubmit } = useForm<{ scope: string }>({
    defaultValues: { scope: "COURSE" },
  });
  return (
    // `method="post"` because `src/app/forms.test.ts` requires it of every
    // form in the tree, test harnesses included: a form with no method
    // defaults to GET and serialises its fields into the URL if a submit
    // ever escapes React.
    <form method="post" onSubmit={handleSubmit(onSubmit)}>
      <FormSelect control={control} name="scope" options={OPTIONS} aria-label="Scope" />
      <button type="submit">Save</button>
    </form>
  );
}

describe("FormSelect", () => {
  it("submits the default when nothing is touched", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<Harness onSubmit={onSubmit} />);

    await user.click(screen.getByText("Save"));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ scope: "COURSE" }),
      expect.anything(),
    );
  });

  it("writes a new selection into form state", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<Harness onSubmit={onSubmit} />);

    await user.click(screen.getByLabelText("Scope"));
    await user.click(await screen.findByText("One batch"));
    await user.click(screen.getByText("Save"));

    // The whole point: without Controller this still reads "COURSE".
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ scope: "BATCH" }),
      expect.anything(),
    );
  });

  it("shows the chosen label on the trigger", async () => {
    const user = userEvent.setup();
    render(<Harness onSubmit={() => {}} />);

    expect(screen.getByLabelText("Scope")).toHaveTextContent("Everyone on the course");
    await user.click(screen.getByLabelText("Scope"));
    await user.click(await screen.findByText("One batch"));
    expect(screen.getByLabelText("Scope")).toHaveTextContent("One batch");
  });
});
