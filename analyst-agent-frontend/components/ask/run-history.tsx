"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import type { RunDetail, RunPage, RunSummary } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { SqlBlock } from "./sql-block";

/**
 * Past runs.
 *
 * The list carries no SQL or answer text, deliberately: both are unbounded, and a page of
 * fifty would be a heavy payload for what is only a way to find a run. Opening one fetches it.
 *
 * There is no stored result table and there never will be. The agent records how many rows
 * came back, not what they were, because keeping a customer's query results in our own
 * database is exactly what its sample-row setting exists to prevent.
 */

function when(iso: string): string {
  const date = new Date(iso);
  const minutes = Math.round((Date.now() - date.getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  if (minutes < 60 * 24) return `${Math.round(minutes / 60)}h ago`;
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

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

  if (error) return <p className="py-3 text-[0.875rem] text-fault">{error}</p>;
  if (!detail) return <p className="py-3 text-[0.875rem] text-ink-muted">Loading</p>;

  return (
    <div className="flex flex-col gap-4 py-4">
      {detail.sql ? <SqlBlock sql={detail.sql} /> : null}
      {detail.answer ? (
        <p className="max-w-[68ch] text-[0.9375rem] leading-[1.65] text-ink">{detail.answer}</p>
      ) : (
        <p className="text-[0.875rem] text-ink-muted">
          No answer was recorded for this run.
        </p>
      )}
    </div>
  );
}

function Row({ run }: { run: RunSummary }) {
  const [open, setOpen] = useState(false);

  return (
    <li className="border-b border-rule-paper">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-baseline gap-4 py-4 text-left"
      >
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[0.9375rem] text-ink">{run.question}</span>
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

export function RunHistory({ initial }: { initial: RunPage }) {
  const [items, setItems] = useState(initial.items);
  const [cursor, setCursor] = useState(initial.next_cursor);
  const [loading, setLoading] = useState(false);

  async function more() {
    if (!cursor) return;
    setLoading(true);
    try {
      const response = await fetch(`/api/runs?limit=50&cursor=${encodeURIComponent(cursor)}`);
      if (response.ok) {
        const page = (await response.json()) as RunPage;
        setItems((current) => [...current, ...page.items]);
        setCursor(page.next_cursor);
      }
    } finally {
      setLoading(false);
    }
  }

  if (items.length === 0) {
    return (
      <p className="border-t border-rule-paper py-8 text-[0.9375rem] text-ink-muted">
        Nothing asked yet.
      </p>
    );
  }

  return (
    <>
      <ul className="border-t border-rule-paper">
        {items.map((run) => (
          <Row key={run.id} run={run} />
        ))}
      </ul>

      {cursor ? (
        <Button
          variant="ghost"
          onClick={more}
          disabled={loading}
          className="mt-6 h-9 px-3 text-[0.875rem] text-ink-muted hover:text-ink"
        >
          {loading ? "Loading" : "Show older"}
        </Button>
      ) : null}
    </>
  );
}
