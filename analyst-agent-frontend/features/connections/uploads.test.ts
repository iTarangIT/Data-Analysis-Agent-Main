import { describe, expect, it } from "vitest";

import type { SourceTable } from "@/lib/api/types";

import {
  MAX_UPLOAD_BYTES,
  MAX_UPLOAD_FILES,
  UploadedFiles,
  filesOf,
  formatBytes,
  pick,
  stemOf,
  uploadProblem,
} from "./uploads";

const sheet = (name: string, size = 1024) => ({ name, size });

function table(name: string, files: string[]): SourceTable {
  return { name, files, selected: false, definition: null, stats: null };
}

describe("uploadProblem", () => {
  it.each(["sales.csv", "stock.TSV", "July.xlsx", "ledger.parquet", "statement.PDF"])(
    "accepts %s",
    (name) => {
      expect(uploadProblem(sheet(name))).toBeNull();
    },
  );

  it.each(["report.docx", "old.xls", "archive.csv.zip", "noextension"])("refuses %s by name", (name) => {
    expect(uploadProblem(sheet(name))).toBe(
      `${name} is not a CSV, TSV, Excel, Parquet or PDF file.`,
    );
  });

  it("refuses a file over the size limit, and not one exactly at it", () => {
    expect(uploadProblem(sheet("big.csv", MAX_UPLOAD_BYTES))).toBeNull();
    expect(uploadProblem(sheet("big.csv", MAX_UPLOAD_BYTES + 1))).toBe("big.csv is over the 25 MB limit.");
  });
});

describe("pick", () => {
  it("adds new files after the ones already chosen, in order", () => {
    const { files, problems } = pick([sheet("a.csv")], [sheet("b.csv"), sheet("c.xlsx")]);

    expect(files.map((f) => f.name)).toEqual(["a.csv", "b.csv", "c.xlsx"]);
    expect(problems).toEqual([]);
  });

  it("keeps the good files and says why the others were left out", () => {
    const { files, problems } = pick([], [sheet("a.csv"), sheet("notes.docx"), sheet("b.csv")]);

    expect(files.map((f) => f.name)).toEqual(["a.csv", "b.csv"]);
    expect(problems).toEqual(["notes.docx is not a CSV, TSV, Excel, Parquet or PDF file."]);
  });

  it("refuses a name already chosen, including twice in one drop", () => {
    const { files, problems } = pick([sheet("a.csv")], [sheet("a.csv"), sheet("b.csv"), sheet("b.csv")]);

    expect(files.map((f) => f.name)).toEqual(["a.csv", "b.csv"]);
    expect(problems).toEqual(["a.csv is already chosen.", "b.csv is already chosen."]);
  });

  it("refuses a name the dataset already holds, because files are removed by name", () => {
    const { files, problems } = pick([], [sheet("July.xlsx")], ["July.xlsx"]);

    expect(files).toEqual([]);
    expect(problems).toEqual(["July.xlsx is already in this dataset."]);
  });

  it("stops at the per-upload limit rather than dropping earlier choices", () => {
    const current = Array.from({ length: MAX_UPLOAD_FILES - 1 }, (_, i) => sheet(`part${i}.csv`));

    const { files, problems } = pick(current, [sheet("last.csv"), sheet("extra.csv")]);

    expect(files).toHaveLength(MAX_UPLOAD_FILES);
    expect(files.at(-1)?.name).toBe("last.csv");
    expect(problems).toEqual([`extra.csv was left out. Upload at most ${MAX_UPLOAD_FILES} files at a time.`]);
  });
});

describe("UploadedFiles", () => {
  const file = (name: string) => new File(["region,units\nWest,10\n"], name);

  it("accepts one to the limit of supported files", () => {
    expect(UploadedFiles.safeParse([file("a.csv"), file("b.xlsx")]).success).toBe(true);
  });

  it("refuses an empty upload, too many files, a string and an unsupported file", () => {
    const tooMany = Array.from({ length: MAX_UPLOAD_FILES + 1 }, (_, i) => file(`p${i}.csv`));

    expect(UploadedFiles.safeParse([]).error?.issues[0]?.message).toBe("Choose at least one file.");
    expect(UploadedFiles.safeParse(tooMany).error?.issues[0]?.message).toBe(
      `Upload at most ${MAX_UPLOAD_FILES} files at a time.`,
    );
    expect(UploadedFiles.safeParse(["a.csv"]).success).toBe(false);
    expect(UploadedFiles.safeParse([file("run.exe")]).error?.issues[0]?.message).toBe(
      "run.exe is not a CSV, TSV, Excel, Parquet or PDF file.",
    );
  });
});

describe("filesOf", () => {
  it("groups a dataset's tables under the file each came from, sorted by file", () => {
    expect(
      filesOf([
        table("book__sales", ["book.xlsx"]),
        table("dealers", ["dealers.csv"]),
        table("book__returns", ["book.xlsx"]),
      ]),
    ).toEqual([
      { file: "book.xlsx", tables: ["book__sales", "book__returns"] },
      { file: "dealers.csv", tables: ["dealers"] },
    ]);
  });

  it("has nothing to say about a database's tables", () => {
    expect(filesOf([table("vehicles", [])])).toEqual([]);
  });

  it("lists a table under every file that feeds it", () => {
    expect(filesOf([table("sales", ["July.xlsx", "August.xlsx"])])).toEqual([
      { file: "August.xlsx", tables: ["sales"] },
      { file: "July.xlsx", tables: ["sales"] },
    ]);
  });
});

describe("formatting", () => {
  it.each([
    [512, "512 B"],
    [2048, "2 KB"],
    [3.4 * 1024 * 1024, "3.4 MB"],
  ])("prints %d bytes as %s", (bytes, printed) => {
    expect(formatBytes(bytes)).toBe(printed);
  });

  it.each([
    ["July dealers.xlsx", "July dealers"],
    ["q3.sales.csv", "q3.sales"],
    [".hidden", ".hidden"],
  ])("names %s as %s", (name, stem) => {
    expect(stemOf(name)).toBe(stem);
  });
});
