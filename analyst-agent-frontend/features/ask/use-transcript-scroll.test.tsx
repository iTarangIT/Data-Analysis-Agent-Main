import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { isNearBottom, useTranscriptScroll } from "./use-transcript-scroll";

let resize: () => void;
const disconnect = vi.fn();
beforeEach(() => {
  vi.useFakeTimers();
  disconnect.mockClear();
  vi.stubGlobal("ResizeObserver", class {
    constructor(callback: () => void) { resize = callback; }
    observe() {}
    disconnect = disconnect;
  });
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => setTimeout(() => callback(0), 16));
  vi.stubGlobal("cancelAnimationFrame", clearTimeout);
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });

function Transcript() {
  const { viewportRef, contentRef, onSubmit } = useTranscriptScroll();
  return <><button onClick={onSubmit}>Send</button><div data-testid="viewport" ref={viewportRef}><div ref={contentRef}>Transcript</div></div></>;
}
function setup() {
  const rendered = render(<Transcript />);
  const viewport = screen.getByTestId("viewport");
  let height = 1000;
  let top = 500;
  Object.defineProperties(viewport, {
    scrollHeight: { get: () => height },
    clientHeight: { get: () => 500 },
    scrollTop: { get: () => top, set: (value: number) => { top = Math.max(0, Math.min(value, height - 500)); } },
  });
  fireEvent.scroll(viewport);
  const grow = (beforeResize?: () => void) => {
    height += 200;
    beforeResize?.();
    act(() => { resize(); vi.advanceTimersByTime(16); });
  };
  return { ...rendered, viewport, grow };
}

describe("transcript following", () => {
  it("uses a 48px bottom threshold", () => {
    expect(isNearBottom({ scrollHeight: 1000, clientHeight: 500, scrollTop: 452 })).toBe(true);
    expect(isNearBottom({ scrollHeight: 1000, clientHeight: 500, scrollTop: 451 })).toBe(false);
  });

  it("follows content growth, pauses on scroll-up, resumes near the bottom", () => {
    const { viewport, grow } = setup();
    grow();
    expect(viewport.scrollTop).toBe(700);
    viewport.scrollTop = 100;
    fireEvent.scroll(viewport);
    grow();
    expect(viewport.scrollTop).toBe(100);
    viewport.scrollTop = 880;
    fireEvent.scroll(viewport);
    grow();
    expect(viewport.scrollTop).toBe(1100);
  });

  it("forces following after submission even when reading an earlier turn", () => {
    const { viewport, grow } = setup();
    viewport.scrollTop = 0;
    fireEvent.scroll(viewport);
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    grow();
    expect(viewport.scrollTop).toBe(700);
  });

  it("does not pull the reader down if they scroll up before a scheduled follow", () => {
    const { viewport } = setup();
    act(() => resize());
    viewport.scrollTop = 0;
    fireEvent.scroll(viewport);
    act(() => vi.advanceTimersByTime(16));
    expect(viewport.scrollTop).toBe(0);
  });

  it("keeps following when a programmatic scroll event arrives after content grows", () => {
    const { viewport, grow } = setup();
    grow();
    // A late scroll event at the same position must not be mistaken for scrolling up.
    grow(() => fireEvent.scroll(viewport));
    expect(viewport.scrollTop).toBe(900);
  });

  it("cleans up the observer and scheduled frame", () => {
    const { unmount } = setup();
    act(() => resize());
    unmount();
    expect(disconnect).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });
});
