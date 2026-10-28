import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import { AssessmentPreviewCard } from "./assessment-preview-card";
import { ActionConfirmationDialog } from "./action-confirmation-dialog";
import { AIMessageList } from "./ai-message-list";
import { useAIStore } from "@/lib/ai-store";
import { api } from "@/lib/api/client";

afterEach(cleanup);

describe("AssessmentPreviewCard", () => {
  it("renders draft badge, title, and metrics correctly", () => {
    const draft = {
      assessment_id: "quiz-123",
      title: "Python Data Structures",
      status: "DRAFT",
      question_count: 5,
      total_marks: 25,
      scope: "BATCH",
      course: "Advanced Python",
      batch: "2026-A",
    };

    render(<AssessmentPreviewCard draft={draft} />);

    expect(screen.getByText("Python Data Structures")).toBeInTheDocument();
    expect(screen.getByText("DRAFT")).toBeInTheDocument();
    expect(screen.getByText("5 Questions")).toBeInTheDocument();
    expect(screen.getByText("25 Total Marks")).toBeInTheDocument();
    expect(screen.getByText("Advanced Python")).toBeInTheDocument();
    expect(screen.getByText("Batch: 2026-A")).toBeInTheDocument();
  });

  it("calls onPublishClick when Publish Live button is clicked", () => {
    const onPublish = vi.fn();
    const draft = {
      assessment_id: "quiz-123",
      title: "Python Quiz",
      status: "DRAFT",
    };

    render(<AssessmentPreviewCard draft={draft} onPublishClick={onPublish} />);

    const publishBtn = screen.getByRole("button", { name: /publish live/i });
    fireEvent.click(publishBtn);

    expect(onPublish).toHaveBeenCalledTimes(1);
    expect(onPublish).toHaveBeenCalledWith(draft);
  });
});

describe("ActionConfirmationDialog", () => {
  it("displays affected records and cryptographic hash preview", () => {
    const ticket = {
      ticket_id: "act_0123456789abcdef",
      action_name: "publish_assessment",
      parameters: { assessment_id: "quiz-123" },
      parameters_hash: "abcdef0123456789fedcba9876543210",
      affected_records_count: 32,
      preview_summary: "Publish assessment 'Python Quiz' to 32 enrolled students.",
      expires_at: new Date(Date.now() + 900000).toISOString(),
      status: "PENDING",
    };

    render(
      <ActionConfirmationDialog
        open={true}
        onOpenChange={vi.fn()}
        ticket={ticket}
      />
    );

    expect(screen.getByText(/Confirm this action/i)).toBeInTheDocument();
    expect(screen.getByText("32")).toBeInTheDocument();
    expect(screen.getByText(/act_0123456789abcdef/i)).toBeInTheDocument();
    expect(screen.getByText(/abcdef0123456789/i)).toBeInTheDocument();
    expect(screen.getByText(/Publish assessment 'Python Quiz' to 32 enrolled students/i)).toBeInTheDocument();
    // No phrase demanded, so none is asked for.
    expect(screen.queryByTestId("ai-confirm-phrase")).toBeNull();
  });

  const sqlTicket = {
    ticket_id: "act_sql",
    action_name: "execute_sql_change",
    parameters: {},
    parameters_hash: "f".repeat(64),
    affected_records_count: 3,
    preview_summary: "DELETE 3 row(s) in tags: DELETE FROM tags WHERE id < 4",
    expires_at: new Date(Date.now() + 900000).toISOString(),
    status: "PENDING",
    typed_confirmation: "DELETE 3 ROWS IN tags",
  };

  it("keeps Confirm disabled until the exact phrase is typed", () => {
    render(<ActionConfirmationDialog open={true} onOpenChange={vi.fn()} ticket={sqlTicket} />);
    const confirm = screen.getByRole("button", { name: /^Confirm$/ });
    const input = screen.getByTestId("ai-confirm-phrase");

    expect(confirm).toBeDisabled();
    fireEvent.change(input, { target: { value: "delete 3 rows in tags" } });
    expect(confirm).toBeDisabled();
    fireEvent.change(input, { target: { value: "DELETE 3 ROWS IN tags" } });
    expect(confirm).toBeEnabled();
  });

  it("sends the typed phrase to the server", async () => {
    const post = vi.spyOn(api, "post").mockResolvedValue({ success: true, result: { message: "applied" } });
    render(<ActionConfirmationDialog open={true} onOpenChange={vi.fn()} ticket={sqlTicket} />);
    fireEvent.change(screen.getByTestId("ai-confirm-phrase"), { target: { value: "DELETE 3 ROWS IN tags" } });
    fireEvent.click(screen.getByRole("button", { name: /^Confirm$/ }));

    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post).toHaveBeenCalledWith(
      "/ai/confirm",
      expect.objectContaining({
        body: expect.objectContaining({ ticket_id: "act_sql", confirmation_text: "DELETE 3 ROWS IN tags" }),
      }),
    );
    post.mockRestore();
  });
});

describe("AIMessageList", () => {
  it("renders role suggestions when message list is empty", () => {
    const onSuggestion = vi.fn();
    render(
      <AIMessageList
        messages={[]}
        userRole="TUTOR"
        onSuggestionClick={onSuggestion}
      />
    );

    expect(screen.getByText("Role-Aware AI Assistant")).toBeInTheDocument();
    const suggestionBtn = screen.getByText(/Draft a 5-question quiz on Python lists/i);
    expect(suggestionBtn).toBeInTheDocument();

    fireEvent.click(suggestionBtn);
    expect(onSuggestion).toHaveBeenCalledWith(
      "Draft a 5-question quiz on Python lists and dictionaries for my course"
    );
  });

  it("renders conversational turns with formatted code blocks", () => {
    const messages = [
      {
        id: "1",
        role: "user" as const,
        content: "How do I reverse a string in Python?",
      },
      {
        id: "2",
        role: "assistant" as const,
        content: "Here is how you do it:\n```python\ntext = 'hello'\nreversed_text = text[::-1]\n```",
        agentRole: "TUTOR",
      },
    ];

    render(<AIMessageList messages={messages} />);

    expect(screen.getByText("How do I reverse a string in Python?")).toBeInTheDocument();
    expect(screen.getByText("TUTOR")).toBeInTheDocument();
    expect(screen.getByText(/text\[::-1\]/)).toBeInTheDocument();
  });
});

describe("useAIStore", () => {
  it("manages open, close, and toggle states", () => {
    const store = useAIStore.getState();
    expect(store.isOpen).toBe(false);

    store.openDrawer("Hello AI");
    expect(useAIStore.getState().isOpen).toBe(true);
    expect(useAIStore.getState().initialPrompt).toBe("Hello AI");

    store.closeDrawer();
    expect(useAIStore.getState().isOpen).toBe(false);
    expect(useAIStore.getState().initialPrompt).toBeNull();

    store.toggleDrawer();
    expect(useAIStore.getState().isOpen).toBe(true);
  });
});

