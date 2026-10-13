"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronDown, Menu, X } from "lucide-react";
import type { Guide } from "@/content/help/types";
import { cn } from "@/lib/utils";
import { HelpSearch } from "./search";

/**
 * The guide's contents, as a left column on a wide screen and a drawer on a
 * phone.
 *
 * The section holding the open article starts expanded and the others start
 * collapsed, so a reader lands looking at where they are rather than at a
 * list of forty links. Opening another section does not close this one --
 * people compare.
 */
export function GuideNav({ guide }: { guide: Guide }) {
  const pathname = usePathname();
  const [drawerOpen, setDrawerOpen] = useState(false);

  const currentId = pathname.split("/").filter(Boolean).pop();
  const openSection = guide.sections.find((s) => s.articles.some((a) => a.id === currentId));

  // On a phone the drawer must close when the reader picks an article,
  // otherwise the article they chose is hidden behind it. Done on the link
  // itself rather than in an effect watching the path: the close belongs to
  // the click that caused it, and an effect here would set state during
  // render for the same result.
  const close = () => setDrawerOpen(false);

  const contents = (
    <nav aria-label={`${guide.title} contents`} className="space-y-1">
      <Link
        href={`/help/${guide.slug}`}
        onClick={close}
        className={cn(
          "block rounded-md px-3 py-2 text-sm font-medium transition-colors",
          pathname === `/help/${guide.slug}`
            ? "bg-accent text-accent-foreground"
            : "text-muted-foreground hover:bg-muted hover:text-foreground",
        )}
      >
        Guide home
      </Link>
      {guide.sections.map((section) => (
        <SectionGroup
          key={section.id}
          guideSlug={guide.slug}
          section={section}
          currentId={currentId}
          defaultOpen={section.id === openSection?.id}
          onNavigate={close}
        />
      ))}
    </nav>
  );

  return (
    <>
      {/* Phone: a bar that opens the contents as a drawer. */}
      <div className="sticky top-0 z-30 flex items-center gap-2 border-b border-border bg-background/95 px-4 py-2.5 backdrop-blur lg:hidden print:hidden">
        <button
          type="button"
          onClick={() => setDrawerOpen(true)}
          className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs font-medium"
          aria-expanded={drawerOpen}
        >
          <Menu className="size-3.5" />
          Contents
        </button>
        <div className="min-w-0 flex-1">
          <HelpSearch guide={guide} compact />
        </div>
      </div>

      {drawerOpen ? (
        <div className="fixed inset-0 z-50 lg:hidden print:hidden">
          <div
            className="absolute inset-0 bg-slate-950/40"
            onClick={() => setDrawerOpen(false)}
            aria-hidden
          />
          <div className="absolute inset-y-0 left-0 w-[17rem] max-w-[85vw] overflow-y-auto border-r border-border bg-background p-4">
            <div className="mb-3 flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Contents
              </span>
              <button
                type="button"
                onClick={() => setDrawerOpen(false)}
                aria-label="Close contents"
                className="rounded-md p-1 text-muted-foreground hover:bg-muted"
              >
                <X className="size-4" />
              </button>
            </div>
            {contents}
          </div>
        </div>
      ) : null}

      {/* Desktop: a column that scrolls with the page. */}
      <aside className="hidden w-[17rem] shrink-0 lg:block print:hidden">
        <div className="sticky top-6 max-h-[calc(100dvh-3rem)] overflow-y-auto pr-2">
          <HelpSearch guide={guide} />
          <div className="mt-4">{contents}</div>
        </div>
      </aside>
    </>
  );
}

function SectionGroup({
  guideSlug,
  section,
  currentId,
  defaultOpen,
  onNavigate,
}: {
  guideSlug: string;
  section: Guide["sections"][number];
  currentId?: string;
  defaultOpen: boolean;
  onNavigate: () => void;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="pt-1">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-left text-2xs font-semibold uppercase tracking-wide text-muted-foreground hover:bg-muted hover:text-foreground"
      >
        {section.title}
        <ChevronDown
          className={cn("size-3 shrink-0 transition-transform", open ? "rotate-180" : undefined)}
          aria-hidden
        />
      </button>
      {open ? (
        <ul className="mt-0.5 space-y-0.5 border-l border-border pl-2">
          {section.articles.map((article) => {
            const active = article.id === currentId;
            return (
              <li key={article.id}>
                <Link
                  href={`/help/${guideSlug}/${article.id}`}
                  onClick={onNavigate}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "block rounded-md px-2.5 py-1.5 text-sm leading-6 transition-colors",
                    active
                      ? "bg-accent font-medium text-accent-foreground"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground",
                  )}
                >
                  {article.title}
                </Link>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}
