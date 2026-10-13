/**
 * Reading `.xlsx` and `.docx` in the browser, from the bytes we already have.
 *
 * **Why not a library.** The obvious choices are SheetJS and mammoth. The npm
 * build of SheetJS is a version behind its own security fixes, and mammoth
 * hands back an HTML *string* -- which would mean `innerHTML` on a file a
 * tenant uploaded, i.e. the one place this codebase has repeatedly refused to
 * put model or user content. Both are also an order of magnitude larger than
 * what is needed to show somebody their spreadsheet.
 *
 * Both formats are ZIPs of XML, so this reads them with `fflate` (8 KB) and
 * the browser's own `DOMParser`, and returns **data**. The React components
 * build elements from that data; no HTML is ever assembled from a string, so
 * there is nothing for a crafted document to inject into.
 *
 * **Deliberately partial, and it says so.** This covers what a lecture
 * handout or a mark sheet actually contains -- paragraphs, headings, bold and
 * italic runs, lists, tables, cells with shared strings. It does not attempt
 * images, charts, merged-cell layout, or formatting beyond emphasis. When a
 * file cannot be read, the caller shows the download panel rather than a bad
 * rendering, which is the honest failure.
 */

import { unzipSync, strFromU8 } from "fflate";

export interface SheetGrid {
  name: string;
  rows: string[][];
}

export interface DocRun {
  text: string;
  bold?: boolean;
  italic?: boolean;
}

export type DocBlock =
  | { kind: "paragraph"; runs: DocRun[]; heading?: number; listed?: boolean }
  | { kind: "table"; rows: DocRun[][][] };

const XML = "application/xml";

function parse(xml: string): Document {
  const doc = new DOMParser().parseFromString(xml, XML);
  if (doc.querySelector("parsererror")) throw new Error("The file's contents are not readable.");
  return doc;
}

/** `local-name()`, without XPath: OOXML namespaces every element. */
function kids(node: Element, name: string): Element[] {
  return Array.from(node.children).filter((child) => child.localName === name);
}

function firstChild(node: Element, name: string): Element | null {
  return kids(node, name)[0] ?? null;
}

function entries(bytes: Uint8Array): Record<string, Uint8Array> {
  try {
    return unzipSync(bytes);
  } catch {
    throw new Error("The file is not a readable Office document.");
  }
}

function text(files: Record<string, Uint8Array>, path: string): string | null {
  const found = files[path];
  return found ? strFromU8(found) : null;
}

/* -------------------------------------------------------------------------- */
/* Spreadsheets                                                                */
/* -------------------------------------------------------------------------- */

/** `"BC7"` -> column 54. Letters are base-26 with no zero, hence the `- 1`. */
function columnOf(reference: string): number {
  let column = 0;
  for (const character of reference) {
    const code = character.charCodeAt(0);
    if (code < 65 || code > 90) break;
    column = column * 26 + (code - 64);
  }
  return Math.max(0, column - 1);
}

function sharedStrings(files: Record<string, Uint8Array>): string[] {
  const xml = text(files, "xl/sharedStrings.xml");
  if (!xml) return [];
  return kids(parse(xml).documentElement, "si").map((si) =>
    // A single string may be split across runs when parts of it are styled
    // differently; joining the `t` nodes is what puts the cell back together.
    Array.from(si.getElementsByTagName("*"))
      .filter((node) => node.localName === "t")
      .map((node) => node.textContent ?? "")
      .join(""),
  );
}

