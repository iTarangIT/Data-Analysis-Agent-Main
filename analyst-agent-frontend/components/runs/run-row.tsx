"use client";

import { useEffect, useState } from "react";

import { SqlBlock } from "@/components/ask/sql-block";
import type { RunDetail, RunSummary } from "@/lib/api/types";
import { when } from "@/lib/time";
import { cn } from "@/lib/utils";

/**
 * One past run, and what opening it fetches.
 *
 * The list carries no SQL or answer text, deliberately: both are unbounded, and a page of
 * fifty would be a heavy payload for what is only a way to find a run. Opening one fetches it.
 *
 * There is no stored result table and there never will be. The agent records how many rows
 * came back, not what they were.
 */

function Detail({ runId }: { runId: string }) {
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Fetching here is correct, unlike starting a run: this reads a row the person just asked
  // to see, costs nothing, and is abandoned if they close the row again.
  useEffect(() => {
    const controller = new AbortController();
    fetch(`/api/runs/${runId}`, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("failed");
        setDetail((await response.json()) as RunDetail);
      })
      .catch(() => {
        if (!controller.signal.aborted) setError("Could not load that run.");
      });
    return () => controller.abort();
  }, [runId]);

  if (error)
    return (
      <p className="border-t border-line bg-surface-sunk px-5 py-3 text-[0.875rem] text-fault">
        {error}
      </p>
    );
  if (!detail)
    return (
      <p className="border-t border-line bg-surface-sunk px-5 py-3 text-[0.875rem] text-ink-muted">
        Loading
      </p>
    );

  return (
    <div className="flex flex-col gap-4 border-t border-line bg-surface-sunk px-5 py-4">
      {detail.sql ? <SqlBlock sql={detail.sql} /> : null}
      {detail.answer ? (
        <p className="max-w-[68ch] text-[0.9375rem] leading-[1.65] text-ink">{detail.answer}</p>
      ) : (
        <p className="text-[0.875rem] text-ink-muted">No answer was recorded for this run.</p>
      )}

      {/* What the run cost. These three fields exist only on the detail, which is why they
          appear here and not in the figures above the list. */}
      {detail.model ? (
        <dl className="flex flex-wrap gap-x-8 gap-y-1 font-mono text-[0.75rem] text-ink-muted">
          <div className="flex gap-2">
            <dt>model</dt>
            <dd className="text-ink">{detail.model}</dd>
          </div>
          <div className="flex gap-2">
            <dt>prompt</dt>
            <dd className="text-ink tabular-nums">{detail.prompt_tokens.toLocaleString()}</dd>
          </div>
          <div className="flex gap-2">
            <dt>completion</dt>
            <dd className="text-ink tabular-nums">{detail.completion_tokens.toLocaleString()}</dd>
          </div>
        </dl>
      ) : null}
    </div>
  );
}

export function RunRow({ run }: { run: RunSummary }) {
  const [open, setOpen] = useState(false);

  return (
    <li className="border-b border-line last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-baseline gap-4 px-5 py-3.5 text-left transition-colors hover:bg-surface-sunk"
      >
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[0.875rem] text-ink">{run.question}</span>
          <span className="mt-0.5 block font-mono text-[0.75rem] text-ink-muted">
            {run.connection_name ?? "connection removed"}
            {" · "}
            {run.rows_returned === 1 ? "1 row" : `${run.rows_returned} rows`}
            {" · "}
            {(run.duration_ms / 1000).toFixed(1)}s
          </span>
        </span>
        <span
          className={cn(
            "shrink-0 font-mono text-[0.75rem]",
            run.status === "error" ? "text-fault" : "text-ink-muted",
          )}
        >
          {run.status === "error" ? "failed" : when(run.created_at)}
        </span>
      </button>

      {open ? <Detail runId={run.id} /> : null}
    </li>
  );
}
