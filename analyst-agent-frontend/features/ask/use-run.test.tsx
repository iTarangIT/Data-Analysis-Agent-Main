import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useRun } from "./use-run";

/**
 * The archive, which is the only behaviour this hook gained. The reducer is covered on its
 * own in run-machine.test.ts and is untouched by any of this.
 */

/** A response whose body ends without a terminal frame, so a run settles as truncated. */
function emptyStream(): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(": open\n\n"));
      controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => emptyStream()),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function ask(result: { current: ReturnType<typeof useRun> }, question: string) {
  await act(async () => {
    await result.current.ask({ connectionId: "c1", question, threadId: "t1" });
  });
}

describe("useRun archive", () => {
  it("starts with nothing behind it", () => {
    const { result } = renderHook(() => useRun());
    expect(result.current.turns).toEqual([]);
    expect(result.current.state.phase).toBe("idle");
  });

  it("does not archive the idle state when the first question is asked", async () => {
    const { result } = renderHook(() => useRun());
    await ask(result, "first");
    expect(result.current.turns).toEqual([]);
    expect(result.current.state.question).toBe("first");
  });

  it("keeps the previous question on screen when a follow-up is asked", async () => {
    const { result } = renderHook(() => useRun());
    await ask(result, "first");
    await ask(result, "second");

    await waitFor(() => expect(result.current.turns).toHaveLength(1));
    expect(result.current.turns[0].question).toBe("first");
    expect(result.current.state.question).toBe("second");
  });

  it("archives a run that ended badly rather than dropping it", async () => {
    const { result } = renderHook(() => useRun());
    await ask(result, "first");
    // The stream closed with no terminal frame, so the machine settled as an error.
    expect(result.current.state.phase).toBe("error");

    await ask(result, "second");
    await waitFor(() => expect(result.current.turns).toHaveLength(1));
    expect(result.current.turns[0].phase).toBe("error");
  });

  it("accumulates rather than replacing", async () => {
    const { result } = renderHook(() => useRun());
    await ask(result, "one");
    await ask(result, "two");
    await ask(result, "three");

    await waitFor(() => expect(result.current.turns).toHaveLength(2));
    expect(result.current.turns.map((t) => t.question)).toEqual(["one", "two"]);
  });

  it("clears the archive when the transcript is reset", async () => {
    const { result } = renderHook(() => useRun());
    await ask(result, "first");
    await ask(result, "second");
    await waitFor(() => expect(result.current.turns).toHaveLength(1));

    act(() => result.current.reset());

    expect(result.current.turns).toEqual([]);
    expect(result.current.state.phase).toBe("idle");
  });
});
