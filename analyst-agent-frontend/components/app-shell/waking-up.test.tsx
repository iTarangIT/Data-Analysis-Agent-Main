import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WakingUp } from "./waking-up";

const refresh = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

const fetchMock = vi.fn();

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  fetchMock.mockReset();
  refresh.mockReset();
});

const answer = (ok: boolean) => Promise.resolve({ ok } as Response);

describe("WakingUp", () => {
  it("says the service is starting, not that anything is missing", async () => {
    fetchMock.mockReturnValue(answer(false));
    render(<WakingUp />);
    await act(async () => {});

    expect(screen.getByRole("heading", { name: /starting/i })).toBeTruthy();
  });

  it("keeps asking until the agent answers, then reloads the page's data", async () => {
    fetchMock
      .mockReturnValueOnce(answer(false))
      .mockReturnValueOnce(answer(false))
      .mockReturnValue(answer(true));
    render(<WakingUp />);

    await act(async () => {});
    expect(refresh).not.toHaveBeenCalled();

    await act(async () => vi.advanceTimersByTimeAsync(3_000));
    expect(refresh).not.toHaveBeenCalled();

    await act(async () => vi.advanceTimersByTimeAsync(3_000));
    expect(refresh).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledWith("/api/health", expect.anything());
  });

  it("admits it is taking too long rather than spinning in silence", async () => {
    fetchMock.mockReturnValue(answer(false));
    render(<WakingUp />);
    await act(async () => {});
    expect(screen.queryByText(/longer than usual/i)).toBeNull();

    await act(async () => vi.advanceTimersByTimeAsync(180_000));
    expect(screen.getByText(/longer than usual/i)).toBeTruthy();
  });

  it("stops asking once it is gone", async () => {
    fetchMock.mockReturnValue(answer(false));
    const { unmount } = render(<WakingUp />);
    await act(async () => {});
    unmount();

    await act(async () => vi.advanceTimersByTimeAsync(30_000));
    expect(fetchMock).toHaveBeenCalledOnce();
  });
});
