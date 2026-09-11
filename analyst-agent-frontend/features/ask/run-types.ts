import type { ChartSpec } from "@/lib/api/types";

/**
 * The agent's five contract stages, plus `web_tool` for a dashboard source.
 *
 * These are not a ladder. With bounded SQL retries the agent can go
 * `sql_gen -> sql_guard -> sql_gen` when the guard rejects a query and the model tries again,
 * so anything that renders them as a fixed five-step progress bar will lie on exactly the
 * runs worth looking at.
 */
export type Stage = "router" | "sql_gen" | "sql_guard" | "db_exec" | "web_tool" | "answer";

/**
 * A single table cell.
 *
 * The agent serialises with `json.dumps(..., default=str)`, so Python ints, floats, booleans
 * and None survive as JSON numbers, booleans and null, while Decimal, date, datetime and UUID
 * arrive as **strings**. A money column comes through as "266300.00". Never coerce a cell with
 * Number() to display it: in an analytics product that turns into silently wrong figures.
 */
export type Cell = string | number | boolean | null;

export type ResultTable = {
  columns: string[];
  rows: Cell[][];
  /** The agent caps results; true means there were more rows than were returned. */
  truncated: boolean;
};

/** Exactly the frozen SSE contract, one variant per `event:` name. */
export type RunEvent =
  | { type: "status"; data: { stage: Stage } }
  | { type: "sql"; data: { sql: string } }
  | { type: "rows"; data: ResultTable }
  | { type: "chart"; data: ChartSpec }
  | { type: "token"; data: { text: string } }
  | { type: "done"; data: { run_id: string; duration_ms: number } }
  | { type: "error"; data: { message: string } };

/** Client-side lifecycle facts, which the stream itself cannot report. */
export type RunAction =
  | { type: "@submit"; question: string; connectionId: string; threadId: string }
  | { type: "@open" }
  | { type: "@http"; status: number; message: string; code?: string }
  | { type: "@transport"; message: string }
  | { type: "@closed" }
  | { type: "@abort" }
  | { type: "@reset" }
  | RunEvent;

export type RunPhase =
  | "idle"
  | "connecting"
  | "routing"
  | "generating"
  | "guarding"
  | "executing"
  | "browsing"
  | "answering"
  | "done"
  | "error"
  | "cancelled";

export type RunErrorKind = "http" | "agent" | "transport" | "truncated";

export type RunError = {
  kind: RunErrorKind;
  message: string;
  status?: number;
  code?: string;
};

/** One pass at writing SQL. `rejected` means the guard bounced it and the model went again. */
export type Attempt = {
  sql: string | null;
  rejected: boolean;
};

export type RunState = {
  phase: RunPhase;
  threadId: string | null;
  connectionId: string | null;
  question: string | null;
  stage: Stage | null;
  /** Every stage in the order it happened, repeats included, so retries can be shown honestly. */
  stageLog: Stage[];
  attempts: Attempt[];
  /** The last SQL that passed the guard. */
  sql: string | null;
  result: ResultTable | null;
  chart: ChartSpec | null;
  answer: string;
  /** Only ever set by `done`: the terminal `error` event carries no run id. */
  runId: string | null;
  durationMs: number | null;
  error: RunError | null;
  startedAt: number | null;
};

export const IDLE_RUN: RunState = {
  phase: "idle",
  threadId: null,
  connectionId: null,
  question: null,
  stage: null,
  stageLog: [],
  attempts: [],
  sql: null,
  result: null,
  chart: null,
  answer: "",
  runId: null,
  durationMs: null,
  error: null,
  startedAt: null,
};

export const TERMINAL_PHASES: ReadonlySet<RunPhase> = new Set<RunPhase>([
  "done",
  "error",
  "cancelled",
]);

export function isRunning(phase: RunPhase): boolean {
  return phase !== "idle" && !TERMINAL_PHASES.has(phase);
}
