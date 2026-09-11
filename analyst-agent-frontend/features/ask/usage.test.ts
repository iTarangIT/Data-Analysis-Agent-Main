import { describe, expect, it } from "vitest";

import type { Usage, UsageDay } from "@/lib/api/types";

import { summariseUsage } from "./usage";

function day(over: Partial<UsageDay> = {}): UsageDay {
  return {
    day: "2026-09-11",
    runs: 0,
    prompt_tokens: 0,
    completion_tokens: 0,
    rows_returned: 0,
    errors: 0,
    ...over,
  };
}

function usage(over: Partial<Usage> = {}): Usage {
  return {
    daily_token_budget: 200_000,
    tokens_last_24h: 0,
    runs_last_24h: 0,
    days: [],
    ...over,
  };
}

describe("summariseUsage", () => {
  it("adds up runs across every day in the window", () => {
    const totals = summariseUsage(
      usage({ days: [day({ runs: 42 }), day({ runs: 128 })] }),
    );
    expect(totals.runs).toBe(170);
  });

  it("counts a token as a token whichever direction it went", () => {
    const totals = summariseUsage(
      usage({ days: [day({ prompt_tokens: 1000, completion_tokens: 200 })] }),
    );
    expect(totals.tokens).toBe(1200);
  });

  it("adds up rows and errors", () => {
    const totals = summariseUsage(
      usage({
        days: [day({ rows_returned: 10, errors: 1 }), day({ rows_returned: 5, errors: 2 })],
      }),
    );
    expect(totals.rowsReturned).toBe(15);
    expect(totals.errors).toBe(3);
  });

  it("reports zeroes rather than nulls for an account that has never run anything", () => {
    const totals = summariseUsage(usage());
    expect(totals.runs).toBe(0);
    expect(totals.tokens).toBe(0);
    expect(totals.rowsReturned).toBe(0);
    expect(totals.errors).toBe(0);
    expect(totals.peakRuns).toBe(0);
  });

  it("finds the busiest day so a chart can mark it", () => {
    const totals = summariseUsage(
      usage({
        days: [
          day({ day: "2026-09-09", runs: 4 }),
          day({ day: "2026-09-10", runs: 19 }),
          day({ day: "2026-09-11", runs: 7 }),
        ],
      }),
    );
    expect(totals.peakRuns).toBe(19);
    expect(totals.peakDay).toBe("2026-09-10");
  });

  it("keeps the first of two equally busy days rather than the last", () => {
    const totals = summariseUsage(
      usage({
        days: [day({ day: "2026-09-09", runs: 5 }), day({ day: "2026-09-10", runs: 5 })],
      }),
    );
    expect(totals.peakDay).toBe("2026-09-09");
  });

  // The rolling 24h figure, never a sum of the day buckets: it is what the agent itself
  // compares against the budget when it refuses a run.
  it("measures the budget against the rolling window, not the calendar day", () => {
    const totals = summariseUsage(
      usage({
        daily_token_budget: 1000,
        tokens_last_24h: 840,
        days: [day({ prompt_tokens: 999_999 })],
      }),
    );
    expect(totals.budgetUsed).toBeCloseTo(0.84);
  });

  it("calls three quarters spent a warning", () => {
    const totals = summariseUsage(
      usage({ daily_token_budget: 1000, tokens_last_24h: 750 }),
    );
    expect(totals.budgetState).toBe("warning");
  });

  it("calls nine tenths spent critical", () => {
    const totals = summariseUsage(
      usage({ daily_token_budget: 1000, tokens_last_24h: 900 }),
    );
    expect(totals.budgetState).toBe("critical");
  });

  it("leaves a half-spent budget alone", () => {
    const totals = summariseUsage(
      usage({ daily_token_budget: 1000, tokens_last_24h: 500 }),
    );
    expect(totals.budgetState).toBe("ok");
  });

  it("does not let an overspent budget draw past the end of the bar", () => {
    const totals = summariseUsage(
      usage({ daily_token_budget: 1000, tokens_last_24h: 4000 }),
    );
    expect(totals.budgetUsed).toBe(1);
    expect(totals.budgetState).toBe("critical");
  });

  // A tenant with no budget set is not a tenant at zero capacity, and drawing it as a full
  // bar would say the opposite of what is true.
  it("declines to draw a bar for an account with no budget rather than dividing by zero", () => {
    const totals = summariseUsage(usage({ daily_token_budget: 0, tokens_last_24h: 500 }));
    expect(totals.budgetUsed).toBeNull();
    expect(totals.budgetState).toBe("unknown");
  });
});
