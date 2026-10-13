"use client";

import { useEffect, type ReactNode } from "react";
import { EditorContent, useEditor, type Editor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { TableKit } from "@tiptap/extension-table";
import {
  Bold,
  Code2,
  Columns3,
  Heading2,
  Heading3,
  Italic,
  List,
  ListOrdered,
  Quote,
  Redo2,
  RemoveFormatting,
  Rows3,
  Strikethrough,
  Table as TableIcon,
  Trash2,
  Undo2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * The editor an assessment is written in.
 *
 * Separate from the message composer (`mail/rich-editor.tsx`) because the two
 * have different allow-lists and should: a brief needs **tables** -- a mark
 * scheme or a data set is a table, and writing one as indented text is how it
 * becomes unreadable -- and **code blocks** with their structure intact. An
 * email does not, and widening the mail editor to suit would widen what email
 * accepts too.
 *
 * What this produces is only ever a *request*. The server re-parses it
 * (`backend/services/rich_text.py`) and keeps a short list of tags; scripts,
 * event handlers, styles, classes, images and `javascript:` links do not
 * survive. The toolbar offers exactly what the server will keep, so nothing a
 * tutor can do here is silently discarded on save.
 */

function ToolbarButton({
  active,
  label,
  onClick,
  disabled,
  children,
}: {
  active?: boolean;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  children: ReactNode;
}): ReactNode {
  return (
    <Button
      type="button"
      size="icon"
      variant="ghost"
      aria-label={label}
      aria-pressed={active}
      title={label}
      disabled={disabled}
      className={cn("size-7", active && "bg-accent text-accent-foreground")}
      onClick={onClick}
    >
      {children}
    </Button>
  );
}

function Toolbar({ editor }: { editor: Editor | null }): ReactNode {
  if (!editor) return null;
  const inTable = editor.isActive("table");

  return (
    <div className="flex flex-wrap items-center gap-0.5 border-b border-border-subtle bg-surface-muted px-1.5 py-1">
      <ToolbarButton label="Bold" active={editor.isActive("bold")} onClick={() => editor.chain().focus().toggleBold().run()}>
        <Bold className="size-3.5" />
      </ToolbarButton>
      <ToolbarButton label="Italic" active={editor.isActive("italic")} onClick={() => editor.chain().focus().toggleItalic().run()}>
        <Italic className="size-3.5" />
      </ToolbarButton>
      <ToolbarButton label="Strike-through" active={editor.isActive("strike")} onClick={() => editor.chain().focus().toggleStrike().run()}>
        <Strikethrough className="size-3.5" />
      </ToolbarButton>

      <span className="mx-1 h-4 w-px bg-border-subtle" aria-hidden />

      <ToolbarButton label="Heading" active={editor.isActive("heading", { level: 2 })} onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}>
        <Heading2 className="size-3.5" />
      </ToolbarButton>
      <ToolbarButton label="Sub-heading" active={editor.isActive("heading", { level: 3 })} onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()}>
        <Heading3 className="size-3.5" />
      </ToolbarButton>
      <ToolbarButton label="Bulleted list" active={editor.isActive("bulletList")} onClick={() => editor.chain().focus().toggleBulletList().run()}>
        <List className="size-3.5" />
      </ToolbarButton>
      <ToolbarButton label="Numbered list" active={editor.isActive("orderedList")} onClick={() => editor.chain().focus().toggleOrderedList().run()}>
        <ListOrdered className="size-3.5" />
      </ToolbarButton>
      <ToolbarButton label="Quote" active={editor.isActive("blockquote")} onClick={() => editor.chain().focus().toggleBlockquote().run()}>
        <Quote className="size-3.5" />
      </ToolbarButton>
      <ToolbarButton label="Code block" active={editor.isActive("codeBlock")} onClick={() => editor.chain().focus().toggleCodeBlock().run()}>
        <Code2 className="size-3.5" />
      </ToolbarButton>

      <span className="mx-1 h-4 w-px bg-border-subtle" aria-hidden />

      <ToolbarButton
        label="Insert table"
        active={inTable}
        onClick={() =>
          editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()
        }
      >
        <TableIcon className="size-3.5" />
      </ToolbarButton>
      {/* The table controls only appear inside a table. Four permanently
          greyed buttons on every brief is noise for the common case, which is
          a brief with no table in it. */}
      {inTable ? (
        <>
          <ToolbarButton label="Add row" onClick={() => editor.chain().focus().addRowAfter().run()}>
            <Rows3 className="size-3.5" />
          </ToolbarButton>
          <ToolbarButton label="Add column" onClick={() => editor.chain().focus().addColumnAfter().run()}>
            <Columns3 className="size-3.5" />
          </ToolbarButton>
          <ToolbarButton label="Delete table" onClick={() => editor.chain().focus().deleteTable().run()}>
            <Trash2 className="size-3.5 text-danger" />
          </ToolbarButton>
        </>
      ) : null}

      <span className="mx-1 h-4 w-px bg-border-subtle" aria-hidden />

      <ToolbarButton label="Clear formatting" onClick={() => editor.chain().focus().unsetAllMarks().clearNodes().run()}>
        <RemoveFormatting className="size-3.5" />
      </ToolbarButton>
      <ToolbarButton label="Undo" disabled={!editor.can().undo()} onClick={() => editor.chain().focus().undo().run()}>
        <Undo2 className="size-3.5" />
      </ToolbarButton>
      <ToolbarButton label="Redo" disabled={!editor.can().redo()} onClick={() => editor.chain().focus().redo().run()}>
        <Redo2 className="size-3.5" />
      </ToolbarButton>
    </div>
  );
}

