"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { FileWarning } from "lucide-react";
import { EmptyState, InlineSpinner } from "@/components/ui/states";
import { readDelimited, readDocument, readSpreadsheet, type DocBlock, type DocRun, type SheetGrid } from "./office";

/**
 * The renderers that need the file's *contents* rather than just a URL.
 *
 * Images, video and audio are not here: the browser fetches those itself from
 * a `src`, which is both less code and better behaved -- a `<video>` asks for
 * byte ranges as the viewer scrubs, and our preview endpoint answers them.
 *
 * Everything in this file instead fetches once, through the same cookie-bearing
 * same-origin request every other call uses, and renders **React elements built
 * from parsed data**. No `innerHTML` anywhere: these are files a tenant
 * uploaded, and assembling markup from their contents is how an uploaded
 * document becomes script running on this origin.
 */

type Loaded<T> =
  | { state: "loading" }
  | { state: "failed"; problem: string }
  | { state: "ready"; value: T };

/**
 * Fetch a file once, and abandon it if the viewer moves on.
 *
 * The abort matters more than it looks: clicking through a list leaves a
 * request per file in flight, and without it the one that happens to finish
 * last paints over whatever the person is actually looking at.
 */
function useFile(src: string, as: "bytes" | "text"): Loaded<Uint8Array | string> {
  const [result, setResult] = useState<Loaded<Uint8Array | string>>({ state: "loading" });

  // Reset during render, not at the top of the effect: a synchronous
  // `setState` there paints the previous file's contents once before
  // correcting itself, and the React compiler rejects it outright.
  const [loadedFrom, setLoadedFrom] = useState(src);
  if (loadedFrom !== src) {
    setLoadedFrom(src);
    setResult({ state: "loading" });
  }

  useEffect(() => {
    const controller = new AbortController();

    void (async () => {
      try {
        const response = await fetch(src, {
          credentials: "same-origin",
          signal: controller.signal,
        });
        if (!response.ok) {
          throw new Error(
            response.status === 403
              ? "You do not have access to this file."
              : `The file could not be loaded (${response.status}).`,
          );
        }
        const value =
          as === "text" ? await response.text() : new Uint8Array(await response.arrayBuffer());
        if (!controller.signal.aborted) setResult({ state: "ready", value });
      } catch (error) {
        if (controller.signal.aborted) return;
        setResult({
          state: "failed",
          problem: error instanceof Error ? error.message : "The file could not be read.",
        });
      }
    })();

    return () => controller.abort();
  }, [src, as]);

  return result;
}

/**
 * Parse what was fetched, once per payload.
 *
 * Kept out of `useFile` deliberately. The hook used to take the parser as a
 * callback, and every caller passed an inline `async (response) => ...` -- a
 * new function on each render, so the effect re-ran the moment the first
 * response set state and **every file was fetched twice**, the first request
 * aborted by its own cleanup. Found by watching the network panel, not by any
 * test. Both arguments here are primitives, so the effect runs when the file
 * changes and at no other time.
 */
