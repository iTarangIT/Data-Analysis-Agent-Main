"use client";

import type { RunState, Stage } from "@/features/ask/run-types";
import { isRunning } from "@/features/ask/run-types";
import { cn } from "@/lib/utils";

/**
 * The stage spine.
 *
 * A hairline down the side of the transcript with one tick per stage the agent actually
 * reached, in the order it reached them. Hand-built rather than taken from a component
 * library because every stepper assumes a ladder, and this is not one: when the guard rejects
 * a query the agent goes back to writing SQL, so `sql_gen` can appear twice. A five-step
 * progress bar would quietly lie on exactly the runs worth looking at.
 *
 * The one piece of motion in the product, and it stops the moment the run settles.
 */

const LABEL: Record<Stage, string> = {
  router: "Reading the question",
  sql_gen: "Writing SQL",
  sql_guard: "Checking the query",
  db_exec: "Running it",
  web_tool: "Reading the dashboard",
  answer: "Writing the answer",
};

export function RunTimeline({ state }: { state: RunState }) {
  if (state.stageLog.length === 0) {
    return state.phase === "connecting" ? (
      <p className="font-mono text-[0.8125rem] text-ink-muted">
        <span className="is-live">Starting</span>
      </p>
    ) : null;
  }

  const live = isRunning(state.phase);
  const retried = state.attempts.filter((a) => a.rejected).length;

  return (
    <div className="flex flex-col gap-0.5">
      {state.stageLog.map((stage, i) => {
        const last = i === state.stageLog.length - 1;
        const current = last && live;

        return (
          <div key={`${stage}-${i}`} className="flex items-center gap-3">
            <span
              aria-hidden
              className={cn(
                "h-3.5 w-px",
                current ? "is-live bg-live" : "bg-rule-paper",
                i === 0 && "mt-1",
              )}
            />
            <span
              className={cn(
                "font-mono text-[0.75rem] tracking-tight",
                current ? "is-live text-live" : "text-ink-muted",
              )}
            >
              {LABEL[stage]}
            </span>
          </div>
        );
      })}

      {retried > 0 ? (
        <p className="mt-2 text-[0.75rem] text-ink-muted">
          {retried === 1
            ? "The first query did not pass the safety check, so it was rewritten."
            : `${retried} queries did not pass the safety check and were rewritten.`}
        </p>
      ) : null}
    </div>
  );
}
