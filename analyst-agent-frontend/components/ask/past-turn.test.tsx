import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { RunSummary } from "@/lib/api/types";
import { PastTurn } from "./past-turn";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const run: RunSummary = {
  id: "r1", thread_id: "t1", question: "How many devices?", status: "done", tool: "sql",
  connection_id: "c1", connection_name: "IoT", rows_returned: 1, duration_ms: 5100,
  created_at: "2026-09-15T00:00:00Z", has_sql: true, has_answer: true,
};

describe("PastTurn", () => {
  it("loads on demand and keeps the saved answer outside its process disclosure", async () => {
    const fetch = vi.fn(async () => Response.json({
      ...run, sql: "SELECT 1", answer: "One device.", error: null,
      prompt_tokens: 100, completion_tokens: 20,
    }));
    vi.stubGlobal("fetch", fetch);
    render(<PastTurn run={run} />);
    expect(fetch).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /How many devices/ }));
    expect(await screen.findByText("One device.")).toBeTruthy();
    const summary = screen.getByRole("button", { name: "Answered in 5.1s" });
    fireEvent.click(summary);
    expect(screen.getByText("SELECT 1")).toBeTruthy();
    expect(screen.queryByRole("list")).toBeNull();
    fireEvent.click(summary);
    expect(screen.queryByText("SELECT 1")).toBeNull();
    expect(screen.getByText("One device.")).toBeTruthy();
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("shows a fetch error and aborts loading when the turn closes", async () => {
    const fetch = vi.fn(async () => new Response(null, { status: 500 }));
    vi.stubGlobal("fetch", fetch);
    render(<PastTurn run={run} />);
    const turn = screen.getByRole("button", { name: /How many devices/ });
    fireEvent.click(turn);
    expect(await screen.findByText("Could not load that run.")).toBeTruthy();
    fireEvent.click(turn);
    await waitFor(() => {
      const init = (fetch.mock.calls as unknown as [string, RequestInit][])[0][1];
      expect(init.signal?.aborted).toBe(true);
    });
  });
});
