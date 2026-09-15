import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useTypedAnswer } from "./use-typed-answer";

let reduced = false;
let listeners: Set<() => void>;
beforeEach(() => {
  vi.useFakeTimers();
  reduced = false;
  listeners = new Set();
  vi.stubGlobal("matchMedia", vi.fn(() => ({
    matches: reduced,
    addEventListener: (_: string, listener: () => void) => listeners.add(listener),
    removeEventListener: (_: string, listener: () => void) => listeners.delete(listener),
  })));
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("useTypedAnswer", () => {
  it("reveals words at 30ms and preserves whitespace exactly", () => {
    const text = "One  two\nthree.";
    const { result } = renderHook(() => useTypedAnswer(text, true));
    expect(result.current).toBe("");
    act(() => vi.advanceTimersByTime(30));
    expect(result.current).toBe("One  ");
    act(() => vi.advanceTimersByTime(30));
    expect(result.current).toBe("One  two\n");
    act(() => vi.advanceTimersByTime(30));
    expect(result.current).toBe(text);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("caps a long answer at 1.5 seconds", () => {
    const text = "word ".repeat(1000);
    const { result } = renderHook(() => useTypedAnswer(text, true));
    act(() => vi.advanceTimersByTime(750));
    expect(result.current.length).toBeGreaterThan(0);
    expect(result.current.length).toBeLessThan(text.length);
    act(() => vi.advanceTimersByTime(750));
    expect(result.current).toBe(text);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("continues appended chunks without replaying and resets for a new answer", () => {
    const { result, rerender } = renderHook(({ text }) => useTypedAnswer(text, true), { initialProps: { text: "One two " } });
    act(() => vi.advanceTimersByTime(30));
    expect(result.current).toBe("One ");
    rerender({ text: "One two three four" });
    expect(result.current).toBe("One ");
    act(() => vi.advanceTimersByTime(90));
    expect(result.current).toBe("One two three four");
    rerender({ text: "" });
    expect(result.current).toBe("");
    rerender({ text: "New answer" });
    expect(result.current).toBe("");
    act(() => vi.advanceTimersByTime(60));
    expect(result.current).toBe("New answer");
  });

  it("renders earlier answers and reduced motion instantly", () => {
    const { result, rerender } = renderHook(({ enabled }) => useTypedAnswer("Earlier answer", enabled), { initialProps: { enabled: false } });
    expect(result.current).toBe("Earlier answer");
    act(() => {
      reduced = true;
      listeners.forEach((listener) => listener());
    });
    rerender({ enabled: true });
    expect(result.current).toBe("Earlier answer");
  });

  it("reveals immediately on a motion change and never retypes completed text", () => {
    const { result } = renderHook(() => useTypedAnswer("One two three", true));
    act(() => vi.advanceTimersByTime(30));
    act(() => { reduced = true; listeners.forEach((listener) => listener()); });
    expect(result.current).toBe("One two three");
    act(() => vi.advanceTimersByTime(0));
    act(() => { reduced = false; listeners.forEach((listener) => listener()); });
    expect(result.current).toBe("One two three");
  });

  it("cleans up timers and motion listeners on unmount", () => {
    const { unmount } = renderHook(() => useTypedAnswer("word ".repeat(1000), true));
    unmount();
    expect(vi.getTimerCount()).toBe(0);
    expect(listeners.size).toBe(0);
  });
});
