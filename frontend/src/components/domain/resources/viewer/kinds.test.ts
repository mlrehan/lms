import { describe, expect, it } from "vitest";
import {
  availableFilters,
  countFor,
  matchesFilter,
  typeLabel,
  viewerKind,
} from "./kinds";

/**
 * Which viewer opens which file.
 *
 * This decides what a student sees when they click a row, and it is decided
 * from metadata alone -- so getting it wrong means the right file opened in the
 * wrong reader, with no fetch to blame. The cases below are the ones that
 * actually bite: a browser sending `application/octet-stream`, a `.md` arriving
 * as `text/plain` because markdown is not in the upload allowlist, and the
 * Office MIME types, which are long enough that a typo in the pattern would
 * silently fall through to "other".
 */

describe("choosing a viewer", () => {
  it("believes the MIME type the server recorded", () => {
    expect(viewerKind({ mime_type: "application/pdf", resource_name: "x" })).toBe("pdf");
    expect(viewerKind({ mime_type: "image/webp", resource_name: "x" })).toBe("image");
    expect(viewerKind({ mime_type: "video/mp4", resource_name: "x" })).toBe("video");
    expect(viewerKind({ mime_type: "audio/mpeg", resource_name: "x" })).toBe("audio");
    expect(viewerKind({ mime_type: "text/csv", resource_name: "x" })).toBe("sheet");
  });

  it("recognises the Office types by their real, long names", () => {
    expect(
      viewerKind({
        mime_type:
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        resource_name: "marks",
      }),
    ).toBe("sheet");
    expect(
      viewerKind({
        mime_type:
          "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        resource_name: "notes",
      }),
    ).toBe("document");
    expect(viewerKind({ mime_type: "application/msword", resource_name: "old.doc" })).toBe(
      "document",
    );
  });

  it("falls back to the extension when the browser said nothing useful", () => {
    // Browsers send this for perfectly ordinary files; refusing to classify
    // them would send every such upload to the "cannot display" panel.
    const octet = "application/octet-stream";
    expect(viewerKind({ mime_type: octet, resource_name: "handout.pdf" })).toBe("pdf");
    expect(viewerKind({ mime_type: null, resource_name: "slide.PNG" })).toBe("image");
    expect(viewerKind({ mime_type: "", resource_name: "data.xlsx" })).toBe("sheet");
  });

  it("reads a .md as markdown even though it arrives as plain text", () => {
    // `text/markdown` is not in the upload allowlist, so the extension is the
    // only thing that can tell these two apart.
    expect(viewerKind({ mime_type: "text/plain", resource_name: "README.md" })).toBe("markdown");
    expect(viewerKind({ mime_type: "text/plain", resource_name: "notes.txt" })).toBe("text");
  });

  it("gives up honestly on something it cannot show", () => {
    expect(viewerKind({ mime_type: "application/zip", resource_name: "course.zip" })).toBe("other");
    expect(viewerKind({ mime_type: null, resource_name: "noextension" })).toBe("other");
  });

  it("labels the toolbar from the extension, and from the type when there is none", () => {
    expect(typeLabel({ mime_type: "application/pdf", resource_name: "a.pdf" })).toBe("PDF");
    expect(typeLabel({ mime_type: "image/png", resource_name: "diagram" })).toBe("PNG");
    expect(typeLabel({ mime_type: null, resource_name: "thing" })).toBe("File");
  });
});

describe("the type filter", () => {
  const files = [
    { mime_type: "application/pdf", resource_name: "a.pdf" },
    { mime_type: "application/pdf", resource_name: "b.pdf" },
    { mime_type: "text/csv", resource_name: "c.csv" },
    { mime_type: "text/plain", resource_name: "d.txt" },
    { mime_type: "application/zip", resource_name: "e.zip" },
  ];

  it("offers only the groups this person actually has", () => {
    // A student with three PDFs should not be handed five empty buttons.
    expect(availableFilters(files)).toEqual(["all", "documents", "pdf", "sheet"]);
    expect(availableFilters([])).toEqual(["all"]);
  });

  it("counts what each group would show, including the unshowable", () => {
    expect(countFor(files, "all")).toBe(5);
    expect(countFor(files, "pdf")).toBe(2);
    expect(countFor(files, "sheet")).toBe(1);
    // "Documents" is prose: text and markdown and Word, but not PDF, which
    // has its own entry -- otherwise the counts would not add up.
    expect(countFor(files, "documents")).toBe(1);
  });

  it("keeps a file the viewer cannot open in the list", () => {
    // It is still something that was shared with them, and the viewer says so
    // with a download panel. Hiding it would be the system losing a file.
    const zip = files[4]!;
    expect(matchesFilter(zip, "all")).toBe(true);
    expect(matchesFilter(zip, "documents")).toBe(false);
  });
});
