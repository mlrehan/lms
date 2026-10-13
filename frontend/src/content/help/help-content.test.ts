import { existsSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { GUIDES, allArticlePaths, guideForRoles } from "./index";
import { flatten, searchText, type Article } from "./types";

/**
 * Checks the guides hold together.
 *
 * TypeScript cannot check that a `related` id names a real article or that a
 * screenshot file exists -- both are strings. Those are exactly the two
 * mistakes that produce a 404 or a broken image for a reader, so they are
 * checked here instead, and a build that would ship one fails.
 */

const PUBLIC_HELP = join(process.cwd(), "public", "help");

function everyArticle(): { guide: string; article: Article }[] {
  return GUIDES.flatMap((guide) =>
    flatten(guide).map((article) => ({ guide: guide.slug, article })),
  );
}

describe("guide structure", () => {
  it("has at least one published guide", () => {
    expect(GUIDES.length).toBeGreaterThan(0);
  });

  it("gives every guide a unique slug", () => {
    const slugs = GUIDES.map((g) => g.slug);
    expect(new Set(slugs).size).toBe(slugs.length);
  });

  it("gives every article a unique id within its guide", () => {
    for (const guide of GUIDES) {
      const ids = flatten(guide).map((a) => a.id);
      expect(new Set(ids).size, `duplicate article id in ${guide.slug}`).toBe(ids.length);
    }
  });

  it("uses url-safe ids, because these become addresses people bookmark", () => {
    for (const { guide, article } of everyArticle()) {
      expect(article.id, `${guide}/${article.id}`).toMatch(/^[a-z0-9]+(-[a-z0-9]+)*$/);
    }
  });

  it("records a sensible last-updated date on every guide", () => {
    for (const guide of GUIDES) {
      expect(guide.updated, guide.slug).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(Number.isNaN(Date.parse(guide.updated)), guide.slug).toBe(false);
    }
  });
});

describe("every article is usable on its own", () => {
  it("says what the reader will learn", () => {
    for (const { guide, article } of everyArticle()) {
      expect(article.learn.length, `${guide}/${article.id}`).toBeGreaterThan(0);
    }
  });

  it("has a summary, which is also its search result and page description", () => {
    for (const { guide, article } of everyArticle()) {
      expect(article.summary.length, `${guide}/${article.id}`).toBeGreaterThan(10);
    }
  });

  it("has a body", () => {
    for (const { guide, article } of everyArticle()) {
      expect(article.body.length, `${guide}/${article.id}`).toBeGreaterThan(0);
    }
  });

  it("gives an action-oriented title rather than a bare noun", () => {
    // A reader scanning a list of forty links needs to know what each one
    // lets them *do*, or answers. Allowed openings cover the how-to articles
    // and the explanatory ones; "why" is here because "Why you can see some
    // people and not others" is exactly the question its readers arrive with,
    // and renaming it to fit a narrower rule would have made it worse. "who"
    // joined it for the same reason and on the same evidence: a student opens
    // the help looking for "who can see my work", not for a paraphrase of it.
    const allowed = /^(how|what|who|why|understanding|welcome|common|getting)/i;
    for (const { guide, article } of everyArticle()) {
      expect(article.title, `${guide}/${article.id}`).toMatch(allowed);
    }
  });
});

describe("links between articles", () => {
  it("points every related link at an article that exists", () => {
    for (const guide of GUIDES) {
      const ids = new Set(flatten(guide).map((a) => a.id));
      for (const article of flatten(guide)) {
        for (const related of article.related ?? []) {
          expect(ids.has(related), `${guide.slug}/${article.id} links to missing "${related}"`).toBe(
            true,
          );
        }
      }
    }
  });

  it("never links an article to itself", () => {
    for (const { guide, article } of everyArticle()) {
      expect(article.related ?? [], `${guide}/${article.id}`).not.toContain(article.id);
    }
  });
});

describe("companion guides", () => {
  it("points every sibling link at a guide that exists", () => {
    for (const guide of GUIDES) {
      if (!guide.sibling) continue;
      expect(
        GUIDES.some((g) => g.slug === guide.sibling!.slug),
        `${guide.slug} points at missing guide "${guide.sibling.slug}"`,
      ).toBe(true);
    }
  });

  it("never points a guide at itself", () => {
    for (const guide of GUIDES) {
      if (guide.sibling) expect(guide.sibling.slug, guide.slug).not.toBe(guide.slug);
    }
  });

  it("pairs the two student guides both ways", () => {
    // They share the STUDENT role, so the sidebar can only offer one. The
    // pointer is how a reader reaches the other, and a one-way link would
    // strand whoever followed it.
    for (const [a, b] of [
      ["managed-student", "individual-student"],
      ["individual-student", "managed-student"],
    ]) {
      expect(GUIDES.find((g) => g.slug === a)?.sibling?.slug, a).toBe(b);
    }
  });
});

describe("screenshots", () => {
  function screenshotsOf(article: Article): string[] {
    const found: string[] = [];
    for (const block of article.body) {
      if (block.type === "screenshot") found.push(block.image.src);
      if (block.type === "steps") {
        for (const step of block.items) if (step.image) found.push(step.image.src);
      }
    }
    return found;
  }

  it("has a file on disk for every screenshot referenced", () => {
    const missing: string[] = [];
    for (const { guide, article } of everyArticle()) {
      for (const src of screenshotsOf(article)) {
        if (!existsSync(join(PUBLIC_HELP, src))) missing.push(`${guide}/${article.id} -> ${src}`);
      }
    }
    expect(missing, `missing screenshot files:\n${missing.join("\n")}`).toEqual([]);
  });

  it("gives every screenshot alternative text, for readers who cannot see it", () => {
    for (const { guide, article } of everyArticle()) {
      for (const block of article.body) {
        if (block.type === "screenshot") {
          expect(block.image.alt.length, `${guide}/${article.id}`).toBeGreaterThan(15);
        }
        if (block.type === "steps") {
          for (const step of block.items) {
            if (step.image) {
              expect(step.image.alt.length, `${guide}/${article.id}`).toBeGreaterThan(15);
            }
          }
        }
      }
    }
  });
});

describe("nothing private is published", () => {
  // These pages are public. A real address or password reaching them would be
  // a privacy breach, not a typo, so the content itself is checked.
  const EMAIL = /[\w.+-]+@[\w-]+\.[a-z]{2,}/i;

  it("contains no email address", () => {
    for (const { guide, article } of everyArticle()) {
      const text = searchText(article);
      expect(EMAIL.test(text), `${guide}/${article.id} contains an email address`).toBe(false);
    }
  });

  it("contains no test credentials", () => {
    const banned = ["password:", "ConsoleDrive", "superadmin/"];
    for (const { guide, article } of everyArticle()) {
      const text = searchText(article).toLowerCase();
      for (const needle of banned) {
        expect(text.includes(needle.toLowerCase()), `${guide}/${article.id} mentions ${needle}`).toBe(
          false,
        );
      }
    }
  });
});

describe("routing", () => {
  it("produces a path for every article", () => {
    const paths = allArticlePaths();
    const total = GUIDES.reduce((n, g) => n + flatten(g).length, 0);
    expect(paths.length).toBe(total);
  });

  it("offers the Super Admin guide to a Super Admin", () => {
    expect(guideForRoles(["SUPER_ADMIN"])?.slug).toBe("super-admin");
  });

  it("offers the most privileged guide when somebody holds several roles", () => {
    expect(guideForRoles(["TUTOR", "SUPER_ADMIN"])?.slug).toBe("super-admin");
  });

  it("offers the Managed Student guide to a student", () => {
    // Both student guides share the STUDENT role, so one mapping serves both.
    // See the comment on ROLE_TO_GUIDE for why it is the managed one.
    expect(guideForRoles(["STUDENT"])?.slug).toBe("managed-student");
  });

  it("offers nothing to a role whose guide is not written yet", () => {
    // Deliberate: a sidebar link to an empty guide is worse than no link.
    expect(guideForRoles(["ADMIN"])).toBeUndefined();
  });
});
