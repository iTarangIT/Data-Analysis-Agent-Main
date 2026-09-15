import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { IDLE_RUN, type RunState } from "@/features/ask/run-types";
import type { RunDetail } from "@/lib/api/types";
import { RunProcess } from "./run-process";

afterEach(cleanup);
const state: RunState = {
  ...IDLE_RUN, phase: "done", durationMs: 5100,
  stageLog: ["router", "sql_gen", "sql_guard", "db_exec", "answer"],
  attempts: [{ sql: "SELECT 1", rejected: false }], sql: "SELECT 1",
  result: { columns: ["count"], rows: [[1]], truncated: true },
};

describe("RunProcess", () => {
  it("starts collapsed and exposes steps, SQL, tool, row count, truncation and time", () => {
    render(<RunProcess state={state} />);
    expect(screen.queryByRole("region")).toBeNull();
    const button = screen.getByRole("button", { name: "Answered in 5.1s · 1 query" });
    expect(button.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(button);
    expect(button.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("region").id).toBe(button.getAttribute("aria-controls"));
    expect(screen.getAllByRole("listitem")).toHaveLength(5);
    expect(screen.getByText("query_database")).toBeTruthy();
    expect(screen.getByText("SELECT 1")).toBeTruthy();
    expect(screen.getByText("1 row returned · Result cut off")).toBeTruthy();
    expect(screen.getByText("Total time: 5.1s")).toBeTruthy();
    fireEvent.click(button);
    expect(screen.queryByRole("region")).toBeNull();
  });

  it("renders saved facts without fabricated steps, retry counts or truncation", () => {
    const detail: RunDetail = {
      id: "saved", connection_id: "c1", thread_id: "t1", question: "Count?",
      status: "done", tool: "sql", sql: "SELECT 1", answer: "One.", error: null,
      model: null, prompt_tokens: 100, completion_tokens: 20, rows_returned: 1,
      chart: null, duration_ms: 5100, created_at: "2026-09-15T00:00:00Z",
    };
    render(<RunProcess detail={detail} />);
    fireEvent.click(screen.getByRole("button", { name: "Answered in 5.1s" }));
    expect(screen.queryByRole("list")).toBeNull();
    expect(screen.getByText("query_database")).toBeTruthy();
    expect(screen.getByText("1 row returned · Truncation not recorded")).toBeTruthy();
    expect(screen.getByText("Tokens: 100 prompt · 20 completion")).toBeTruthy();
  });

  it("shows unavailable rejected SQL and preserves the successful SQL", () => {
    render(<RunProcess state={{ ...state, attempts: [{ sql: null, rejected: true }, ...state.attempts] }} />);
    fireEvent.click(screen.getByRole("button", { name: /2 queries, 1 rejected/ }));
    expect(screen.getByText("Rejected SQL text is not available in the stream.")).toBeTruthy();
    expect(screen.getByText("SELECT 1")).toBeTruthy();
  });
});
