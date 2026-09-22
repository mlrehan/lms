import type { Metadata, Viewport } from "next";
import { Inter, Inter_Tight, JetBrains_Mono } from "next/font/google";
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
 */
const sans = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});
const display = Inter_Tight({
  variable: "--font-inter-tight",
  subsets: ["latin"],
  weight: ["500", "600", "700", "800"],
  display: "swap",
});
const mono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "LMS Console", template: "%s · LMS Console" },
  description: "Administration console for the learning management system.",
  // An administration console has nothing to gain from being indexed, and a
  // crawler following a link into it only ever reaches the sign-in screen.
  robots: { index: false, follow: false },
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
