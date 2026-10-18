"use client";

import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Code2, Database, ExternalLink } from "lucide-react";

import { api } from "@/lib/api/client";
import { Tooltip } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

/**
 * Links to the code editors this person's own courses call for.
 *
 * Which editors those are is a decision stored against the course's category
 * (and overridden per course where needed), never guessed from the title --
 * "Agentic AI & Automation" and "Teens Coding" carry no usable word, and
 * "Python-free Data Literacy" would match exactly backwards.
 *
 * Nothing renders when the answer is empty, which is the ordinary case for a
 * guardian or a corporate manager: they are watching somebody else do the
 * work, and a link to an editor they have no exercise in is a support question.
 */

interface EditorLink {
  key: "sql" | "python";
  label: string;
  url: string;
}

const ICONS = { sql: Database, python: Code2 } as const;

export function EditorNav({
  enabled,
  onNavigate,
  collapsed = false,
}: {
  enabled: boolean;
  onNavigate?: () => void;
  collapsed?: boolean;
}): ReactNode {
  const { data } = useQuery<EditorLink[]>({
    queryKey: ["editors"],
    queryFn: () => api.get<EditorLink[]>("/editors"),
    enabled,
    // The answer changes when somebody is enrolled or a mapping is edited --
    // rare enough that a session-length cache is right, and the page is
    // reloaded either way after an enrolment.
    staleTime: 10 * 60_000,
  });

  if (!data || data.length === 0) return null;

  if (collapsed) {
    return (
      <div className="w-full flex flex-col items-center">
        <div className="my-1.5 h-px w-7 bg-border-subtle" />
        <ul className="space-y-1 w-full flex flex-col items-center">
          {data.map((editor) => {
            const Icon = ICONS[editor.key] ?? Code2;
            return (
              <li key={editor.key} className="w-full flex justify-center">
                <Tooltip content={editor.label} side="right">
                  <a
                    href={editor.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={onNavigate}
                    aria-label={editor.label}
                    className="flex size-9 items-center justify-center rounded-md text-muted-foreground transition-all duration-200 hover:bg-surface/70 hover:text-foreground"
                  >
                    <Icon className="size-4.5 text-subtle-foreground hover:text-muted-foreground" aria-hidden />
                    <span className="sr-only">{editor.label}</span>
                  </a>
                </Tooltip>
              </li>
            );
          })}
        </ul>
      </div>
    );
  }

  return (
    <div className="px-3 py-2">
      <p className="px-2.5 pb-1.5 text-2xs font-medium uppercase tracking-wide text-subtle-foreground">
        Tools
      </p>
      <ul className="space-y-0.5">
        {data.map((editor) => {
          const Icon = ICONS[editor.key] ?? Code2;
          return (
            <li key={editor.key}>
              <a
                href={editor.url}
                target="_blank"
                /* `noopener` is the security half: without it the opened page
                   gets a handle on this window and can navigate it somewhere
                   else. `noreferrer` keeps our URL out of their logs. */
                rel="noopener noreferrer"
                onClick={onNavigate}
                className={cn(
                  "group flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px]",
                  "font-normal text-muted-foreground transition-all duration-200 ease-out",
                  "hover:bg-surface/70 hover:text-foreground",
                )}
              >
                <Icon
                  className="size-4 shrink-0 text-subtle-foreground transition-colors duration-200 group-hover:text-muted-foreground"
                  aria-hidden
                />
                <span className="truncate">{editor.label}</span>
                <ExternalLink
                  className="ml-auto size-3 shrink-0 text-subtle-foreground opacity-0 transition-opacity group-hover:opacity-100"
                  aria-hidden
                />
                <span className="sr-only">(opens in a new tab)</span>
              </a>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
