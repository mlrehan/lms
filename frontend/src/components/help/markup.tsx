import { Fragment, type ReactNode } from "react";

/**
 * The only formatting an article author needs: **bold**.
 *
 * Deliberately not a markdown library. Help text uses bold for exactly one
 * thing -- the words a reader has to find on screen -- and a parser that can
 * only do that cannot accidentally render a link, an image or raw HTML from
 * content. There is no sanitiser to get wrong because nothing else is
 * possible.
 */
export function Markup({ text }: { text: string }): ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return (
    <>
      {parts.map((part, index) => {
        if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
          return (
            <strong key={index} className="font-semibold text-foreground">
              {part.slice(2, -2)}
            </strong>
          );
        }
        return <Fragment key={index}>{part}</Fragment>;
      })}
    </>
  );
}

/** The same, with the markers removed, for places that take a plain string. */
export function plain(text: string): string {
  return text.replace(/\*\*/g, "");
}
