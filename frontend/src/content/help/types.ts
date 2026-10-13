/**
 * The shape every help article has.
 *
 * Articles are typed data, not MDX or HTML. Three reasons, and they are the
 * reasons this survives being maintained by somebody who is not a developer:
 *
 * 1. **The template is enforced.** Every article has to say what the reader
 *    will learn, what they need first, the steps, what they should see
 *    afterwards, and what to do when it goes wrong. A prose format lets an
 *    author skip the last two, which are the ones beginners need most.
 * 2. **Links cannot rot.** `related` holds article ids, and a missing id is a
 *    type error at build time rather than a 404 somebody finds in a year.
 * 3. **Search is free and needs no service.** Every block is plain text, so
 *    the index is built from the same data the page renders.
 *
 * Adding an article is adding one object to a section's `articles` array.
 * Nothing else has to change: the navigation, the search index, the
 * previous/next links and the sitemap are all derived from the registry.
 */

/** A single step in a numbered instruction list. */
export type Step = {
  /** One action, in plain words. Bold the exact on-screen label with **…**. */
  text: string;
  /** Optional screenshot showing this step. */
  image?: Screenshot;
  /** Optional clarification shown under the step in smaller text. */
  note?: string;
};

export type Screenshot = {
  /** Path under /help/, e.g. "super-admin/courses.webp". */
  src: string;
  /** What the picture shows, for readers using a screen reader. Required. */
  alt: string;
  /** Shown under the image. Say what to look at, not what the page is called. */
  caption?: string;
};

export type Callout = {
  kind: "tip" | "warning" | "note";
  title?: string;
  body: string;
};

/** A labelled pair in a "what each thing means" list. */
export type Definition = { term: string; detail: string };

export type Block =
  | { type: "paragraph"; text: string }
  | { type: "heading"; text: string }
  | { type: "steps"; items: Step[] }
  | { type: "bullets"; items: string[] }
  | { type: "definitions"; items: Definition[] }
  | { type: "screenshot"; image: Screenshot }
  | { type: "callout"; callout: Callout }
  | { type: "table"; columns: string[]; rows: string[][] };

export type Problem = {
  /** What the reader sees, in their words. */
  symptom: string;
  /** What to do about it. */
  fix: string;
};

export type Article = {
  /** URL segment. Stable for ever once published: people bookmark these. */
  id: string;
  /** Action-oriented and plain, e.g. "How to add a new course". */
  title: string;
  /** One sentence, used on the index, in search results and as the page description. */
  summary: string;
  /** The screen this article is about, as named in the sidebar. */
  feature?: string;
  /** "What you will learn" — one short sentence per outcome. */
  learn: string[];
  /** "Before you begin" — what the reader needs first. Empty means nothing. */
  before?: string[];
  /** The body. */
  body: Block[];
  /** "Expected result" — what the reader should see when it worked. */
  result?: string;
  /** Practical advice that stops a beginner making the usual mistake. */
  tips?: string[];
  /** Things that go wrong, and what to do. */
  problems?: Problem[];
  /** Ids of other articles in the same guide. Checked at build time. */
  related?: string[];
  /**
   * Set when the feature exists but could not be exercised safely, or is not
   * finished. Published with the caveat visible rather than quietly omitted.
   */
  caveat?: string;
};

export type Section = {
  id: string;
  title: string;
  /** One line explaining what this group of articles covers. */
  blurb: string;
  articles: Article[];
};

export type Guide = {
  /** URL segment under /help, e.g. "super-admin". */
  slug: string;
  /** The role as the reader would describe themselves. */
  role: string;
  /** Guide title, e.g. "Super Admin User Guide". */
  title: string;
  /** One paragraph for the landing page and the link preview. */
  intro: string;
  /** Who this guide is for, in the reader's own terms. */
  audience: string;
  /** ISO date, shown as "Last updated". */
  updated: string;
  /**
   * A companion guide for readers who landed on the wrong one.
   *
   * Both student guides are written for the same role holding the same
   * permissions -- what separates them is whether anybody is linked to the
   * account, which the console cannot tell from a student's own token. So one
   * of them is offered in the sidebar and this points at the other, in the
   * reader's own terms rather than the role's.
   */
  sibling?: { slug: string; label: string; when: string };
  sections: Section[];
};

/** Every article in a guide, in reading order. */
export function flatten(guide: Guide): Article[] {
  return guide.sections.flatMap((section) => section.articles);
}

/** The section an article belongs to, for breadcrumbs. */
export function sectionOf(guide: Guide, articleId: string): Section | undefined {
  return guide.sections.find((s) => s.articles.some((a) => a.id === articleId));
}

export function findArticle(guide: Guide, articleId: string): Article | undefined {
  return flatten(guide).find((a) => a.id === articleId);
}

/** Previous and next in reading order, for the footer links. */
export function neighbours(
  guide: Guide,
  articleId: string,
): { previous?: Article; next?: Article } {
  const all = flatten(guide);
  const index = all.findIndex((a) => a.id === articleId);
  if (index < 0) return {};
  return { previous: all[index - 1], next: all[index + 1] };
}

/** Every heading in an article, for the table of contents. */
export function headings(article: Article): string[] {
  return article.body.filter((b) => b.type === "heading").map((b) => b.text);
}

/** A stable anchor id for a heading. */
export function anchorFor(heading: string): string {
  return heading
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");
}

/** Plain text of an article, for the search index. */
export function searchText(article: Article): string {
  const parts: string[] = [article.title, article.summary, ...article.learn];
  for (const block of article.body) {
    switch (block.type) {
      case "paragraph":
      case "heading":
        parts.push(block.text);
        break;
      case "steps":
        parts.push(...block.items.map((s) => `${s.text} ${s.note ?? ""}`));
        break;
      case "bullets":
        parts.push(...block.items);
        break;
      case "definitions":
        parts.push(...block.items.map((d) => `${d.term} ${d.detail}`));
        break;
      case "callout":
        parts.push(`${block.callout.title ?? ""} ${block.callout.body}`);
        break;
      case "table":
        parts.push(block.columns.join(" "), ...block.rows.map((r) => r.join(" ")));
        break;
      case "screenshot":
        parts.push(block.image.alt, block.image.caption ?? "");
        break;
    }
  }
  parts.push(...(article.tips ?? []));
  parts.push(...(article.problems ?? []).flatMap((p) => [p.symptom, p.fix]));
  return parts.join(" ").replace(/\*\*/g, "");
}
