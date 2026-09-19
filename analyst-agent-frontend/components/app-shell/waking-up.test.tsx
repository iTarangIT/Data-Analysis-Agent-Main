import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WakingUp } from "./waking-up";

const refresh = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

const WAKE_URL = "https://agent.example.com/health";

// The app's own check answers from this queue, then keeps giving its last answer. The wake
// request never settles, as the host holds it until the agent is up.
let answers: boolean[] = [];
const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>((url) => {
  if (url === WAKE_URL) return new Promise<Response>(() => {});
  const ok = answers.length > 1 ? answers.shift()! : (answers[0] ?? false);
  return Promise.resolve({ ok } as Response);
});
const healthChecks = () => fetchMock.mock.calls.filter(([url]) => url === "/api/health");
const wakeCalls = () => fetchMock.mock.calls.filter(([url]) => url === WAKE_URL);

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("fetch", fetchMock);
  answers = [false];
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  fetchMock.mockClear();
  refresh.mockReset();
});

describe("WakingUp", () => {
  it("says the service is starting, not that anything is missing", async () => {
    render(<WakingUp wakeUrl={WAKE_URL} />);
    await act(async () => {});

    expect(screen.getByRole("heading", { name: /starting/i })).toBeTruthy();
  });

  // Render starts a sleeping free service only for a request from outside Render. The app's
  // own check comes from its server, on Render, and was turned away in 0.4 s for minutes on
  // end; one request from outside woke the agent at once.
  it("wakes the agent from the browser, which the host will start it for", async () => {
    render(<WakingUp wakeUrl={WAKE_URL} />);
    await act(async () => {});

    expect(wakeCalls()).toHaveLength(1);
    expect(wakeCalls()[0][1]).toMatchObject({ mode: "no-cors" });
  });

  it("keeps a single wake request in flight however many checks fail", async () => {
    render(<WakingUp wakeUrl={WAKE_URL} />);
    await act(async () => vi.advanceTimersByTimeAsync(30_000));

    expect(healthChecks().length).toBeGreaterThan(5);
    expect(wakeCalls()).toHaveLength(1);
  });

  it("keeps asking until the agent answers, then reloads the page's data", async () => {
    answers = [false, false, true];
    render(<WakingUp wakeUrl={WAKE_URL} />);

    await act(async () => {});
    expect(refresh).not.toHaveBeenCalled();

    await act(async () => vi.advanceTimersByTimeAsync(3_000));
    expect(refresh).not.toHaveBeenCalled();

    await act(async () => vi.advanceTimersByTimeAsync(3_000));
    expect(refresh).toHaveBeenCalledOnce();
    expect(healthChecks()).toHaveLength(3);
  });

  it("admits it is taking too long rather than spinning in silence", async () => {
    render(<WakingUp wakeUrl={WAKE_URL} />);
    await act(async () => {});
    expect(screen.queryByText(/longer than usual/i)).toBeNull();

    await act(async () => vi.advanceTimersByTimeAsync(180_000));
    expect(screen.getByText(/longer than usual/i)).toBeTruthy();
  });

  it("stops asking once it is gone", async () => {
    const { unmount } = render(<WakingUp wakeUrl={WAKE_URL} />);
    await act(async () => {});
    unmount();
    const asked = fetchMock.mock.calls.length;

    await act(async () => vi.advanceTimersByTimeAsync(30_000));
    expect(fetchMock.mock.calls.length).toBe(asked);
  });
});
