import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowRight, CalendarDays, FileText } from "lucide-react";
import { articleCount, guideBySlug } from "@/content/help";
import { ShareLink } from "@/components/help/share-link";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ role: string }>;
}): Promise<Metadata> {
  const { role } = await params;
  const guide = guideBySlug(role);
  if (!guide) return {};
  return {
    title: guide.title,
    description: guide.intro,
    alternates: { canonical: `/help/${guide.slug}` },
    openGraph: {
      title: guide.title,
      description: guide.intro,
      url: `/help/${guide.slug}`,
      type: "article",
    },
    twitter: { card: "summary", title: guide.title, description: guide.intro },
  };
}

export default async function GuideLandingPage({
  params,
}: {
  params: Promise<{ role: string }>;
}) {
  const { role } = await params;
  const guide = guideBySlug(role);
  if (!guide) notFound();

  const first = guide.sections[0]?.articles[0];

  return (
    <main>
      <nav aria-label="Breadcrumb" className="text-xs text-muted-foreground">
        <Link href="/help" className="hover:text-foreground hover:underline">
          Help Center
        </Link>
        <span className="px-1.5" aria-hidden>
          /
        </span>
        <span className="text-foreground">{guide.title}</span>
      </nav>

      <h1 className="mt-3 font-display text-3xl font-semibold tracking-tight text-foreground">
        {guide.title}
      </h1>
      <p className="mt-3 max-w-2xl text-sm leading-7 text-muted-foreground">{guide.intro}</p>

      <div className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <FileText className="size-3.5" aria-hidden />
          {articleCount(guide)} articles
        </span>
        <span className="flex items-center gap-1.5">
          <CalendarDays className="size-3.5" aria-hidden />
          Last updated{" "}
          {new Date(guide.updated).toLocaleDateString("en-GB", {
            day: "numeric",
            month: "long",
            year: "numeric",
          })}
        </span>
        <ShareLink path={`/help/${guide.slug}`} />
      </div>

      {/* A reader offered the wrong one of a pair should be able to switch in a
          click, rather than going back out to the Help Center to work out which
          of two similarly-named guides is theirs. */}
      {guide.sibling ? (
        <p className="mt-5 max-w-2xl rounded-lg border border-border bg-muted/40 px-4 py-3 text-sm leading-6 text-muted-foreground">
          {guide.sibling.when}{" "}
          <Link
            href={`/help/${guide.sibling.slug}`}
            className="font-medium text-foreground underline underline-offset-2 hover:text-primary"
          >
            {guide.sibling.label}
          </Link>
          .
        </p>
      ) : null}

      {first ? (
        <Link
          href={`/help/${guide.slug}/${first.id}`}
          className="mt-6 inline-flex items-center gap-1.5 rounded-md bg-primary px-3.5 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          Start reading
          <ArrowRight className="size-3.5" aria-hidden />
        </Link>
      ) : null}

      <div className="mt-10 space-y-8">
        {guide.sections.map((section) => (
          <section key={section.id} aria-labelledby={`section-${section.id}`}>
            <h2
              id={`section-${section.id}`}
              className="font-display text-lg font-semibold tracking-tight text-foreground"
            >
              {section.title}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">{section.blurb}</p>
            <ul className="mt-3 grid gap-2.5 sm:grid-cols-2">
              {section.articles.map((article) => (
                <li key={article.id}>
                  <Link
                    href={`/help/${guide.slug}/${article.id}`}
                    className="group block h-full rounded-lg border border-border bg-card p-3.5 transition-colors hover:border-primary/40 hover:bg-accent/40"
                  >
                    <span className="block text-sm font-medium text-foreground">
                      {article.title}
                    </span>
                    <span className="mt-1 block text-xs leading-6 text-muted-foreground">
                      {article.summary}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </main>
  );
}
