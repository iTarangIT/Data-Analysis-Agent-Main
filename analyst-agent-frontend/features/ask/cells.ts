import type { Cell } from "./run-types";

/**
 * How a result cell is read and aligned.
 *
 * Separate from the component because it is logic, not presentation, and because it is the
 * one place a mistake ships a wrong number rather than an ugly one.
 *
 * The agent serialises rows with `json.dumps(..., default=str)`. `default` is only consulted
 * for types JSON cannot encode, so Python ints, floats, booleans and None arrive as JSON
 * numbers, booleans and null, while `Decimal`, `date`, `datetime` and `UUID` arrive as
 * **strings**. A NUMERIC column reaches us as "7.20", trailing zero and all, because that is
 * the precision the database chose to express.
 */

/** A string that is entirely numeric: what a Decimal or a bigint column looks like. */
const NUMERIC_TEXT = /^-?\d+(\.\d+)?$/;

export function isNumericCell(value: Cell): boolean {
  if (typeof value === "number") return true;
  return typeof value === "string" && NUMERIC_TEXT.test(value);
}

/**
 * Whether a column should be right-aligned.
 *
 * Decided from the column rather than each cell, so one null does not knock a single figure
 * out of line with the rest. Stops after a sample: five hundred rows do not change the answer.
 */
export function columnIsNumeric(rows: Cell[][], index: number, sample = 20): boolean {
  let seen = 0;
  for (const row of rows) {
    const value = row[index];
    if (value === null || value === undefined) continue;
    if (!isNumericCell(value)) return false;
    seen++;
    if (seen >= sample) break;
  }
  return seen > 0;
}

export type RenderedCell =
  | { kind: "null" }
  | { kind: "boolean"; text: string }
  | { kind: "json"; text: string }
  | { kind: "value"; text: string };

/**
 * What to print.
 *
 * Never `Number(value)`. Coercing "7.20" gives 7.2 and coercing a bigint past 2^53 gives the
 * wrong integer outright, and in a product whose whole job is answering questions about
 * numbers that is the worst possible failure.
 *
 * A json, jsonb or array cell is printed as the JSON it arrived as. `String()` on it gives
 * "[object Object]" for an object and silently drops the brackets and quotes from an array.
 */
export function renderCell(value: Cell): RenderedCell {
  if (value === null || value === undefined) return { kind: "null" };
  if (typeof value === "boolean") return { kind: "boolean", text: value ? "true" : "false" };
  if (typeof value === "object") return { kind: "json", text: JSON.stringify(value) };
  return { kind: "value", text: String(value) };
}
