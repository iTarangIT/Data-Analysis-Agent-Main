"use client";

import { useCallback, useEffect, useRef } from "react";

export const BOTTOM_THRESHOLD = 48;
export function isNearBottom(element: Pick<HTMLElement, "scrollHeight" | "clientHeight" | "scrollTop">): boolean {
  return element.scrollHeight - element.clientHeight - element.scrollTop <= BOTTOM_THRESHOLD;
}

export function useTranscriptScroll() {
  const viewportRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const following = useRef(true);
  const lastScrollTop = useRef(0);
  const frame = useRef<number | null>(null);

  const followBottom = useCallback(() => {
    if (frame.current !== null) cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(() => {
      frame.current = null;
      const viewport = viewportRef.current;
      if (viewport && following.current) {
        viewport.scrollTop = viewport.scrollHeight;
        lastScrollTop.current = viewport.scrollTop;
      }
    });
  }, []);

  const onSubmit = useCallback(() => {
    following.current = true;
    followBottom();
  }, [followBottom]);

  useEffect(() => {
    const viewport = viewportRef.current;
    const content = contentRef.current;
    if (!viewport || !content) return;
    lastScrollTop.current = viewport.scrollTop;
    const onScroll = () => {
      // A programmatic scroll event may arrive after the next batch of words has
      // increased the height. That distance alone does not mean the reader scrolled up.
      if (isNearBottom(viewport)) following.current = true;
      else if (viewport.scrollTop < lastScrollTop.current) following.current = false;
      lastScrollTop.current = viewport.scrollTop;
    };
    viewport.addEventListener("scroll", onScroll, { passive: true });
    const observer = new ResizeObserver(followBottom);
    observer.observe(content);
    observer.observe(viewport);
    return () => {
      viewport.removeEventListener("scroll", onScroll);
      observer.disconnect();
      if (frame.current !== null) cancelAnimationFrame(frame.current);
    };
  }, [followBottom]);

  return { viewportRef, contentRef, onSubmit };
}
