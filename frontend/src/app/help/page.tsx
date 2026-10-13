import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight, BookOpen } from "lucide-react";
import { GUIDES, articleCount } from "@/content/help";

export const metadata: Metadata = {
  title: "Help Center",
  description:
    "Choose your role to open a step-by-step guide to the learning management system.",
};

/**
 * The Help Center front door.
 *
 * It lists only guides that exist. Roles whose guide has not been written are
 * named plainly as "coming soon" rather than linked to an empty page --
 * a reader who follows a link to nothing assumes the whole site is broken.
 */
const PLANNED = [
  "Tutor",
  "Corporate Manager",
  "Guardian",
  "Student (managed account)",
  "Student (individual account)",
];

export default function HelpHomePage() {
  const published = new Set(GUIDES.map((g) => g.role));
  const pending = PLANNED.filter((role) => !published.has(role));

  return (
    <main className="mx-auto max-w-[82rem] px-4 py-12 sm:px-6">
      <div className="max-w-2xl">
        <h1 className="font-display text-3xl font-semibold tracking-tight text-foreground">
          How can we help?
        </h1>
        <p className="mt-3 text-sm leading-7 text-muted-foreground">
          Choose the guide that matches your account. Each one explains every screen you can see,
          step by step, with pictures. You do not need any technical knowledge, and you do not need
          to be signed in to read them.
        </p>
      </div>

      <h2 className="mt-10 text-2xs font-semibold uppercase tracking-wide text-muted-foreground">
        Available guides
      </h2>
      <ul className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {GUIDES.map((guide) => (
          <li key={guide.slug}>
            <Link
              href={`/help/${guide.slug}`}
              className="group flex h-full flex-col rounded-xl border border-border bg-card p-5 transition-colors hover:border-primary/40 hover:bg-accent/40"
            >
              <span className="flex size-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <BookOpen className="size-4" aria-hidden />
              </span>
              <span className="mt-3 font-display text-base font-semibold text-foreground">
                {guide.title}
              </span>
              <span className="mt-1.5 flex-1 text-sm leading-6 text-muted-foreground">
                {guide.audience}
              </span>
              <span className="mt-4 flex items-center gap-1.5 text-xs font-medium text-primary">
                {articleCount(guide)} articles
                <ArrowRight
                  className="size-3 transition-transform group-hover:translate-x-0.5"
                  aria-hidden
                />
              </span>
            </Link>
          </li>
        ))}
      </ul>

      {pending.length ? (
        <>
          <h2 className="mt-10 text-2xs font-semibold uppercase tracking-wide text-muted-foreground">
            Coming soon
          </h2>
          <ul className="mt-3 flex flex-wrap gap-2">
            {pending.map((role) => (
              <li
                key={role}
                className="rounded-md border border-dashed border-border px-3 py-1.5 text-xs text-muted-foreground"
              >
                {role}
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </main>
  );
}
