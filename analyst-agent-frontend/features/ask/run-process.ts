import { type RunState, type Stage } from "./run-types";

export const STAGE_LABEL: Record<Stage, string> = {
  router: "Reading your question",
  sql_gen: "Writing the query",
  sql_guard: "Checking the query is read-only",
  db_exec: "Running it on IoT database",
  answer: "Writing the answer",
};

// The last attempt is optimistically rejected while the check is still pending.
// Only a subsequent generation confirms a retry; a failed/aborted check does not.
export function confirmedRejections(state: RunState): number {
  return state.attempts.slice(0, -1).filter((attempt) => attempt.rejected).length;
}

export function buildProcessSteps(state: RunState) {
  let attempt = 0;
  return state.stageLog.map((stage, index) => {
    if (stage === "sql_gen") attempt++;
    const query = state.attempts[attempt - 1];
    const rejected = (stage === "sql_gen" || stage === "sql_guard") &&
      Boolean(query?.rejected && attempt < state.attempts.length);
    const interrupted = index === state.stageLog.length - 1 && state.phase !== "done";
    const unchecked = stage === "sql_guard" && !query?.sql;
    return {
      stage, label: STAGE_LABEL[stage], attempt, rejected,
      mark: rejected || interrupted || unchecked ? "hollow" as const : "done" as const,
    };
  });
}

export function processSummary(phase: string, durationMs: number, queries?: number, rejected = 0): string {
  const time = `${(durationMs / 1000).toFixed(1)}s`;
  if (phase === "error") return `Failed after ${time}`;
  if (phase === "cancelled") return `Stopped after ${time}`;
  if (phase !== "done") return "Run still in progress";
  const count = queries === undefined ? "" :
    ` · ${queries} ${queries === 1 ? "query" : "queries"}${rejected ? `, ${rejected} rejected` : ""}`;
  return `Answered in ${time}${count}`;
}
