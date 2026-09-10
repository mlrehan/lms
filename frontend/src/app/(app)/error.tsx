"use client";

import { useEffect } from "react";
import { Button } from "@/components/ui/button";

/**
 * The last line of defence for a rendering error inside the signed-in shell.
 *
 * The message is shown, the digest is not decorated with anything else: an
 * error thrown while rendering can carry internal detail, and this console
 * has no way to tell a safe message from an unsafe one at this point.
 */
export default function AppError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Left in the browser console for whoever is debugging; never sent
    // anywhere, and never rendered as markup.
    console.error(error);
  }, [error]);

  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 text-center">
      <h1 className="text-lg font-semibold">This screen could not be rendered</h1>
      <p className="max-w-md text-sm text-muted-foreground">
        Something went wrong drawing this page. Trying again is safe; nothing was submitted.
      </p>
      {error.digest ? (
        <p className="font-mono text-xs text-muted-foreground">Reference {error.digest}</p>
      ) : null}
      <Button onClick={reset}>Try again</Button>
    </div>
  );
}
