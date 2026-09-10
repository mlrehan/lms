import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

function tsxFiles(directory: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(directory)) {
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) out.push(...tsxFiles(path));
    else if (entry.endsWith(".tsx")) out.push(path);
  }
  return out;
}

/**
 * Strip comments before looking for an attribute.
 *
 * The first version of the test below did not, and a mutation proved it could
 * not fail: the explanatory comment *inside* the sign-in form's opening tag
 * contains the text `method="post"`, so deleting the real attribute left the
 * check green. A test that passes for the wrong reason is worse than no test,
 * because it is counted as coverage.
 */
function attributesOf(tag: string): string {
  return tag.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/\/\/[^\n]*/g, " ");
}

const DECLARES_POST = /\bmethod\s*=\s*"post"/;

/**
 * Every `<form>` must declare `method="post"`.
 *
 * React handles all of these submits, so the attribute looks redundant --
 * until a submit escapes React, which happens when a click lands before
 * hydration or when the JavaScript fails to load. A form with no method
 * defaults to GET, and the browser then serialises every field into the query
 * string.
 *
 * This was observed, not theorised: during a slow development rebuild a click
 * on the sign-in button produced
 * `GET /login?identifier=superadmin&password=...` -- the password in the
 * address bar, and from there in browser history, the server's access log and
 * the `Referer` of the next request.
 *
 * The rule applies to every form rather than only the ones carrying a
 * credential today, so a password field added to an existing form later
 * cannot quietly reintroduce it.
 */
describe("form submission cannot leak fields into a URL", () => {
  const files = tsxFiles(join(process.cwd(), "src"));

  it("finds the forms to check", () => {
    const withForms = files.filter((file) => readFileSync(file, "utf8").includes("<form"));
    expect(withForms.length).toBeGreaterThan(5);
  });

  it("declares method=post on every form", () => {
    const offenders: string[] = [];
    for (const file of files) {
      const source = readFileSync(file, "utf8");
      for (const match of source.matchAll(/<form\b[^>]*>/gs)) {
        if (!DECLARES_POST.test(attributesOf(match[0]))) {
          offenders.push(`${file.replace(process.cwd(), "")}: ${match[0].slice(0, 60)}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it("is not satisfied by the attribute appearing inside a comment", () => {
    // Guards the guard: the exact shape that defeated the first version.
    const commentOnly = '<form\n  /* `method="post"` matters here */\n  onSubmit={x}\n>';
    const real = '<form\n  /* explained above */\n  method="post"\n  onSubmit={x}\n>';
    expect(DECLARES_POST.test(attributesOf(commentOnly))).toBe(false);
    expect(DECLARES_POST.test(attributesOf(real))).toBe(true);
  });
});
