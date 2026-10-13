import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  CircleHelp,
  Info,
  Lightbulb,
  ListChecks,
} from "lucide-react";
import { allArticlePaths, guideBySlug } from "@/content/help";
import {
  anchorFor,
  findArticle,
  headings,
  neighbours,
  sectionOf,
} from "@/content/help/types";
import { ArticleBody } from "@/components/help/article-body";
import { Markup, plain } from "@/components/help/markup";
import { ShareLink } from "@/components/help/share-link";

export function generateStaticParams() {
  return allArticlePaths();
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ role: string; article: string }>;
}): Promise<Metadata> {
  const { role, article: articleId } = await params;
  const guide = guideBySlug(role);
  const article = guide && findArticle(guide, articleId);
  if (!guide || !article) return {};
  const url = `/help/${guide.slug}/${article.id}`;
  return {
    title: article.title,
    description: article.summary,
    alternates: { canonical: url },
    openGraph: {
      title: `${article.title} · ${guide.title}`,
      description: article.summary,
      url,
      type: "article",
    },
    twitter: { card: "summary", title: article.title, description: article.summary },
  };
}

export default async function ArticlePage({
  params,
}: {
  params: Promise<{ role: string; article: string }>;
}) {
  const { role, article: articleId } = await params;
  const guide = guideBySlug(role);
  if (!guide) notFound();
  const article = findArticle(guide, articleId);
  if (!article) notFound();

  const section = sectionOf(guide, article.id);
  const { previous, next } = neighbours(guide, article.id);
  const toc = headings(article);
  const related = (article.related ?? [])
    .map((id) => findArticle(guide, id))
    .filter((a): a is NonNullable<typeof a> => Boolean(a));

  return (
    <main className="min-w-0">
      <nav aria-label="Breadcrumb" className="text-xs text-muted-foreground print:hidden">
        <Link href="/help" className="hover:text-foreground hover:underline">
          Help Center
        </Link>
        <span className="px-1.5" aria-hidden>
          /
        </span>
        <Link href={`/help/${guide.slug}`} className="hover:text-foreground hover:underline">
          {guide.role}
        </Link>
        {section ? (
          <>
            <span className="px-1.5" aria-hidden>
              /
            </span>
            <span>{section.title}</span>
          </>
        ) : null}
      </nav>

      <article className="mt-3 max-w-[48rem]">
        <h1 className="font-display text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
          {article.title}
        </h1>
        <p className="mt-2.5 text-sm leading-7 text-muted-foreground">{article.summary}</p>

        <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground">
          <span>
            Last updated{" "}
            {new Date(guide.updated).toLocaleDateString("en-GB", {
              day: "numeric",
              month: "long",
              year: "numeric",
            })}
          </span>
          <ShareLink path={`/help/${guide.slug}/${article.id}`} />
        </div>

        {article.caveat ? (
          <p className="mt-5 flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/5 p-3.5 text-xs leading-6 text-muted-foreground">
            <Info className="mt-0.5 size-3.5 shrink-0 text-warning" aria-hidden />
            <span>{article.caveat}</span>
          </p>
        ) : null}

        {/* What you will learn */}
        <section className="mt-6 rounded-lg border border-border bg-muted/30 p-4">
          <h2 className="flex items-center gap-2 text-xs font-semibold text-foreground">
            <ListChecks className="size-3.5 text-primary" aria-hidden />
            What you will learn
          </h2>
          <ul className="mt-2 space-y-1.5">
            {article.learn.map((item) => (
              <li
                key={item}
                className="relative pl-4 text-sm leading-6 text-muted-foreground before:absolute before:left-0 before:top-2.5 before:size-1 before:rounded-full before:bg-primary"
              >
                {item}
              </li>
            ))}
          </ul>
        </section>

        {/* Before you begin */}
        {article.before?.length ? (
          <section className="mt-5">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Before you begin
            </h2>
            <ul className="mt-2 space-y-1.5">
              {article.before.map((item) => (
                <li
                  key={item}
                  className="relative pl-4 text-sm leading-6 text-muted-foreground before:absolute before:left-0 before:top-2.5 before:size-1 before:rounded-full before:bg-border"
                >
                  <Markup text={item} />
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {/* On this page — only worth showing when there is something to jump to. */}
        {toc.length > 1 ? (
          <nav
            aria-label="On this page"
            className="mt-6 rounded-lg border border-border p-4 print:hidden"
          >
            <h2 className="text-2xs font-semibold uppercase tracking-wide text-muted-foreground">
              On this page
            </h2>
            <ul className="mt-2 space-y-1">
              {toc.map((heading) => (
                <li key={heading}>
                  <a
                    href={`#${anchorFor(heading)}`}
                    className="text-sm text-muted-foreground hover:text-foreground hover:underline"
                  >
                    {heading}
                  </a>
                </li>
              ))}
            </ul>
          </nav>
        ) : null}

        <div className="mt-8">
          <ArticleBody blocks={article.body} />
        </div>

        {article.result ? (
          <section className="mt-8 rounded-lg border border-success/30 bg-success/5 p-4">
            <h2 className="flex items-center gap-2 text-xs font-semibold text-foreground">
              <CheckCircle2 className="size-3.5 text-success" aria-hidden />
              What you should see
            </h2>
            <p className="mt-1.5 text-sm leading-6 text-muted-foreground">
              <Markup text={article.result} />
            </p>
          </section>
        ) : null}

        {article.tips?.length ? (
          <section className="mt-6">
            <h2 className="flex items-center gap-2 font-display text-base font-semibold text-foreground">
              <Lightbulb className="size-4 text-primary" aria-hidden />
              Helpful tips
            </h2>
            <ul className="mt-2 space-y-1.5">
              {article.tips.map((tip) => (
                <li
                  key={tip}
                  className="relative pl-4 text-sm leading-6 text-muted-foreground before:absolute before:left-0 before:top-2.5 before:size-1 before:rounded-full before:bg-primary/60"
                >
                  <Markup text={tip} />
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {article.problems?.length ? (
          <section className="mt-7">
            <h2 className="flex items-center gap-2 font-display text-base font-semibold text-foreground">
              <CircleHelp className="size-4 text-primary" aria-hidden />
              If something goes wrong
            </h2>
            <dl className="mt-3 space-y-3">
              {article.problems.map((problem) => (
                <div key={problem.symptom} className="rounded-lg border border-border p-3.5">
                  <dt className="text-sm font-medium text-foreground">
                    <Markup text={problem.symptom} />
                  </dt>
                  <dd className="mt-1 text-sm leading-6 text-muted-foreground">
                    <Markup text={problem.fix} />
                  </dd>
                </div>
              ))}
            </dl>
          </section>
        ) : null}

        {related.length ? (
          <section className="mt-7 print:hidden">
            <h2 className="font-display text-base font-semibold text-foreground">
              Related articles
            </h2>
            <ul className="mt-2.5 grid gap-2 sm:grid-cols-2">
              {related.map((item) => (
                <li key={item.id}>
                  <Link
                    href={`/help/${guide.slug}/${item.id}`}
                    className="block rounded-lg border border-border p-3 text-sm text-foreground transition-colors hover:border-primary/40 hover:bg-accent/40"
                  >
                    {item.title}
                    <span className="mt-0.5 block text-xs text-muted-foreground">
                      {plain(item.summary)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        <nav
          aria-label="Article navigation"
          className="mt-10 flex flex-col gap-2.5 border-t border-border pt-5 sm:flex-row sm:justify-between print:hidden"
        >
          {previous ? (
            <Link
              href={`/help/${guide.slug}/${previous.id}`}
              className="group flex items-center gap-2 rounded-lg border border-border p-3 text-sm sm:max-w-[48%]"
            >
              <ArrowLeft className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
              <span className="min-w-0">
                <span className="block text-2xs uppercase tracking-wide text-muted-foreground">
                  Previous
                </span>
                <span className="block truncate text-foreground">{previous.title}</span>
              </span>
            </Link>
          ) : (
            <span />
          )}
          {next ? (
            <Link
              href={`/help/${guide.slug}/${next.id}`}
              className="group flex items-center gap-2 rounded-lg border border-border p-3 text-right text-sm sm:ml-auto sm:max-w-[48%]"
            >
              <span className="min-w-0 flex-1">
                <span className="block text-2xs uppercase tracking-wide text-muted-foreground">
                  Next
                </span>
                <span className="block truncate text-foreground">{next.title}</span>
              </span>
              <ArrowRight className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
            </Link>
          ) : null}
        </nav>
      </article>
    </main>
  );
}
