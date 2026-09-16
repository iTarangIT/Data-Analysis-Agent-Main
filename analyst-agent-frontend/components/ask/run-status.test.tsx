import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { IDLE_RUN, type RunState, type Stage } from "@/features/ask/run-types";
import { RunStatus } from "./run-status";

// The shimmer asks whether it is on screen, and jsdom has no IntersectionObserver to answer.
class NeverIntersects { observe() {} unobserve() {} disconnect() {} takeRecords() { return []; } }

beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(1000); vi.stubGlobal("IntersectionObserver", NeverIntersects); });
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });
const state: RunState = { ...IDLE_RUN, phase: "connecting", startedAt: 1000 };

describe("RunStatus", () => {
  it.each<[Stage | null, string]>([
    [null, "Reading your question"], ["router", "Reading your question"],
    ["sql_gen", "Writing the query"], ["sql_guard", "Checking the query is read-only"],
    ["db_exec", "Running it on IoT database"], ["answer", "Writing the answer"],
  ])("labels %s", (stage, label) => {
    render(<RunStatus state={{ ...state, stage }} />);
    expect(screen.getByRole("status").textContent).toBe(`${label}…`);
  });

  it("counts total seconds and cleans up on completion", () => {
    const { rerender } = render(<RunStatus state={state} />);
    expect(screen.getByText("(0s)")).toBeTruthy();
    act(() => vi.advanceTimersByTime(3250));
    rerender(<RunStatus state={{ ...state, stage: "sql_gen" }} />);
    expect(screen.getByText("(3s)")).toBeTruthy();
    // Stopping moved to the composer's button; the status line only reports.
    expect(screen.queryByRole("button")).toBeNull();
    rerender(<RunStatus state={{ ...state, phase: "done" }} />);
    expect(screen.queryByRole("status")).toBeNull();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("only labels attempt 2 after a pending guard actually retries", () => {
    const checking: RunState = { ...state, stage: "sql_guard", attempts: [{ sql: null, rejected: true }] };
    const { rerender } = render(<RunStatus state={checking} />);
    expect(screen.getByRole("status").textContent).not.toContain("attempt");
    rerender(<RunStatus state={{ ...checking, stage: "sql_gen", attempts: [...checking.attempts, { sql: null, rejected: false }] }} />);
    expect(screen.getByRole("status").textContent).toBe("Writing the query… · attempt 2");
  });
});
