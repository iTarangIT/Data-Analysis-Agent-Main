"use client";

import { Check } from "lucide-react";

import type { RunState, Stage } from "@/features/ask/run-types";
import { isRunning } from "@/features/ask/run-types";
import { cn } from "@/lib/utils";

/**
 * The stage spine.
 *
 * One mark per stage the agent actually reached, in the order it reached them. Hand-built
 * rather than taken from a component library because every stepper assumes a ladder, and this
 * is not one: when the guard rejects a query the agent goes back to writing SQL, so `sql_gen`
 * can appear twice. A fixed five-step progress bar would quietly lie on exactly the runs
 * worth looking at.
 *
 * Because the log holds only what happened, there is no such thing as a stage that has not
 * started yet, and a hollow mark is never a guess about the future. It means one of two real
 * things: work that was superseded when the guard sent the model back, or the final stage of
 * a run that stopped before finishing.
 *
 * The one piece of motion in the product, and it stops the moment the run settles.
 */

const LABEL: Record<Stage, string> = {
  router: "Understanding the question",
  sql_gen: "Writing the query",
  sql_guard: "Checking the query",
  db_exec: "Running on database",
  web_tool: "Reading the dashboard",
  answer: "Writing the answer",
};

type Mark = "done" | "running" | "hollow";

function StageMark({ mark }: { mark: Mark }) {
  if (mark === "running") {
    return (
      <span
        aria-hidden
        className="is-live size-4 shrink-0 rounded-full border-2 border-brand/25 border-t-brand"
      />
    );
  }
  if (mark === "hollow") {
    return (
      <span
        aria-hidden
        className="size-4 shrink-0 rounded-full border border-line-strong bg-surface"
      />
    );
  }
  return (
    <span
      aria-hidden
      className="flex size-4 shrink-0 items-center justify-center rounded-full bg-brand"
    >
      <Check className="size-2.5 text-white" strokeWidth={3.5} />
    </span>
  );
}

export function RunTimeline({
  state,
  onCancel,
}: {
  state: RunState;
  onCancel?: () => void;
}) {
  const live = isRunning(state.phase);
  if (state.stageLog.length === 0 && !live) return null;

  const lastIndex = state.stageLog.length - 1;
  // Read the log, not `attempts`: the machine flags an attempt rejected optimistically the
  // moment the guard starts and only clears it when the SQL arrives, so `attempts` would
  // flash the running attempt as thrown away for the length of the check.
  const lastSqlGen = state.stageLog.lastIndexOf("sql_gen");
  const retried = state.attempts.filter((a) => a.rejected).length;

  function markOf(stage: Stage, i: number): Mark {
    if (i === lastIndex) {
      if (live) return "running";
      return state.phase === "done" ? "done" : "hollow";
    }
    if ((stage === "sql_gen" || stage === "sql_guard") && i < lastSqlGen) return "hollow";
    return "done";
  }

  return (
    <div className="flex flex-col">
      {state.stageLog.length === 0 ? (
        <p className="flex items-center gap-3 py-1 text-[0.8125rem] text-brand">
          <span
            aria-hidden
            className="is-live size-4 shrink-0 rounded-full border-2 border-brand/25 border-t-brand"
          />
          Starting
        </p>
      ) : (
        <ol className="flex flex-col">
          {state.stageLog.map((stage, i) => {
            const mark = markOf(stage, i);
            return (
              <li key={`${stage}-${i}`} className="relative flex items-center gap-3 py-1">
                {i < lastIndex ? (
                  <span
                    aria-hidden
                    className="absolute top-[1.375rem] left-[0.4375rem] h-2 w-px bg-line"
                  />
                ) : null}
                <StageMark mark={mark} />
                <span
                  className={cn(
                    "text-[0.8125rem]",
                    mark === "running"
                      ? "font-medium text-brand"
                      : mark === "hollow"
                        ? "text-ink-faint"
                        : "text-ink",
                  )}
                >
                  {LABEL[stage]}
                </span>
              </li>
            );
          })}
        </ol>
      )}

      {retried > 0 ? (
        <p className="mt-2 text-[0.75rem] text-ink-muted">
          {retried === 1
            ? "The first query did not pass the safety check, so it was rewritten."
            : `${retried} queries did not pass the safety check and were rewritten.`}
        </p>
      ) : null}

      {live && onCancel ? (
        <button
          type="button"
          onClick={onCancel}
          className="mt-3 self-start text-[0.75rem] font-semibold tracking-[0.06em] text-fault uppercase underline-offset-4 hover:underline"
        >
          Cancel execution
        </button>
      ) : null}
    </div>
  );
}
