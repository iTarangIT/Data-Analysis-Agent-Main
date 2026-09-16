import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RunSummary } from "@/lib/api/types";
import { PastTurn } from "./past-turn";

/** An IntersectionObserver the test drives by hand, since jsdom has none. */
let observers: { callback: IntersectionObserverCallback; target: Element | null; disconnected: boolean }[] = [];
class ManualObserver {
  entry: (typeof observers)[number];
  constructor(callback: IntersectionObserverCallback) {
    this.entry = { callback, target: null, disconnected: false };
    observers.push(this.entry);
  }
  observe(target: Element) { this.entry.target = target; }
  unobserve() {}
  disconnect() { this.entry.disconnected = true; }
  takeRecords() { return []; }
}
function scrollIntoView() {
  act(() => {
    for (const o of observers) {
      if (o.disconnected || !o.target) continue;
      o.callback([{ isIntersecting: true, target: o.target } as IntersectionObserverEntry], {} as IntersectionObserver);
    }
  });
}

beforeEach(() => { observers = []; vi.stubGlobal("IntersectionObserver", ManualObserver); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const run: RunSummary = {
  id: "r1", thread_id: "t1", question: "How many devices?", status: "done", tool: "sql",
  connection_id: "c1", connection_name: "IoT", rows_returned: 1, duration_ms: 5100,
  created_at: "2026-09-15T00:00:00Z", has_sql: true, has_answer: true,
};
const saved = { ...run, sql: "SELECT 1", answer: "One device.", error: null, prompt_tokens: 100, completion_tokens: 20 };

describe("PastTurn", () => {
  it("shows the question at once, and fetches the answer only once it scrolls into view", async () => {
    const fetch = vi.fn(async () => Response.json(saved));
    vi.stubGlobal("fetch", fetch);
    render(<PastTurn run={run} latest={false} />);
    expect(screen.getByText("How many devices?")).toBeTruthy();
    expect(fetch).not.toHaveBeenCalled();

    scrollIntoView();
    expect(await screen.findByText("One device.")).toBeTruthy();
    expect(fetch).toHaveBeenCalledOnce();

    // The run's details stay behind their own toggle, and the answer stays outside it.
    const summary = screen.getByRole("button", { name: "Answered in 5.1s" });
    fireEvent.click(summary);
    expect(screen.getByText("SELECT 1")).toBeTruthy();
    expect(screen.queryByRole("list")).toBeNull();
    fireEvent.click(summary);
    expect(screen.queryByText("SELECT 1")).toBeNull();
    expect(screen.getByText("One device.")).toBeTruthy();

    // Scrolling past it again does not fetch it again.
    scrollIntoView();
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("offers to ask the same question again", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json(saved)));
    const onAskAgain = vi.fn();
    render(<PastTurn run={run} latest onAskAgain={onAskAgain} />);
    scrollIntoView();
    await screen.findByText("One device.");
    fireEvent.click(screen.getByRole("button", { name: "Ask again" }));
    expect(onAskAgain).toHaveBeenCalledOnce();
  });

  it("names a failed load, and abandons the request when the turn goes away", async () => {
    const fetch = vi.fn(async () => new Response(null, { status: 500 }));
    vi.stubGlobal("fetch", fetch);
    const first = render(<PastTurn run={run} latest={false} />);
    scrollIntoView();
    expect(await screen.findByText("Could not load that answer.")).toBeTruthy();
    first.unmount();

    const pending = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(() => new Promise(() => {}));
    vi.stubGlobal("fetch", pending);
    const second = render(<PastTurn run={run} latest={false} />);
    scrollIntoView();
    second.unmount();
    await waitFor(() => {
      expect(pending.mock.calls[0][1]?.signal?.aborted).toBe(true);
    });
  });
});
