import type { Attempt, ChartSpec, Stage } from "@/lib/api/types";

export type { Attempt, Stage } from "@/lib/api/types";

/**
 * A single table cell.
 *
 * The agent serialises with `json.dumps(..., default=str)`, so Python ints, floats, booleans
 * and None survive as JSON numbers, booleans and null, while Decimal, date, datetime and UUID
 * arrive as **strings**. A money column comes through as "266300.00". Never coerce a cell with
 * Number() to display it: in an analytics product that turns into silently wrong figures.
 *
 * Not every cell is a scalar. psycopg decodes json and jsonb columns into Python lists and
 * dicts, and Postgres arrays into lists, and `json.dumps` sends those on as JSON arrays and
 * objects. `info -> 'assignedgroups'` is one: a list of `{"groupname": ...}` objects.
 */
export type Cell = string | number | boolean | null | Cell[] | { [key: string]: Cell };

export type ResultTable = {
  columns: string[];
  rows: Cell[][];
  /** The agent caps results; true means there were more rows than were returned. */
  truncated: boolean;
};

/** Exactly the frozen SSE contract, one variant per `event:` name. */
export type RunEvent =
  | { type: "status"; data: { stage: Stage } }
  | { type: "sql"; data: { sql: string; what?: string; why?: string } }
  | { type: "rejected"; data: { sql: string; reason: string; at: "guard" | "database" } }
  | { type: "rows"; data: ResultTable & { ms?: number } }
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
