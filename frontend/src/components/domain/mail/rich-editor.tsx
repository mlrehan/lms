"use client";

import { useCallback, useEffect } from "react";
import { EditorContent, useEditor, type Editor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { Bold, Italic, Link2, List, ListOrdered, Quote, Redo2, RemoveFormatting, Strikethrough, Underline as UnderlineIcon, Undo2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * A small rich-text editor for message bodies: bold, italic, underline, strike-through, lists, quote and links.
 *
 * What it produces is only ever a *request*: the server re-parses the HTML and keeps a short allow-list of
 * formatting tags (`services/mail_html.py`), so nothing pasted here can carry a script into another person's
 * browser. The editor's own formatting options simply match what the server will keep.
 */
export function RichEditor({
  initialHtml,
  onChange,
  placeholder = "Write your message",
  disabled,
  className,
}: {
  initialHtml: string;
  onChange: (html: string, text: string) => void;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
}) {
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: false,
        codeBlock: false,
        code: false,
        horizontalRule: false,
        link: { openOnClick: false, autolink: true, protocols: ["http", "https", "mailto"], HTMLAttributes: { rel: "noopener noreferrer nofollow" } },
      }),
    ],
    content: initialHtml,
    editable: !disabled,
    immediatelyRender: false, // the console renders on the client; skipping the server render avoids a hydration mismatch
    editorProps: {
      attributes: {
        class: "mail-body min-h-40 px-3 py-2 text-sm outline-none",
        "aria-label": "Message body",
        "data-placeholder": placeholder,
      },
    },
    onUpdate: ({ editor: e }) => onChange(e.isEmpty ? "" : e.getHTML(), e.getText()),
  });

  useEffect(() => {
    editor?.setEditable(!disabled);
  }, [editor, disabled]);

  return (
    <div className={cn("overflow-hidden rounded-lg border border-border bg-surface focus-within:ring-2 focus-within:ring-primary", className)}>
      <Toolbar editor={editor} />
      <EditorContent editor={editor} />
    </div>
  );
}

function Toolbar({ editor }: { editor: Editor | null }) {
  const setLink = useCallback(() => {
    if (!editor) return;
    const previous = editor.getAttributes("link").href as string | undefined;
    const url = window.prompt("Link address", previous ?? "https://");
    if (url === null) return;
    if (url.trim() === "") {
      editor.chain().focus().extendMarkRange("link").unsetLink().run();
      return;
    }
    // The server accepts only http, https and mailto; a bare address is treated as https.
    const href = /^(https?:|mailto:)/i.test(url.trim()) ? url.trim() : `https://${url.trim()}`;
    editor.chain().focus().extendMarkRange("link").setLink({ href }).run();
  }, [editor]);

  if (!editor) return <div className="h-9 border-b border-border" />;

  const tool = (label: string, icon: React.ReactNode, active: boolean, run: () => void, disabled = false) => (
    <Button
      key={label}
      type="button"
      variant={active ? "secondary" : "ghost"}
      size="icon"
      aria-label={label}
      aria-pressed={active}
      title={label}
      disabled={disabled}
      // Keep the selection: a normal click would move focus out of the editor before the command ran.
      onMouseDown={(event) => event.preventDefault()}
      onClick={run}
      className="size-8"
    >
      {icon}
    </Button>
  );

  return (
    <div role="toolbar" aria-label="Formatting" className="flex flex-wrap items-center gap-0.5 border-b border-border bg-surface-muted px-1.5 py-1">
      {tool("Undo", <Undo2 />, false, () => editor.chain().focus().undo().run(), !editor.can().undo())}
      {tool("Redo", <Redo2 />, false, () => editor.chain().focus().redo().run(), !editor.can().redo())}
      <span className="mx-1 h-5 w-px bg-border" aria-hidden />
      {tool("Bold", <Bold />, editor.isActive("bold"), () => editor.chain().focus().toggleBold().run())}
      {tool("Italic", <Italic />, editor.isActive("italic"), () => editor.chain().focus().toggleItalic().run())}
      {tool("Underline", <UnderlineIcon />, editor.isActive("underline"), () => editor.chain().focus().toggleUnderline().run())}
      {tool("Strikethrough", <Strikethrough />, editor.isActive("strike"), () => editor.chain().focus().toggleStrike().run())}
      <span className="mx-1 h-5 w-px bg-border" aria-hidden />
      {tool("Bulleted list", <List />, editor.isActive("bulletList"), () => editor.chain().focus().toggleBulletList().run())}
      {tool("Numbered list", <ListOrdered />, editor.isActive("orderedList"), () => editor.chain().focus().toggleOrderedList().run())}
      {tool("Quote", <Quote />, editor.isActive("blockquote"), () => editor.chain().focus().toggleBlockquote().run())}
      {tool("Link", <Link2 />, editor.isActive("link"), setLink)}
      <span className="mx-1 h-5 w-px bg-border" aria-hidden />
      {tool("Clear formatting", <RemoveFormatting />, false, () => editor.chain().focus().clearNodes().unsetAllMarks().run())}
    </div>
  );
}
