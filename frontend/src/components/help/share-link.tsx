"use client";

import { useState } from "react";
import { Check, Link2 } from "lucide-react";

/**
 * Copies the page's public address.
 *
 * The URL is read from the browser rather than built from a configured public
 * origin, because the console has no such setting -- and whatever address the
 * reader reached this page on is, by definition, an address that works for
 * them to send to somebody else.
 */
export function ShareLink({ path }: { path: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    const url = `${window.location.origin}${path}`;
    try {
      await navigator.clipboard.writeText(url);
    } catch {
      // Clipboard access can be refused (an insecure origin, or a browser
      // setting). Showing the address lets the reader copy it by hand rather
      // than leaving them with a button that silently does nothing.
      window.prompt("Copy this link:", url);
      return;
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  }

  return (
    <button
      type="button"
      onClick={() => void copy()}
      className="flex items-center gap-1.5 rounded-md border border-border px-2 py-1 text-xs text-muted-foreground transition-colors hover:text-foreground print:hidden"
    >
      {copied ? (
        <>
          <Check className="size-3" aria-hidden />
          Link copied
        </>
      ) : (
        <>
          <Link2 className="size-3" aria-hidden />
          Copy link
        </>
      )}
    </button>
  );
}
