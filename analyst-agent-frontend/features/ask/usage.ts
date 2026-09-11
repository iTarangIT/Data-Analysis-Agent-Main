import type { Usage } from "@/lib/api/types";

/**
 * What a window of usage adds up to.
 *
 * Pure. Everything here comes from the agent's own `/usage` aggregate rather than from the
 * page of runs that happens to be loaded, so the figures cover the account rather than the
 * scroll position. An earlier version of this file summed `RunSummary[]` because there was
 * believed to be no totals endpoint; there is one, and it also carries the token counts a
 * run summary never did.
 *
 * The budget is measured against `tokens_last_24h`, a rolling window, because that is the
 * number the agent compares against the ceiling when it refuses a run. The day buckets are
 * calendar days; summing the latest one would draw a bar that disagrees with the error
 * people actually hit.
 */

export type BudgetState = "ok" | "warning" | "critical" | "unknown";

export type UsageTotals = {
  runs: number;
  /** Prompt and completion together: a token is a token whichever direction it went. */
  tokens: number;
  rowsReturned: number;
  errors: number;
  /** The busiest day in the window, so a chart can mark it. Null when nothing ran. */
  peakDay: string | null;
  peakRuns: number;
  /** 0..1, clamped. Null when the account has no ceiling to measure against. */
  budgetUsed: number | null;
  budgetState: BudgetState;
};

const WARNING_AT = 0.75;
const CRITICAL_AT = 0.9;

function stateOf(used: number | null): BudgetState {
  if (used === null) return "unknown";
  if (used >= CRITICAL_AT) return "critical";
  if (used >= WARNING_AT) return "warning";
  return "ok";
}

export function summariseUsage(usage: Usage): UsageTotals {
  let runs = 0;
  let tokens = 0;
  let rowsReturned = 0;
  let errors = 0;
  let peakDay: string | null = null;
  let peakRuns = 0;

  for (const day of usage.days) {
    runs += day.runs;
    tokens += day.prompt_tokens + day.completion_tokens;
    rowsReturned += day.rows_returned;
    errors += day.errors;

    // Strictly greater, so a tie keeps the earlier day and the mark does not drift
    // rightwards every time the window is refetched.
    if (day.runs > peakRuns) {
      peakRuns = day.runs;
      peakDay = day.day;
    }
  }

  const budget = usage.daily_token_budget;
  const budgetUsed = budget > 0 ? Math.min(1, usage.tokens_last_24h / budget) : null;

  return {
    runs,
    tokens,
    rowsReturned,
    errors,
    peakDay,
    peakRuns,
    budgetUsed,
    budgetState: stateOf(budgetUsed),
  };
}
