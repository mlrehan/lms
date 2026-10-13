import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import { BookOpen } from "lucide-react";

/**
 * The public Help Center shell.
 *
 * **These pages are outside the `(app)` route group on purpose.** That group's
 * layout holds the sign-in guard, so anything inside it redirects a signed-out
 * visitor to the login screen. The guide has to open for somebody with no
 * account at all -- a parent sent a link, a new tutor reading before their
 * first day -- so it lives here, where no guard runs and no request to the API
 * is made.
 *
 * Nothing on these pages reads application data. They are built from the
 * content files at build time, which is also why they cannot leak anything:
 * there is no query to run and no session to read.
 */
export const metadata: Metadata = {
  title: { default: "Help Center", template: "%s · LMS Help Center" },
  description:
    "Step-by-step guides for using the learning management system, written for complete beginners.",
  // The console is noindex; these pages are meant to be shared, but the
  // screenshots show a real institution's console, so they are kept out of
  // search results while remaining open to anybody holding the link.
  robots: { index: false, follow: true },
  openGraph: {
    type: "website",
    siteName: "LMS Help Center",
  },
};

export default function HelpLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-dvh bg-background">
      <header className="border-b border-border print:hidden">
        <div className="mx-auto flex max-w-[82rem] items-center gap-3 px-4 py-3 sm:px-6">
          <Link
            href="/help"
            className="flex items-center gap-2 font-display text-sm font-semibold tracking-tight text-foreground"
          >
            <span className="flex size-6 items-center justify-center rounded-md bg-primary text-primary-foreground">
              <BookOpen className="size-3.5" aria-hidden />
            </span>
            LMS Help Center
          </Link>
          <span className="ml-auto text-xs text-muted-foreground">
            <Link href="/login" className="hover:text-foreground hover:underline">
              Sign in to the LMS
            </Link>
          </span>
        </div>
      </header>

      {children}

      <footer className="mt-16 border-t border-border py-8 print:hidden">
        <div className="mx-auto max-w-[82rem] px-4 text-xs text-muted-foreground sm:px-6">
          <p>
            These guides describe the learning management system as it works today. If a screen
            looks different from a picture here, trust the screen and tell your administrator.
          </p>
        </div>
      </footer>
    </div>
  );
}