function useParsed<T>(loaded: Loaded<Uint8Array | string>, parse: (value: never) => T): Loaded<T> {
  return useMemo(() => {
    if (loaded.state !== "ready") return loaded;
    try {
      return { state: "ready" as const, value: parse(loaded.value as never) };
    } catch (error) {
      return {
        state: "failed" as const,
        problem: error instanceof Error ? error.message : "The file could not be read.",
      };
    }
    // `parse` is a module-level reader chosen by the caller's own branch; it
    // is the payload that decides the result.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded]);
}

function Busy({ label }: { label: string }): ReactNode {
  return (
    <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
      <InlineSpinner /> {label}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Spreadsheets                                                                */
/* -------------------------------------------------------------------------- */

function Grid({ grid }: { grid: SheetGrid }): ReactNode {
  const width = grid.rows.reduce((widest, row) => Math.max(widest, row.length), 0);
  if (width === 0) return <p className="p-6 text-sm text-muted-foreground">This sheet is empty.</p>;

  // The first row is treated as headings. It is right far more often than it
  // is wrong for the mark sheets and registers this actually shows, and when
  // it is wrong the row is still legible -- just bold.
  const [headings, ...body] = grid.rows;

  return (
    <div className="h-full overflow-auto">
      <table className="w-max min-w-full border-collapse text-sm">
        <thead className="sticky top-0 bg-surface-muted">
          <tr>
            <th className="sticky left-0 z-10 w-10 border border-border-subtle bg-surface-muted px-2 py-1 text-right text-2xs font-normal text-subtle-foreground">
              #
            </th>
            {Array.from({ length: width }, (_, column) => (
              <th
                key={column}
                className="whitespace-nowrap border border-border-subtle px-2 py-1 text-left font-medium"
              >
                {headings?.[column] ?? ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((row, index) => (
            <tr key={index} className="even:bg-muted/30">
              <td className="sticky left-0 z-10 border border-border-subtle bg-surface px-2 py-1 text-right text-2xs text-subtle-foreground">
                {index + 2}
              </td>
              {Array.from({ length: width }, (_, column) => (
                <td
                  key={column}
                  className="whitespace-nowrap border border-border-subtle px-2 py-1 tabular-nums"
                >
                  {row[column] ?? ""}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function SheetView({ src, delimited }: { src: string; delimited: boolean }): ReactNode {
  const fetched = useFile(src, delimited ? "text" : "bytes");
  const loaded = useParsed<SheetGrid[]>(
    fetched,
    delimited
      ? (value: string) => [readDelimited(value)]
      : (value: Uint8Array) => readSpreadsheet(value),
  );
  const [sheet, setSheet] = useState(0);

  if (loaded.state === "loading") return <Busy label="Opening the spreadsheet…" />;
  if (loaded.state === "failed") {
    return <EmptyState icon={<FileWarning />} title="This spreadsheet could not be opened" description={loaded.problem} />;
  }

  const grids = loaded.value;
  const current = grids[Math.min(sheet, grids.length - 1)];
  if (!current) return <p className="p-6 text-sm text-muted-foreground">Nothing to show.</p>;

  return (
    <div className="flex h-full min-h-0 flex-col">
      {grids.length > 1 ? (
        <div className="flex flex-wrap gap-1 border-b border-border-subtle px-2 py-1.5">
          {grids.map((grid, index) => (
            <button
              key={grid.name}
              type="button"
              onClick={() => setSheet(index)}
              className={
                index === sheet
                  ? "rounded-md bg-accent px-2 py-0.5 text-xs font-medium"
                  : "rounded-md px-2 py-0.5 text-xs text-muted-foreground hover:bg-muted/60"
              }
            >
              {grid.name}
            </button>
          ))}
        </div>
      ) : null}
      <div className="min-h-0 flex-1">
        <Grid grid={current} />
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Word documents                                                              */
/* -------------------------------------------------------------------------- */

function Runs({ runs }: { runs: DocRun[] }): ReactNode {
  if (runs.length === 0) return <>&nbsp;</>;
  return (
    <>
      {runs.map((run, index) => {
        const content = run.bold ? <strong>{run.text}</strong> : run.text;
        return (
          <span key={index} className={run.italic ? "italic" : undefined}>
            {content}
          </span>
        );
      })}
    </>
  );
}

function Block({ block }: { block: DocBlock }): ReactNode {
  if (block.kind === "table") {
    return (
      <div className="my-3 overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <tbody>
            {block.rows.map((row, r) => (
              <tr key={r}>
                {row.map((cell, c) => (
                  <td key={c} className="border border-border-subtle px-2 py-1 align-top">
                    <Runs runs={cell} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  if (block.heading) {
    const sizes = ["text-2xl", "text-xl", "text-lg", "text-base", "text-sm", "text-sm"];
    return (
      <p className={`mt-4 mb-1 font-semibold ${sizes[block.heading - 1] ?? "text-base"}`}>
        <Runs runs={block.runs} />
      </p>
    );
  }

  if (block.listed) {
    return (
      <p className="my-1 ps-5 before:absolute before:-ms-4 before:content-['•'] relative">
        <Runs runs={block.runs} />
      </p>
    );
  }

  return (
    <p className="my-2 leading-relaxed">
      <Runs runs={block.runs} />
    </p>
  );
}

export function DocView({ src }: { src: string }): ReactNode {
  const loaded = useParsed<DocBlock[]>(useFile(src, "bytes"), (value: Uint8Array) =>
    readDocument(value),
  );

  if (loaded.state === "loading") return <Busy label="Opening the document…" />;
  if (loaded.state === "failed") {
    return <EmptyState icon={<FileWarning />} title="This document could not be opened" description={loaded.problem} />;
  }
  return (
    <div className="h-full overflow-auto bg-surface-muted p-4">
      <article className="mx-auto max-w-3xl rounded-lg bg-surface p-6 text-sm shadow-sm sm:p-8">
        {loaded.value.map((block, index) => (
          <Block key={index} block={block} />
        ))}
      </article>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Plain text and markdown                                                     */
/* -------------------------------------------------------------------------- */

/** Inline markdown: code, bold, italic, links. Built as elements, never HTML. */
function inline(source: string, keyPrefix: string): ReactNode[] {
  const pattern = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*]+\*)|(\[[^\]]+\]\((https?:\/\/[^)\s]+)\))/g;
  const out: ReactNode[] = [];
  let last = 0;
  let match: RegExpExecArray | null;
  let index = 0;

  while ((match = pattern.exec(source)) !== null) {
    if (match.index > last) out.push(source.slice(last, match.index));
    const token = match[0];
    const key = `${keyPrefix}-${index++}`;
    if (token.startsWith("`")) {
      out.push(
        <code key={key} className="rounded bg-muted px-1 py-0.5 text-[0.9em]">
          {token.slice(1, -1)}
        </code>,
      );
    } else if (token.startsWith("**")) {
      out.push(<strong key={key}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("*")) {
      out.push(<em key={key}>{token.slice(1, -1)}</em>);
    } else {
      const label = token.slice(1, token.indexOf("]"));
      const href = match[5] ?? "#";
      out.push(
        // http(s) only, by the pattern above. A `javascript:` URL cannot
        // match, which is the reason the scheme is in the regular expression
        // rather than checked afterwards.
        <a
          key={key}
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary underline underline-offset-2"
        >
          {label}
        </a>,
      );
    }
    last = match.index + token.length;
  }
  if (last < source.length) out.push(source.slice(last));
  return out;
}

function Markdown({ source }: { source: string }): ReactNode {
  const lines = source.split(/\r?\n/);
  const blocks: ReactNode[] = [];
  let paragraph: string[] = [];
  let list: string[] = [];
  let fence: string[] | null = null;

  const flushParagraph = () => {
    if (paragraph.length === 0) return;
    const key = `p-${blocks.length}`;
    blocks.push(
      <p key={key} className="my-2 leading-relaxed">
        {inline(paragraph.join(" "), key)}
      </p>,
    );
    paragraph = [];
  };
  const flushList = () => {
    if (list.length === 0) return;
    const key = `ul-${blocks.length}`;
    blocks.push(
      <ul key={key} className="my-2 list-disc space-y-1 ps-6">
        {list.map((item, index) => (
          <li key={index}>{inline(item, `${key}-${index}`)}</li>
        ))}
      </ul>,
    );
    list = [];
  };

  for (const line of lines) {
    if (line.trimStart().startsWith("```")) {
      if (fence === null) {
        flushParagraph();
        flushList();
        fence = [];
      } else {
        blocks.push(
          <pre
            key={`code-${blocks.length}`}
            className="my-3 overflow-x-auto rounded-lg bg-muted p-3 text-xs"
          >
            <code>{fence.join("\n")}</code>
          </pre>,
        );
        fence = null;
      }
      continue;
    }
    if (fence !== null) {
      fence.push(line);
      continue;
    }

    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      flushParagraph();
      flushList();
      const level = heading[1]!.length;
      const sizes = ["text-2xl", "text-xl", "text-lg", "text-base", "text-sm", "text-sm"];
      blocks.push(
        <p
          key={`h-${blocks.length}`}
          className={`mt-4 mb-1 font-semibold ${sizes[level - 1] ?? "text-base"}`}
        >
          {inline(heading[2]!, `h-${blocks.length}`)}
        </p>,
      );
      continue;
    }
    const bullet = /^\s*[-*+]\s+(.*)$/.exec(line);
    if (bullet) {
      flushParagraph();
      list.push(bullet[1]!);
      continue;
    }
    if (line.trim() === "") {
      flushParagraph();
      flushList();
      continue;
    }
    flushList();
    paragraph.push(line.trim());
  }
  flushParagraph();
  flushList();
  if (fence !== null) {
    // An unclosed fence is a truncated file, not a reason to drop its tail.
    blocks.push(
      <pre key="code-tail" className="my-3 overflow-x-auto rounded-lg bg-muted p-3 text-xs">
        <code>{fence.join("\n")}</code>
      </pre>,
    );
  }
  return <>{blocks}</>;
}

export function TextView({ src, markdown }: { src: string; markdown: boolean }): ReactNode {
  const loaded = useFile(src, "text") as Loaded<string>;

  if (loaded.state === "loading") return <Busy label="Opening the file…" />;
  if (loaded.state === "failed") {
    return <EmptyState icon={<FileWarning />} title="This file could not be opened" description={loaded.problem} />;
  }
  return (
    <div className="h-full overflow-auto bg-surface-muted p-4">
      <article className="mx-auto max-w-3xl rounded-lg bg-surface p-6 text-sm shadow-sm sm:p-8">
        {markdown ? (
          <Markdown source={loaded.value} />
        ) : (
          <pre className="whitespace-pre-wrap break-words font-sans leading-relaxed">
            {loaded.value}
          </pre>
        )}
      </article>
    </div>
  );
}
