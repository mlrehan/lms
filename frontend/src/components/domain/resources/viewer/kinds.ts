/**
 * What kind of thing is this, and therefore which viewer opens it.
 *
 * **Decided from the MIME type first and the extension only as a fallback.**
 * The server records the type it accepted at upload against an allowlist, so
 * it is the better evidence; but browsers send `application/octet-stream` for
 * perfectly ordinary files, and `text/plain` for both a `.txt` and a `.md`,
 * which are read differently. So the extension breaks those ties and nothing
 * else.
 *
 * Classification is **metadata only** -- no byte of the file is fetched to
 * decide this. That is what lets the list render sixty rows, with icons and a
 * working type filter, having downloaded nothing.
 */

export type ViewerKind =
  | "pdf"
  | "image"
  | "video"
  | "audio"
  | "markdown"
  | "text"
  | "sheet"
  | "document"
  | "other";

/** The groups offered above the list. Only types this LMS actually accepts. */
export type TypeFilter = "all" | "documents" | "pdf" | "sheet" | "image" | "video" | "audio";

export interface FileLike {
  mime_type?: string | null;
  resource_name?: string | null;
  name?: string | null;
}

const BY_EXTENSION: Record<string, ViewerKind> = {
  pdf: "pdf",
  md: "markdown",
  markdown: "markdown",
  txt: "text",
  log: "text",
  csv: "sheet",
  tsv: "sheet",
  xls: "sheet",
  xlsx: "sheet",
  doc: "document",
  docx: "document",
  jpg: "image",
  jpeg: "image",
  png: "image",
  gif: "image",
  webp: "image",
  svg: "image",
  mp4: "video",
  webm: "video",
  mov: "video",
  mp3: "audio",
  wav: "audio",
  ogg: "audio",
  m4a: "audio",
};

const BY_MIME: Array<[RegExp, ViewerKind]> = [
  [/^application\/pdf$/, "pdf"],
  [/^image\//, "image"],
  [/^video\//, "video"],
  [/^audio\//, "audio"],
  [/^text\/markdown$/, "markdown"],
  [/^text\/csv$/, "sheet"],
  [/^text\/tab-separated-values$/, "sheet"],
  [/spreadsheetml|ms-excel/, "sheet"],
  [/wordprocessingml|msword/, "document"],
  [/^text\//, "text"],
];

export function fileName(file: FileLike): string {
  return file.resource_name ?? file.name ?? "Untitled";
}

export function extensionOf(file: FileLike): string {
  const name = fileName(file);
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot + 1).toLowerCase() : "";
}

export function viewerKind(file: FileLike): ViewerKind {
  const extension = extensionOf(file);
  const mime = (file.mime_type ?? "").toLowerCase();

  // `.md` arrives as `text/plain`, because `text/markdown` is not in the
  // upload allowlist. Reading a markdown file as plain text is not wrong, but
  // it is worse, and the extension is the only thing that can tell them apart.
  if (extension === "md" || extension === "markdown") return "markdown";

  for (const [pattern, kind] of BY_MIME) {
    if (pattern.test(mime)) return kind;
  }
  return BY_EXTENSION[extension] ?? "other";
}

/** A short label for the toolbar: "PDF", "XLSX", "MP4". */
export function typeLabel(file: FileLike): string {
  const extension = extensionOf(file);
  if (extension) return extension.toUpperCase();
  const mime = file.mime_type ?? "";
  return mime ? (mime.split("/")[1] ?? mime).toUpperCase() : "File";
}

const FILTER_KINDS: Record<Exclude<TypeFilter, "all">, readonly ViewerKind[]> = {
  // "Documents" is the readable-prose group: Word files and plain text and
  // markdown. PDF has its own entry because it is the one people look for by
  // name, and putting it in both would make the counts not add up.
  documents: ["document", "text", "markdown"],
  pdf: ["pdf"],
  sheet: ["sheet"],
  image: ["image"],
  video: ["video"],
  audio: ["audio"],
};

export function matchesFilter(file: FileLike, filter: TypeFilter): boolean {
  if (filter === "all") return true;
  return FILTER_KINDS[filter].includes(viewerKind(file));
}

/**
 * Which filters to offer.
 *
 * Driven by what is actually in this person's list, so a student with three
 * PDFs is not given five empty buttons to press. "All" is always offered;
 * everything else earns its place.
 */
export function availableFilters(files: readonly FileLike[]): TypeFilter[] {
  const present = new Set(files.map(viewerKind));
  const offered: TypeFilter[] = ["all"];
  for (const filter of ["documents", "pdf", "sheet", "image", "video", "audio"] as const) {
    if (FILTER_KINDS[filter].some((kind) => present.has(kind))) offered.push(filter);
  }
  return offered;
}

export const FILTER_LABELS: Record<TypeFilter, string> = {
  all: "All",
  documents: "Documents",
  pdf: "PDF",
  sheet: "Spreadsheets",
  image: "Images",
  video: "Video",
  audio: "Audio",
};

export function countFor(files: readonly FileLike[], filter: TypeFilter): number {
  return files.filter((file) => matchesFilter(file, filter)).length;
}