export function readSpreadsheet(bytes: Uint8Array, limitRows = 2000): SheetGrid[] {
  const files = entries(bytes);
  const strings = sharedStrings(files);

  const workbookXml = text(files, "xl/workbook.xml");
  const names: string[] = workbookXml
    ? kids(firstChild(parse(workbookXml).documentElement, "sheets") ?? parse("<a/>").documentElement, "sheet").map(
        (sheet, index) => sheet.getAttribute("name") ?? `Sheet ${index + 1}`,
      )
    : [];

  // Read the worksheet parts in their own order rather than following the
  // relationship ids: the names above are in workbook order, and a mismatch
  // would label the wrong grid, which is worse than no label.
  const paths = Object.keys(files)
    .filter((path) => /^xl\/worksheets\/sheet\d+\.xml$/.test(path))
    .sort((a, b) => {
      const n = (p: string) => Number(p.match(/sheet(\d+)\.xml$/)?.[1] ?? 0);
      return n(a) - n(b);
    });
  if (paths.length === 0) throw new Error("The workbook has no sheets.");

  return paths.map((path, index) => {
    const sheet = parse(strFromU8(files[path]!)).documentElement;
    const data = firstChild(sheet, "sheetData");
    const rows: string[][] = [];

    for (const row of data ? kids(data, "row") : []) {
      if (rows.length >= limitRows) break;
      const cells: string[] = [];
      for (const cell of kids(row, "c")) {
        const at = columnOf(cell.getAttribute("r") ?? "");
        const type = cell.getAttribute("t");
        let value = "";
        if (type === "s") {
          const index = Number(firstChild(cell, "v")?.textContent ?? "");
          value = strings[index] ?? "";
        } else if (type === "inlineStr") {
          value = firstChild(cell, "is")?.textContent ?? "";
        } else {
          value = firstChild(cell, "v")?.textContent ?? "";
        }
        // Cells are addressed, not sequential: a row with A1 and D1 has no
        // B or C element at all, and appending would shift the columns left.
        while (cells.length < at) cells.push("");
        cells[at] = value;
      }
      rows.push(cells);
    }
    return { name: names[index] ?? `Sheet ${index + 1}`, rows };
  });
}

/** `.csv` and `.tsv`, including quoted fields with embedded separators. */
export function readDelimited(raw: string, separator?: string): SheetGrid {
  const text = raw.replace(/^﻿/, "");
  const sep = separator ?? (text.slice(0, 2000).includes("\t") ? "\t" : ",");
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;

  for (let i = 0; i < text.length; i += 1) {
    const character = text[i];
    if (quoted) {
      if (character === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i += 1;
        } else {
          quoted = false;
        }
      } else {
        field += character;
      }
      continue;
    }
    if (character === '"') quoted = true;
    else if (character === sep) {
      row.push(field);
      field = "";
    } else if (character === "\n") {
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else if (character !== "\r") {
      field += character;
    }
  }
  if (field !== "" || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  return { name: "Sheet", rows };
}

/* -------------------------------------------------------------------------- */
/* Word documents                                                              */
/* -------------------------------------------------------------------------- */

function runsOf(parent: Element): DocRun[] {
  const runs: DocRun[] = [];
  for (const run of kids(parent, "r")) {
    const properties = firstChild(run, "rPr");
    const bold = properties ? firstChild(properties, "b") !== null : false;
    const italic = properties ? firstChild(properties, "i") !== null : false;
    let value = "";
    for (const node of Array.from(run.children)) {
      if (node.localName === "t") value += node.textContent ?? "";
      else if (node.localName === "tab") value += "\t";
      else if (node.localName === "br") value += "\n";
    }
    if (value) runs.push({ text: value, bold: bold || undefined, italic: italic || undefined });
  }
  return runs;
}

function paragraph(node: Element): DocBlock {
  const properties = firstChild(node, "pPr");
  const styleName = properties
    ? (firstChild(properties, "pStyle")?.getAttribute("w:val") ??
       firstChild(properties, "pStyle")?.getAttribute("val") ??
       "")
    : "";
  const headingLevel = /^heading\s*([1-6])$/i.exec(styleName.replace(/[-_]/g, " "));
  return {
    kind: "paragraph",
    runs: runsOf(node),
    heading: headingLevel ? Number(headingLevel[1]) : undefined,
    listed: properties ? firstChild(properties, "numPr") !== null : false,
  };
}

export function readDocument(bytes: Uint8Array, limitBlocks = 3000): DocBlock[] {
  const files = entries(bytes);
  const xml = text(files, "word/document.xml");
  if (!xml) throw new Error("The file is not a readable Word document.");

  const body = firstChild(parse(xml).documentElement, "body");
  if (!body) throw new Error("The document has no body.");

  const blocks: DocBlock[] = [];
  for (const node of Array.from(body.children)) {
    if (blocks.length >= limitBlocks) break;
    if (node.localName === "p") {
      blocks.push(paragraph(node));
    } else if (node.localName === "tbl") {
      const rows = kids(node, "tr").map((tr) =>
        kids(tr, "tc").map((tc) => kids(tc, "p").flatMap(runsOf)),
      );
      if (rows.length > 0) blocks.push({ kind: "table", rows });
    }
  }
  if (blocks.length === 0) throw new Error("The document appears to be empty.");
  return blocks;
}
