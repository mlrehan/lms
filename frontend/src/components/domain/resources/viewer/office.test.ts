import { describe, expect, it } from "vitest";
import { zipSync, strToU8 } from "fflate";
import { readDelimited, readDocument, readSpreadsheet } from "./office";

/**
 * Reading `.xlsx`, `.docx` and `.csv` without a library.
 *
 * The fixtures are **built here as real ZIPs of real OOXML**, not recorded from
 * a sample file: a hand-written stub would let a parser pass that only works on
 * the one document somebody happened to save. The cases are the ones that
 * actually break naive parsers --
 *
 *  * a spreadsheet row with a gap (`A1` and `D1`, no `B` or `C` element at
 *    all), which shifts every later column left if cells are appended in order;
 *  * a shared string split across styled runs, which comes back as two `t`
 *    nodes and must be rejoined;
 *  * a CSV field containing the separator inside quotes;
 *  * a Word paragraph whose heading level is in `w:pStyle`, and runs whose
 *    emphasis is in `w:rPr`.
 */

const NS =
  'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"';
const WNS =
  'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"';

function workbook(sheetXml: string, sharedXml?: string): Uint8Array {
  const files: Record<string, Uint8Array> = {
    "xl/workbook.xml": strToU8(
      `<?xml version="1.0"?><workbook ${NS}><sheets><sheet name="Marks" sheetId="1"/></sheets></workbook>`,
    ),
    "xl/worksheets/sheet1.xml": strToU8(
      `<?xml version="1.0"?><worksheet ${NS}>${sheetXml}</worksheet>`,
    ),
  };
  if (sharedXml) {
    files["xl/sharedStrings.xml"] = strToU8(
      `<?xml version="1.0"?><sst ${NS}>${sharedXml}</sst>`,
    );
  }
  return zipSync(files);
}

describe("spreadsheets", () => {
  it("keeps a gapped row in its real columns", () => {
    const bytes = workbook(
      '<sheetData><row r="1">' +
        '<c r="A1"><v>1</v></c>' +
        '<c r="D1"><v>4</v></c>' +
        "</row></sheetData>",
    );
    const [sheet] = readSpreadsheet(bytes);
    // Appending in document order would give ["1","4"] and put 4 under B.
    expect(sheet!.rows[0]).toEqual(["1", "", "", "4"]);
  });

  it("addresses columns past Z", () => {
    const bytes = workbook('<sheetData><row r="1"><c r="AB1"><v>x</v></c></row></sheetData>');
    const [sheet] = readSpreadsheet(bytes);
    expect(sheet!.rows[0]!.length).toBe(28); // A..AB
    expect(sheet!.rows[0]![27]).toBe("x");
  });

  it("rejoins a shared string that was split by styling", () => {
    const bytes = workbook(
      '<sheetData><row r="1"><c r="A1" t="s"><v>0</v></c></row></sheetData>',
      "<si><r><t>Pass</t></r><r><t> mark</t></r></si>",
    );
    const [sheet] = readSpreadsheet(bytes);
    expect(sheet!.rows[0]![0]).toBe("Pass mark");
  });

  it("names the sheet from the workbook", () => {
    const bytes = workbook('<sheetData><row r="1"><c r="A1"><v>1</v></c></row></sheetData>');
    expect(readSpreadsheet(bytes)[0]!.name).toBe("Marks");
  });

  it("refuses something that is not a workbook, rather than rendering nothing", () => {
    expect(() => readSpreadsheet(strToU8("not a zip"))).toThrow();
    expect(() => readSpreadsheet(zipSync({ "a.txt": strToU8("hello") }))).toThrow();
  });
});

describe("delimited text", () => {
  it("keeps a separator that is inside quotes", () => {
    const grid = readDelimited('name,note\n"Patel, R",ok\n');
    expect(grid.rows).toEqual([
      ["name", "note"],
      ["Patel, R", "ok"],
    ]);
  });

  it("unescapes a doubled quote", () => {
    expect(readDelimited('a,"he said ""no"""\n').rows[1 - 1]).toEqual(["a", 'he said "no"']);
  });

  it("picks the tab when the file is tab-separated", () => {
    expect(readDelimited("a\tb\nc\td\n").rows).toEqual([
      ["a", "b"],
      ["c", "d"],
    ]);
  });

  it("drops a byte-order mark instead of hiding it in the first heading", () => {
    expect(readDelimited("﻿name,mark\n").rows[0]).toEqual(["name", "mark"]);
  });

  it("keeps a last line with no trailing newline", () => {
    expect(readDelimited("a,b\nc,d").rows.length).toBe(2);
  });
});

function document(bodyXml: string): Uint8Array {
  return zipSync({
    "word/document.xml": strToU8(
      `<?xml version="1.0"?><w:document ${WNS}><w:body>${bodyXml}</w:body></w:document>`,
    ),
  });
}

describe("word documents", () => {
  it("reads a heading, its level, and emphasis on runs", () => {
    const bytes = document(
      '<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>Week 1</w:t></w:r></w:p>' +
        '<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Bold</w:t></w:r>' +
        "<w:r><w:rPr><w:i/></w:rPr><w:t> and italic</w:t></w:r></w:p>",
    );
    const blocks = readDocument(bytes);
    expect(blocks[0]).toMatchObject({ kind: "paragraph", heading: 2 });
    expect(blocks[1]).toMatchObject({
      kind: "paragraph",
      runs: [
        { text: "Bold", bold: true },
        { text: " and italic", italic: true },
      ],
    });
  });

  it("marks a numbered or bulleted paragraph", () => {
    const bytes = document(
      '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/></w:numPr></w:pPr><w:r><w:t>One</w:t></w:r></w:p>',
    );
    expect(readDocument(bytes)[0]).toMatchObject({ listed: true });
  });

  it("reads a table as rows of cells", () => {
    const bytes = document(
      "<w:tbl><w:tr>" +
        "<w:tc><w:p><w:r><w:t>Name</w:t></w:r></w:p></w:tc>" +
        "<w:tc><w:p><w:r><w:t>Mark</w:t></w:r></w:p></w:tc>" +
        "</w:tr></w:tbl>",
    );
    const block = readDocument(bytes)[0];
    expect(block).toMatchObject({ kind: "table" });
    if (block?.kind !== "table") throw new Error("expected a table");
    expect(block.rows[0]!.length).toBe(2);
  });

  it("refuses a file that is not a Word document", () => {
    // The old binary `.doc` is not a ZIP at all, and an empty one has nothing
    // to show -- both are better reported than rendered as a blank page.
    expect(() => readDocument(strToU8("\xD0\xCF\x11\xE0"))).toThrow();
    expect(() => readDocument(document(""))).toThrow();
  });
});
