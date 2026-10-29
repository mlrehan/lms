import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { AIComposer, type AIComposerProps } from "./ai-composer";
import { LONG_PASTE_CHARS, pastedTextAsFile, precheck, type StagedAttachment } from "./use-ai-attachments";

afterEach(cleanup);

function setup(overrides: Partial<AIComposerProps> = {}) {
  const props: AIComposerProps = {
    value: "",
    onChange: vi.fn(),
    onSend: vi.fn(),
    attachments: [],
    onAddFiles: vi.fn(),
    onRemoveAttachment: vi.fn(),
    loading: false,
    uploading: false,
    placeholder: "Message",
    ...overrides,
  };
  render(<AIComposer {...props} />);
  return props;
}

function paste(target: HTMLElement, data: { text?: string; files?: File[] }) {
  fireEvent.paste(target, {
    clipboardData: { files: data.files ?? [], getData: () => data.text ?? "" },
  });
}

const ready: StagedAttachment = {
  key: "a", id: "srv-1", filename: "veselin.ipynb", size: 48_000, kind: "NOTEBOOK", status: "ready", progress: 1,
};

describe("AIComposer", () => {
  it("turns a long paste into a file instead of a prompt that cannot be sent", () => {
    const props = setup();
    const notebook = JSON.stringify({ cells: [{ cell_type: "code", source: "x".repeat(LONG_PASTE_CHARS) }] });
    paste(screen.getByRole("textbox"), { text: notebook });
    expect(props.onAddFiles).toHaveBeenCalledTimes(1);
    const file = ((props.onAddFiles as ReturnType<typeof vi.fn>).mock.calls[0]?.[0] as File[])[0]!;
    expect(file.name).toMatch(/^pasted-notebook-\d+\.ipynb$/); // notebook JSON stays a notebook
    expect(props.onChange).not.toHaveBeenCalled();
  });

  it("leaves an ordinary paste alone", () => {
    const props = setup();
    paste(screen.getByRole("textbox"), { text: "grade this please" });
    expect(props.onAddFiles).not.toHaveBeenCalled();
  });

  it("attaches files pasted from the clipboard", () => {
    const props = setup();
    const image = new File(["x"], "board.png", { type: "image/png" });
    paste(screen.getByRole("textbox"), { files: [image] });
    expect(props.onAddFiles).toHaveBeenCalledWith([image]);
  });

  it("sends a message that is only an attachment", () => {
    const props = setup({ attachments: [ready] });
    const send = screen.getByRole("button", { name: "Send message" });
    expect(send).toBeEnabled();
    fireEvent.click(send);
    expect(props.onSend).toHaveBeenCalledTimes(1);
  });

  it("will not send while a file is still uploading, so nothing is sent without it", () => {
    const props = setup({ value: "mark this", uploading: true, attachments: [{ ...ready, status: "uploading", progress: 0.4 }] });
    expect(screen.getByRole("button", { name: /waiting for uploads/i })).toBeDisabled();
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    expect(props.onSend).not.toHaveBeenCalled();
    expect(screen.getByText("Uploading 40%")).toBeInTheDocument();
  });

  it("shows why a file failed and lets it be removed", () => {
    const props = setup({
      attachments: [{ key: "b", filename: "setup.exe", size: 10, status: "failed", progress: 0, message: ".exe files cannot be read here." }],
    });
    expect(screen.getByText(".exe files cannot be read here.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send message" })).toBeDisabled(); // a failed file is not something to send
    fireEvent.click(screen.getByRole("button", { name: "Remove setup.exe" }));
    expect(props.onRemoveAttachment).toHaveBeenCalledWith("b");
  });

  it("sends on Enter and keeps Shift+Enter for a new line", () => {
    const props = setup({ value: "hello" });
    const box = screen.getByRole("textbox");
    fireEvent.keyDown(box, { key: "Enter", shiftKey: true });
    expect(props.onSend).not.toHaveBeenCalled();
    fireEvent.keyDown(box, { key: "Enter" });
    expect(props.onSend).toHaveBeenCalledTimes(1);
  });
});

describe("attachment prechecks", () => {
  it("uses the server's limits for the obvious refusals", () => {
    expect(precheck(new File(["x"], "a.exe"), 0)).toMatch(/\.exe files cannot be read/);
    expect(precheck(new File([""], "a.py"), 0)).toMatch(/empty/);
    expect(precheck(new File(["x"], "a.py"), 10)).toMatch(/Up to 10 files/);
    expect(precheck(new File(["x"], "notes.md"), 0)).toBeNull();
  });

  it("names a plain long paste as text", () => {
    expect(pastedTextAsFile("just a lot of words", 2).name).toBe("pasted-text-2.txt");
  });
});
