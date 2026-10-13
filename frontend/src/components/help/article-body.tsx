import type { ReactNode } from "react";
import { AlertTriangle, Info, Lightbulb } from "lucide-react";
import type { Block, Callout } from "@/content/help/types";
import { anchorFor } from "@/content/help/types";
import { Markup } from "./markup";
import { HelpScreenshot } from "./screenshot";
import { cn } from "@/lib/utils";

/**
 * Renders an article's blocks.
 *
 * Every block type is handled explicitly and the switch is exhaustive, so
 * adding a block type to the model is a type error here until it is given a
 * shape on screen. That is the point: content and presentation cannot drift
 * apart silently.
 */

const CALLOUT_STYLES: Record<Callout["kind"], { ring: string; icon: typeof Info; label: string }> = {
  tip: { ring: "border-success/30 bg-success/5", icon: Lightbulb, label: "Tip" },
  warning: { ring: "border-warning/40 bg-warning/5", icon: AlertTriangle, label: "Take care" },
  note: { ring: "border-info/30 bg-info/5", icon: Info, label: "Note" },
};

function CalloutBox({ callout }: { callout: Callout }): ReactNode {
  const style = CALLOUT_STYLES[callout.kind];
  const Icon = style.icon;
  return (
    <div className={cn("my-5 rounded-lg border p-4", style.ring)}>
      <p className="flex items-center gap-2 text-xs font-semibold text-foreground">
        <Icon className="size-3.5" aria-hidden />
        {callout.title ?? style.label}
      </p>
      <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
        <Markup text={callout.body} />
      </p>
    </div>
  );
}

export function ArticleBody({ blocks }: { blocks: Block[] }): ReactNode {
  return (
    <>
      {blocks.map((block, index) => {
        switch (block.type) {
          case "heading":
            return (
              <h2
                key={index}
                id={anchorFor(block.text)}
                className="mt-9 scroll-mt-24 font-display text-lg font-semibold tracking-tight text-foreground first:mt-0"
              >
                {block.text}
              </h2>
            );

          case "paragraph":
            return (
              <p key={index} className="mt-4 text-sm leading-7 text-muted-foreground">
                <Markup text={block.text} />
              </p>
            );

          case "bullets":
            return (
              <ul key={index} className="mt-4 space-y-2">
                {block.items.map((item, i) => (
                  <li
                    key={i}
                    className="relative pl-5 text-sm leading-7 text-muted-foreground before:absolute before:left-1 before:top-3 before:size-1.5 before:rounded-full before:bg-border"
                  >
                    <Markup text={item} />
                  </li>
                ))}
              </ul>
            );

          case "steps":
            return (
              <ol key={index} className="mt-5 space-y-4">
                {block.items.map((step, i) => (
                  <li key={i} className="flex gap-3.5">
                    <span
                      className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-2xs font-semibold tabular-nums text-primary"
                      aria-hidden
                    >
                      {i + 1}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm leading-7 text-muted-foreground">
                        <span className="sr-only">{`Step ${i + 1}. `}</span>
                        <Markup text={step.text} />
                      </p>
                      {step.note ? (
                        <p className="mt-1 text-xs leading-6 text-subtle-foreground">
                          <Markup text={step.note} />
                        </p>
                      ) : null}
                      {step.image ? <HelpScreenshot image={step.image} /> : null}
                    </div>
                  </li>
                ))}
              </ol>
            );

          case "definitions":
            return (
              <dl key={index} className="mt-5 space-y-3">
                {block.items.map((item, i) => (
                  <div key={i} className="rounded-lg border border-border bg-card p-3.5">
                    <dt className="text-sm font-semibold text-foreground">{item.term}</dt>
                    <dd className="mt-1 text-sm leading-6 text-muted-foreground">
                      <Markup text={item.detail} />
                    </dd>
                  </div>
                ))}
              </dl>
            );

          case "table":
            return (
              <div key={index} className="mt-5 overflow-x-auto rounded-lg border border-border">
                <table className="w-full min-w-[32rem] border-collapse text-sm">
                  <thead>
                    <tr className="bg-muted/50">
                      {block.columns.map((column) => (
                        <th
                          key={column}
                          scope="col"
                          className="px-3.5 py-2.5 text-left text-2xs font-semibold uppercase tracking-wide text-muted-foreground"
                        >
                          {column}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {block.rows.map((row, i) => (
                      <tr key={i} className="border-t border-border align-top">
                        {row.map((cell, j) => (
                          <td key={j} className="px-3.5 py-2.5 leading-6 text-muted-foreground">
                            <Markup text={cell} />
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );

          case "screenshot":
            return <HelpScreenshot key={index} image={block.image} />;

          case "callout":
            return <CalloutBox key={index} callout={block.callout} />;
        }
      })}
    </>
  );
}
