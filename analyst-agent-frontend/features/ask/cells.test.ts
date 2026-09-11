import { describe, expect, it } from "vitest";

import { columnIsNumeric, isNumericCell, renderCell } from "./cells";

/**
 * These fixtures are what the demo database actually produces. `batteries.capacity_kwh` is
 * NUMERIC, so `json.dumps(..., default=str)` sends "7.20" while `id`, an integer, stays 1.
 */
describe("renderCell", () => {
  it("prints a Decimal exactly as it arrived", () => {
    // The trailing zero is the precision the column was defined with. Number() would drop it.
    expect(renderCell("7.20")).toEqual({ kind: "value", text: "7.20" });
    expect(renderCell("266300.00")).toEqual({ kind: "value", text: "266300.00" });
  });

  it("does not round a long decimal", () => {
    expect(renderCell("0.1234567890123456789")).toEqual({
      kind: "value",
      text: "0.1234567890123456789",
    });
  });

  it("keeps an integer beyond what a double can hold", () => {
    // 9007199254740993 is 2^53 + 1. Coercing it silently returns 9007199254740992.
    expect(renderCell("9007199254740993")).toEqual({
      kind: "value",
      text: "9007199254740993",
    });
  });

  it("prints a real number unchanged", () => {
    expect(renderCell(3)).toEqual({ kind: "value", text: "3" });
    expect(renderCell(-12.5)).toEqual({ kind: "value", text: "-12.5" });
  });

  it("marks null so it can be shown as absent rather than as empty", () => {
    expect(renderCell(null)).toEqual({ kind: "null" });
  });

  it("marks booleans, which Postgres sends as true JSON booleans", () => {
    expect(renderCell(true)).toEqual({ kind: "boolean", text: "true" });
    expect(renderCell(false)).toEqual({ kind: "boolean", text: "false" });
  });

  it("prints a date, which arrives as a string", () => {
    expect(renderCell("2026-09-11")).toEqual({ kind: "value", text: "2026-09-11" });
  });
});

describe("isNumericCell", () => {
  it.each([1, -1, 0, 3.14])("treats the number %s as numeric", (value) => {
    expect(isNumericCell(value)).toBe(true);
  });

  it.each(["7.20", "-3", "0", "266300.00"])(
    "treats the Decimal string %s as numeric",
    (value) => {
      expect(isNumericCell(value)).toBe(true);
    },
  );

  it.each(["Acme Corp", "2026-09-11", "", "1e5", "12abc", "1,200"])(
    "does not treat %s as numeric",
    (value) => {
      expect(isNumericCell(value)).toBe(false);
    },
  );

  it("does not treat a boolean as numeric", () => {
    expect(isNumericCell(true)).toBe(false);
  });
});

describe("columnIsNumeric", () => {
  const rows = [
    [1, "7.20", "Acme Corp", null],
    [2, "10.00", "Northwind", true],
  ];

  it("finds an integer column", () => {
    expect(columnIsNumeric(rows, 0)).toBe(true);
  });

  it("finds a Decimal column", () => {
    expect(columnIsNumeric(rows, 1)).toBe(true);
  });

  it("leaves a text column alone", () => {
    expect(columnIsNumeric(rows, 2)).toBe(false);
  });

  it("leaves a column of only nulls alone", () => {
    expect(columnIsNumeric(rows, 3)).toBe(false);
  });

  it("ignores a null among numbers, so one gap does not break the alignment", () => {
    expect(columnIsNumeric([[1], [null], [3]], 0)).toBe(true);
  });

  it("is decided by the column, not by one cell", () => {
    // A single piece of text makes the whole column text, which is what keeps a mixed
    // column readable rather than half-aligned.
    expect(columnIsNumeric([[1], ["n/a"], [3]], 0)).toBe(false);
  });

  it("stops after the sample rather than walking every row", () => {
    // The five hundredth row cannot change the answer, and a full scan on every render would.
    const many = [...Array(499).fill([1]), ["text"]];
    expect(columnIsNumeric(many, 0, 20)).toBe(true);
  });
});
