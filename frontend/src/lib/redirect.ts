/**
 * Where a sign-in is allowed to send someone next.
 *
 * `?next=` is attacker-controllable: a link that signs a person in and then
 * bounces them to another site is a working phishing step, and one that
 * bounces to `javascript:` is worse. Only a path inside this console is
 * accepted -- it must begin with a single `/` and not `//`, which a browser
 * reads as a protocol-relative *absolute* URL and would follow off-site.
 *
 * A backslash is refused too: some browsers normalise `/\evil.test` to
 * `//evil.test`, which is the same escape wearing a different hat.
 */
export function safeRedirect(value: string | null | undefined): string {
  if (!value) return "/";
  const trimmed = value.trim();
  if (!trimmed.startsWith("/")) return "/";
  if (trimmed.startsWith("//")) return "/";
  if (trimmed.startsWith("/\\")) return "/";
  // A control character can truncate a header or a URL in some parsers.
  if (/[\u0000-\u001f\u007f]/.test(trimmed)) return "/";
  return trimmed;
}
