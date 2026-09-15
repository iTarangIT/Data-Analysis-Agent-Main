"use client";

import { ChevronDown } from "lucide-react";
import { useEffect, useState } from "react";

import type { RunDetail, RunSummary } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/**
 * A turn from before this sitting, replayed from the agent.
 *
 * Collapsed, and deliberately without a result table. The agent records how many rows came
 * back, never what they were, so there is no table to restore and there never will be --
 * re-asking the question is how you get fresh numbers. Saying that plainly beats an empty
 * grid that looks like a bug.
 *
 * The list carries no SQL or answer text either, because both are unbounded and a thread of
 * fifty would be a heavy payload for what is only a way to find your place. Opening one
 * fetches it, the same way the runs page does.
 */
function Detail({ runId }: { runId: string }) {
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Fetching here is correct, unlike starting a run: this reads a row the person just asked
  // to see, costs nothing, and is abandoned if they close it again.
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

  if (error) return <p className="pt-3 text-[0.875rem] text-fault">{error}</p>;
  if (!detail) return <p className="pt-3 text-[0.875rem] text-ink-muted">Loading</p>;

  return (
    <div className="flex flex-col gap-3 pt-3">      {detail.answer ? (
        <p className="max-w-[68ch] text-[0.9375rem] leading-[1.65] text-ink">{detail.answer}</p>
      ) : (
        <p className="text-[0.875rem] text-ink-muted">No answer was recorded for this run.</p>
      )}
      <p className="text-[0.75rem] text-ink-muted">
        Results are not stored. Ask it again for fresh numbers.
      </p>
    </div>
  );
}

export function PastTurn({ run }: { run: RunSummary }) {
  const [open, setOpen] = useState(false);

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-start gap-2 text-left"
      >
        <ChevronDown
          aria-hidden
          className={cn(
            "mt-1 size-4 shrink-0 text-ink-faint transition-transform",
            open && "rotate-180",
          )}
          strokeWidth={2}
        />
        <span className="min-w-0 flex-1">
          <span className="block text-[0.9375rem] leading-[1.6] text-ink">{run.question}</span>
          <span className="mt-0.5 block font-mono text-[0.6875rem] text-ink-muted">
            {run.status === "error"
              ? "failed"
              : `${run.rows_returned} row${run.rows_returned === 1 ? "" : "s"} · ${(run.duration_ms / 1000).toFixed(1)}s`}
          </span>
        </span>
      </button>

      {open ? <Detail runId={run.id} /> : null}
    </div>
  );
}