export function RichTextEditor({
  value,
  onChange,
  placeholder = "Write here",
  disabled,
  minHeight = "min-h-32",
  ariaLabel,
  className,
}: {
  /** Stored HTML. Plain text from before this editor existed is accepted. */
  value: string;
  onChange: (html: string) => void;
  placeholder?: string;
  disabled?: boolean;
  minHeight?: string;
  ariaLabel?: string;
  className?: string;
}): ReactNode {
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        // Kept: headings, code blocks and the horizontal rule, all of which
        // the server's allow-list keeps too.
        link: {
          openOnClick: false,
          autolink: true,
          protocols: ["http", "https", "mailto"],
          HTMLAttributes: { rel: "noopener noreferrer nofollow" },
        },
      }),
      TableKit.configure({ table: { resizable: false } }),
    ],
    content: value,
    editable: !disabled,
    // The console renders on the client; skipping the server render avoids a
    // hydration mismatch.
    immediatelyRender: false,
    editorProps: {
      attributes: {
        class: cn("rich-text px-3 py-2 text-sm outline-none", minHeight),
        ...(ariaLabel ? { "aria-label": ariaLabel } : {}),
        "data-placeholder": placeholder,
      },
    },
    onUpdate: ({ editor: e }) => onChange(e.isEmpty ? "" : e.getHTML()),
  });

  useEffect(() => {
    editor?.setEditable(!disabled);
  }, [editor, disabled]);

  /*
   * Adopt a value that changed from outside -- a different question opened in
   * the same dialog, or a reset after "save & add another".
   *
   * Compared against what the editor currently holds, so typing does not
   * fight the prop: `onUpdate` has already pushed that same HTML upward, and
   * re-setting it would move the caret to the end on every keystroke.
   */
  useEffect(() => {
    if (!editor) return;
    if (value === editor.getHTML()) return;
    if (value === "" && editor.isEmpty) return;
    editor.commands.setContent(value, { emitUpdate: false });
  }, [editor, value]);

  return (
    <div
      className={cn(
        "overflow-hidden rounded-lg border border-border-subtle bg-surface focus-within:ring-2 focus-within:ring-primary",
        disabled && "opacity-60",
        className,
      )}
    >
      <Toolbar editor={editor} />
      <EditorContent editor={editor} />
    </div>
  );
}

/**
 * Stored formatted text, rendered.
 *
 * `dangerouslySetInnerHTML` is correct here and nowhere else: the server
 * sanitised this on the way in and nothing re-sanitises on the way out, which
 * is the contract `rich_text.py` states. Anything that reaches here without
 * having gone through it must not use this component.
 *
 * **Plain text is detected, not assumed.** Every assignment and question
 * written before the editor existed holds plain text, and handing that to the
 * HTML renderer would silently eat anything with an angle bracket -- `x < 5`
 * is an ordinary thing to write in a question.
 */
export function RichText({
  html,
  className,
}: {
  html: string | null | undefined;
  className?: string;
}): ReactNode {
  if (!html) return null;
  const formatted = html.includes("<") && html.includes(">");

  if (!formatted) {
    return (
      <p className={cn("whitespace-pre-wrap break-words text-sm", className)}>{html}</p>
    );
  }
  return (
    <div
      className={cn("rich-text text-sm", className)}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
