"use client";

import type { Cell, ResultTable as Result } from "@/features/ask/run-types";
import { cn } from "@/lib/utils";

/**
 * The result grid.
 *
 * Hand-built, because the awkward parts here are not layout. The agent serialises with
 * `default=str`, so a Decimal, date, datetime or UUID arrives as a **string** while ints,
 * floats and booleans stay themselves. A generic data grid coerces cells to display them,
 * and in an analytics product that turns "266300.00" into a rounded float and ships a wrong
 * number with total confidence. Nothing here ever calls Number() on a cell.
 */

/** A string that is entirely numeric: what a Decimal or a bigint column looks like. */
const NUMERIC_TEXT = /^-?\d+(\.\d+)?$/;

function isNumericCell(value: Cell): boolean {
  if (typeof value === "number") return true;
  return typeof value === "string" && NUMERIC_TEXT.test(value);
}

/**
 * Align a column by what it holds, not by its name. Decided from the column rather than the
 * cell so a single null does not knock one figure out of line with the rest.
 */
function columnIsNumeric(rows: Cell[][], index: number): boolean {
  let seen = 0;
  for (const row of rows) {
    const value = row[index];
    if (value === null) continue;
    if (!isNumericCell(value)) return false;
    seen++;
    if (seen >= 20) break; // enough to decide; no need to walk five hundred rows
  }
  return seen > 0;
}

function renderCell(value: Cell) {
  if (value === null) {
    return <span className="text-ink-muted">null</span>;
  }
  if (typeof value === "boolean") {
    return <span className="text-ink-muted">{value ? "true" : "false"}</span>;
  }
  // Printed exactly as it arrived. This is the line that keeps money correct.
  return String(value);
}

export function ResultTable({ result }: { result: Result }) {
  const { columns, rows, truncated } = result;
  const numeric = columns.map((_, i) => columnIsNumeric(rows, i));

  return (
    <div className="border border-rule-paper bg-paper">
      <div className="flex items-baseline justify-between border-b border-rule-paper px-3 py-2">
        <p className="font-mono text-[0.75rem] text-ink-muted">
          {rows.length === 1 ? "1 row" : `${rows.length} rows`}
        </p>
        {truncated ? (
          <p className="font-mono text-[0.75rem] text-ink-muted">
            capped, ask for a narrower range to see the rest
          </p>
        ) : null}
      </div>

      {rows.length === 0 ? (
        <p className="px-3 py-6 text-[0.875rem] text-ink-muted">
          The query ran and matched nothing.
        </p>
      ) : (
        // Only the grid scrolls sideways, never the page.
        <div className="max-h-[26rem] overflow-auto">
          <table className="w-full border-collapse font-mono text-[0.8125rem]">
            <thead>
              <tr>
                {columns.map((column, i) => (
                  <th
                    key={column}
                    scope="col"
                    className={cn(
                      // Sticky so the header survives five hundred rows of scrolling.
                      "sticky top-0 z-10 border-b border-rule-paper bg-paper-sunk px-3 py-2 font-medium whitespace-nowrap text-ink",
                      numeric[i] ? "text-right" : "text-left",
                    )}
                  >
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, r) => (
                <tr key={r} className="border-b border-rule-paper last:border-b-0">
                  {row.map((value, c) => (
                    <td
                      key={c}
                      className={cn(
                        "px-3 py-1.5 whitespace-nowrap text-ink",
                        numeric[c] ? "text-right tabular-nums" : "text-left",
                      )}
                    >
                      {renderCell(value)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
