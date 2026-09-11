"use client";

import { Eyebrow, Panel } from "@/components/panel";
import type { RunSummary } from "@/lib/api/types";

/**
 * The same runs as a table, for reading across rather than down.
 *
 * Every column here is a field the agent actually sends. There is deliberately no "asked by":
 * a run is recorded against the organisation, not the person, so `RunSummary` carries no user.
 * Rather than print an em-dash in a column that would never fill, the note below says what is
 * missing and why -- an empty column that looks like a bug is worse than an honest sentence.
 */

export function RunAudit({ runs }: { runs: RunSummary[] }) {
  if (runs.length === 0) return null;

  return (
    <section className="flex flex-col gap-3">
      <div>
        <Eyebrow>Audit</Eyebrow>
        <p className="mt-1.5 max-w-[62ch] text-[0.875rem] leading-relaxed text-ink-muted">
          The same runs, as a table. Every query was read-only; the agent has no path that writes.
        </p>
      </div>

      <Panel className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full border-collapse font-mono text-[0.8125rem]">
            <thead>
              <tr>
                <Th>when</Th>
                <Th>question</Th>
                <Th>connection</Th>
                <Th align="right">rows</Th>
                <Th align="right">ms</Th>
                <Th>status</Th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.id} className="border-b border-line last:border-b-0">
                  <td className="px-3 py-1.5 whitespace-nowrap text-ink">
                    {run.created_at.slice(0, 16).replace("T", " ")}
                  </td>
                  <td className="max-w-[22rem] truncate px-3 py-1.5 text-ink" title={run.question}>
                    {run.question}
                  </td>
                  <td
                    className={`px-3 py-1.5 whitespace-nowrap ${run.connection_name ? "text-ink" : "text-ink-muted"}`}
                  >
                    {run.connection_name ?? "connection removed"}
                  </td>
                  <td className="px-3 py-1.5 text-right whitespace-nowrap text-ink tabular-nums">
                    {run.rows_returned}
                  </td>
                  <td className="px-3 py-1.5 text-right whitespace-nowrap text-ink tabular-nums">
                    {run.duration_ms}
                  </td>
                  <td
                    className={`px-3 py-1.5 whitespace-nowrap ${run.status === "error" ? "text-fault" : "text-ink-muted"}`}
                  >
                    {run.status}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p className="border-t border-line bg-surface-sunk px-3 py-2 text-[0.8125rem] text-ink-muted">
          Runs are recorded against the organisation rather than the person who asked, so this
          cannot yet say who ran what. That needs a field the agent does not send.
        </p>
      </Panel>
    </section>
  );
}

function Th({ children, align }: { children: React.ReactNode; align?: "right" }) {
  return (
    <th
      scope="col"
      className={`sticky top-0 z-10 border-b border-line bg-surface-sunk px-3 py-2 font-medium whitespace-nowrap text-ink ${
        align === "right" ? "text-right" : "text-left"
      }`}
    >
      {children}
    </th>
  );
}
