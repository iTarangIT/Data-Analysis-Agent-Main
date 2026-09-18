import type { Attempt, Stage } from "./run-types";

export const STAGE_LABEL: Record<Stage, string> = {
  router: "Reading your question",
  sql_gen: "Writing the query",
  sql_guard: "Checking the query is read-only",
  db_exec: "Running it on IoT database",
  answer: "Writing the answer",
};

/**
 * The last attempt is optimistically rejected while its check is still pending. The agent's
 * `rejected` event confirms it with a reason, and so does the model trying again; a failed or
 * aborted check does neither.
 */
function isConfirmedRejection(attempts: Attempt[], index: number): boolean {
  const attempt = attempts[index];
  return attempt.rejected && (Boolean(attempt.reason) || index < attempts.length - 1);
}

export function confirmedRejections(attempts: Attempt[]): number {
  return attempts.filter((_, index) => isConfirmedRejection(attempts, index)).length;
}

/** The query the answer was written from: the last one that got as far as returning rows. */
export function answeringAttempt(attempts: Attempt[]): Attempt | undefined {
  return attempts.findLast((attempt) => !attempt.rejected && attempt.rows != null);
}

export type ProcessStep = {
  stage: Stage;
  label: string;
  attempt: number;
  rejected: boolean;
  mark: "done" | "hollow";
  /** What this step came to, in a few words: "rejected", "2 rows · 412 ms", "from 2 rows". */
  note: string | null;
};

export function buildProcessSteps(stageLog: Stage[], attempts: Attempt[], phase: string): ProcessStep[] {
  let attempt = 0;
  return stageLog.map((stage, index) => {
    if (stage === "sql_gen") attempt++;
    const query = attempts[attempt - 1];
    const writing = stage === "sql_gen" || stage === "sql_guard";
    const rejected = writing && Boolean(query) && isConfirmedRejection(attempts, attempt - 1);
    const interrupted = index === stageLog.length - 1 && phase !== "done";
    const unchecked = stage === "sql_guard" && !query?.sql;
    const mark = rejected || interrupted || unchecked ? "hollow" as const : "done" as const;
    const notes = [
      writing && attempt > 1 ? `attempt ${attempt}` : null,
      rejected ? (query.at === "database" ? "failed in the database" : "rejected")
        : mark === "hollow" ? "not completed" : outcome(stage, query, attempts),
    ];
    return { stage, label: STAGE_LABEL[stage], attempt, rejected, mark, note: notes.filter(Boolean).join(" · ") || null };
  });
}

function outcome(stage: Stage, query: Attempt | undefined, attempts: Attempt[]): string | null {
  if (stage === "db_exec" && query?.rows != null) {
    const found = query.truncated ? `cut off at ${rowCount(query.rows)}` : rowCount(query.rows);
    return query.ms != null ? `${found} · ${formatMs(query.ms)}` : found;
  }
  if (stage === "answer") {
    const rows = answeringAttempt(attempts)?.rows;
    return rows != null ? `from ${rowCount(rows)}` : null;
  }
  return null;
}

export type PlainSummary = { what?: string; why?: string; means?: string };

/**
 * What happened, for someone who does not read SQL.
 *
 * "What" and "why" are the model's own words, written with the query. "Means" is worked out
 * here from what the query returned, so it can never claim more than the run actually did.
 */
export function plainSummary(attempts: Attempt[], phase: string): PlainSummary | null {
  if (phase !== "done") return null;
  if (!attempts.some((attempt) => attempt.sql)) {
    return { what: "Nothing was looked up: this question didn't need your data." };
  }
  const source = answeringAttempt(attempts);
  const rows = source?.rows;
  if (!source || rows == null) {
    return { means: "None of the queries worked, so the answer doesn't come from your data." };
  }
  const means = rows === 0 ? "Nothing in your data matched this."
    : source.truncated ? `This found more than ${rows} results, so the answer only uses the first ${rows}.`
    : "The answer uses everything this found; nothing was left out.";
  return { what: source.what || undefined, why: source.why || undefined, means };
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

export function rowCount(rows: number): string {
  return `${rows} ${rows === 1 ? "row" : "rows"}`;
}

function formatMs(ms: number): string {
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)}s`;
}
