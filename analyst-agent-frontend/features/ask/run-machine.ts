import {
  type Attempt,
  IDLE_RUN,
  type RunAction,
  type RunPhase,
  type RunState,
  type Stage,
  TERMINAL_PHASES,
} from "./run-types";

const PHASE_FOR: Record<Stage, RunPhase> = {
  router: "routing",
  sql_gen: "generating",
  sql_guard: "guarding",
  db_exec: "executing",
  answer: "answering",
};

/** Every event after `sql_gen` is about the query it started, which is always the last one. */
function patchLast(attempts: Attempt[], patch: Partial<Attempt>): Attempt[] {
  if (attempts.length === 0) return attempts;
  return [...attempts.slice(0, -1), { ...attempts[attempts.length - 1], ...patch }];
}

/** A `sql` event means the guard passed, so the attempt it was about is not rejected. */
function acceptPending(
  attempts: Attempt[],
  accepted: { sql: string; what?: string; why?: string },
): Attempt[] {
  const attempt = { ...accepted, rejected: false };
  if (attempts.length === 0) return [attempt];
  return [...attempts.slice(0, -1), attempt];
}

/**
 * The whole run, as a pure function of the events that arrived.
 *
 * No React, no fetch, no timers, so every path can be driven as an array in a test. Three
 * rules here are not obvious and are the ones worth protecting:
 *
 * 1. Stages can go backwards. The agent retries after the guard rejects a query, so
 *    `sql_gen` follows `sql_guard`. The stage log keeps repeats rather than flattening them.
 * 2. Entering `answer` resets the answer buffer and `token` appends to it. That is correct
 *    whether the backend sends the whole answer in one event (as it does today) or in chunks
 *    (as it may later), and it handles the stage being entered twice.
 * 3. A stream that closes without `done` or `error` is a failure. Treating it as success is
 *    how a truncated run gets presented as a complete answer.
 */
export function runReducer(state: RunState, action: RunAction): RunState {
  // Once a run has settled, only starting over changes anything. The reader reports how the
  // stream finished on every run, so a late `@closed` arrives even on the happy path.
  if (TERMINAL_PHASES.has(state.phase) && action.type !== "@submit" && action.type !== "@reset") {
    return state;
  }

  switch (action.type) {
    case "@submit":
      return {
        ...IDLE_RUN,
        phase: "connecting",
        question: action.question,
        connectionId: action.connectionId,
        threadId: action.threadId,
        startedAt: Date.now(),
      };

    // Headers are back, but nothing has happened yet. The first `status` moves us on.
    case "@open":
      return state;

    case "status": {
      const { stage, tool } = action.data;
      // The guard is announced before its verdict is known, so a pending attempt starts
      // rejected until a `sql` event accepts it.
      const attempts =
        stage === "sql_gen"
          ? [...state.attempts, { sql: null, rejected: false, ...(tool ? { tool } : {}) }]
          : stage === "sql_guard"
            ? patchLast(state.attempts, { rejected: true })
            : state.attempts;

      return {
        ...state,
        phase: PHASE_FOR[stage],
        stage,
        stageLog: [...state.stageLog, stage],
        attempts,
        answer: stage === "answer" ? "" : state.answer,
      };
    }

    case "sql":
      return {
        ...state,
        sql: action.data.sql,
        // The previous table answered the previous query; keeping it beside new SQL would
        // show a result that never came from it.
        result: null,
        chart: null,
        attempts: acceptPending(state.attempts, action.data),
      };

    case "rejected": {
      const { sql, reason, at } = action.data;
      return { ...state, attempts: patchLast(state.attempts, { sql, reason, at, rejected: true }) };
    }

    case "rows": {
      const { rows, truncated, ms } = action.data;
      return {
        ...state,
        result: action.data,
        attempts: patchLast(state.attempts, { rows: rows.length, truncated, ms }),
      };
    }

    case "chart":
      return { ...state, chart: action.data };

    case "token":
      return { ...state, answer: state.answer + action.data.text };

    case "done":
      return {
        ...state,
        phase: "done",
        runId: action.data.run_id,
        durationMs: action.data.duration_ms,
      };

    case "error":
      return {
        ...state,
        phase: "error",
        durationMs: elapsed(state),
        error: { kind: "agent", message: action.data.message },
      };

    case "@http":
      return {
        ...state,
        phase: "error",
        durationMs: elapsed(state),
        error: {
          kind: "http",
          message: action.message,
          status: action.status,
          code: action.code,
        },
      };

    case "@transport":
      return {
        ...state,
        phase: "error",
        durationMs: elapsed(state),
        error: { kind: "transport", message: action.message },
      };

    case "@closed":
      return {
        ...state,
        phase: "error",
        durationMs: elapsed(state),
        error: {
          kind: "truncated",
          message: "the connection closed before the run finished",
        },
      };

    case "@abort":
      // Deliberately no error: the person asked for this, so nothing should turn red.
      return { ...state, phase: "cancelled", durationMs: elapsed(state) };

    case "@reset":
      return IDLE_RUN;

    default:
      return state;
  }
}

function elapsed(state: RunState): number {
  return state.startedAt === null ? 0 : Math.max(0, Date.now() - state.startedAt);
}
