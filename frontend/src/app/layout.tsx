import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import type { ReactNode } from "react";
import { Providers } from "./providers";
import "./globals.css";

/*
 * Three faces, three jobs.
 *
 * Inter carries the UI: it has the widest weight range and the best tabular
 * figures of the open grotesques, and a console is mostly figures. Inter
 * Tight is reserved for headings and hero numerals, where its narrower
 * sidebearings let negative tracking read as deliberate rather than cramped.
 * JetBrains Mono is for identifiers -- batch codes, ids, keys -- because its
 * slashed zero and disambiguated l/1/I are the whole point of setting a
 * reference in mono in the first place.
 *
 * Bundled rather than fetched from Google at build time (`next/font/google`).
 * The production Docker build failed on Inter Tight with "next/font/google
 * queries have exactly one entry": what Google serves to that server is not
 * what it serves elsewhere, and a build that depends on a third party's
 * response to a particular machine is not reproducible. These are the same
 * latin variable files Google serves, under the SIL Open Font License (see
 * fonts/OFL.md), so the rendering is unchanged and the build needs no network.
 */
const sans = localFont({
  src: "./fonts/inter-latin.woff2",
  variable: "--font-inter",
  weight: "100 900",
  display: "swap",
});
const display = localFont({
  src: "./fonts/inter-tight-latin.woff2",
  variable: "--font-inter-tight",
  weight: "100 900",
  display: "swap",
});
const mono = localFont({
  src: "./fonts/jetbrains-mono-latin.woff2",
  variable: "--font-jetbrains-mono",
  weight: "100 800",
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "LMS Console", template: "%s · LMS Console" },
  description: "Administration console for the learning management system.",
  // An administration console has nothing to gain from being indexed, and a
  // crawler following a link into it only ever reaches the sign-in screen.
  robots: { index: false, follow: false },
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "any" },
      { url: "/icon.svg", type: "image/svg+xml" },
    ],
    apple: [
      { url: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" },
    ],
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f8fafc" },
    { media: "(prefers-color-scheme: dark)", color: "#020617" },
  ],
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    // `suppressHydrationWarning` is required by next-themes: it writes the
    // theme class onto <html> before React hydrates, so the server's markup
    // and the client's first pass legitimately differ on that one attribute.
    // The font variables go on <html>, not <body>: `:root` rules and the
    // `@theme` stacks both resolve against the documentElement, and a
    // variable defined only on <body> is invisible to them.
    <html
      lang="en"
      suppressHydrationWarning
      className={`${sans.variable} ${display.variable} ${mono.variable}`}
    >
      <body className="antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
