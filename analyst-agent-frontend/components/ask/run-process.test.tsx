import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { IDLE_RUN, type RunState } from "@/features/ask/run-types";
import type { RunDetail } from "@/lib/api/types";
import { RunProcess } from "./run-process";

afterEach(cleanup);
const state: RunState = {
  ...IDLE_RUN, phase: "done", durationMs: 5100,
  stageLog: ["router", "sql_gen", "sql_guard", "db_exec", "answer"],
  attempts: [{ sql: "SELECT 1", rejected: false, what: "Counts dealers.", why: "You asked how many.", rows: 1, truncated: true, ms: 40 }],
  sql: "SELECT 1",
  result: { columns: ["count"], rows: [[1]], truncated: true },
};
const saved: RunDetail = {
  id: "saved", connection_id: "c1", thread_id: "t1", question: "Count?",
  status: "done", tool: "sql", sql: "SELECT 1", answer: "One.", error: null,
  model: null, prompt_tokens: 100, completion_tokens: 20, rows_returned: 1,
  chart: null, trace: null, duration_ms: 5100, created_at: "2026-09-15T00:00:00Z",
};
const simpleTerms = () => screen.queryByRole("heading", { name: "In simple terms" });

describe("RunProcess", () => {
  it("starts collapsed and exposes steps, SQL, tool, row count, truncation and time", () => {
    render(<RunProcess state={state} />);
    expect(screen.queryByRole("region")).toBeNull();
    const button = screen.getByRole("button", { name: "Answered in 5.1s · 1 query" });
    expect(button.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(button);
    expect(button.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("region").id).toBe(button.getAttribute("aria-controls"));
    const steps = within(screen.getByRole("list", { name: "Run steps" })).getAllByRole("listitem");
    expect(steps).toHaveLength(5);
    expect(steps[3].textContent).toBe("Running it on your data · cut off at 1 row · 40 ms");
    expect(screen.getByText("query_database")).toBeTruthy();
    expect(screen.getByText("SELECT 1")).toBeTruthy();
    expect(screen.getByText("1 row · cut off")).toBeTruthy();
    expect(screen.getByText("5.1s")).toBeTruthy();
    fireEvent.click(button);
    expect(screen.queryByRole("region")).toBeNull();
  });

  it("ends with a plain-English summary of what was done, why, and what it means", () => {
    render(<RunProcess state={state} />);
    fireEvent.click(screen.getByRole("button"));
    expect(simpleTerms()).toBeTruthy();
    expect(screen.getByText("Counts dealers.")).toBeTruthy();
    expect(screen.getByText("You asked how many.")).toBeTruthy();
    expect(screen.getByText("This found more than 1 results, so the answer only uses the first 1.")).toBeTruthy();
  });

  it("renders a run saved before steps were kept without fabricated steps, counts or summary", () => {
    render(<RunProcess detail={saved} />);
    fireEvent.click(screen.getByRole("button", { name: "Answered in 5.1s" }));
    expect(screen.queryByRole("list")).toBeNull();
    expect(screen.getByText("query_database")).toBeTruthy();
    expect(screen.getByText("1 row")).toBeTruthy();
    expect(screen.getByText("100 prompt · 20 completion")).toBeTruthy();
    expect(simpleTerms()).toBeNull();
  });

  it("replays a saved run's steps and summary from its trace", () => {
    render(<RunProcess detail={{ ...saved, model: "gemini-3-flash", trace: { stages: state.stageLog, attempts: [{ ...state.attempts[0], truncated: false }] } }} />);
    fireEvent.click(screen.getByRole("button", { name: "Answered in 5.1s · 1 query" }));
    expect(within(screen.getByRole("list", { name: "Run steps" })).getAllByRole("listitem")).toHaveLength(5);
    expect(screen.getByText("1 row · complete")).toBeTruthy();
    expect(screen.getByText("gemini-3-flash")).toBeTruthy();
    expect(screen.getByText("The answer uses everything this found; nothing was left out.")).toBeTruthy();
  });

  it("keeps a rejected query and its reason behind a closed disclosure", () => {
    const refused = { sql: "DELETE FROM dealers", rejected: true, reason: "only SELECT is allowed", at: "guard" as const };
    render(<RunProcess state={{ ...state, stageLog: ["router", "sql_gen", "sql_guard", ...state.stageLog.slice(1)], attempts: [refused, ...state.attempts] }} />);
    fireEvent.click(screen.getByRole("button", { name: /2 queries, 1 rejected/ }));
    const disclosure = screen.getByText("1 rejected query").closest("details")!;
    expect(disclosure.open).toBe(false);
    expect(within(disclosure).getByText("DELETE FROM dealers")).toBeTruthy();
    expect(within(disclosure).getByText("Reason: only SELECT is allowed")).toBeTruthy();
    expect(screen.getByText("SELECT 1").closest("details")).toBeNull();
    expect(screen.getByText("Counts dealers.")).toBeTruthy();
  });
});
