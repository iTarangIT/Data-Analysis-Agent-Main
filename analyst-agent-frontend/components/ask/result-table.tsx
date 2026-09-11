"use client";

import { columnIsNumeric, renderCell } from "@/features/ask/cells";
import type { Cell, ResultTable as Result } from "@/features/ask/run-types";
import { Panel } from "@/components/panel";
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

export function ResultTable({ result }: { result: Result }) {
  const { columns, rows, truncated } = result;
  const numeric = columns.map((_, i) => columnIsNumeric(rows, i));

  return (
    <Panel className="flex min-w-0 flex-col overflow-hidden">
      <div className="flex items-baseline justify-between gap-3 border-b border-line px-4 py-2.5">
        <p className="text-[0.6875rem] font-semibold tracking-[0.08em] text-ink-muted uppercase">
          {rows.length === 1 ? "1 row" : `${rows.length} rows`}
        </p>
        {truncated ? (
          <p className="text-[0.6875rem] text-warning">
            capped, ask for a narrower range to see the rest
          </p>
        ) : null}
      </div>

      {rows.length === 0 ? (
        <p className="px-4 py-8 text-center text-[0.875rem] text-ink-muted">
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
                      "sticky top-0 z-10 border-b border-line bg-surface-sunk px-4 py-2 font-medium whitespace-nowrap text-ink-muted",
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
                <tr key={r} className="border-b border-line last:border-b-0">
                  {row.map((value, c) => (
                    <td
                      key={c}
                      className={cn(
                        "px-4 py-1.5 whitespace-nowrap text-ink",
                        numeric[c] ? "text-right tabular-nums" : "text-left",
                      )}
                    >
                      <RenderedCell value={value} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

/** Null and booleans are shown as absent and as words, both in the muted ink. */
function RenderedCell({ value }: { value: Cell }) {
  const rendered = renderCell(value);
  if (rendered.kind === "value") return rendered.text;
  return <span className="text-ink-muted">{rendered.kind === "null" ? "null" : rendered.text}</span>;
}
