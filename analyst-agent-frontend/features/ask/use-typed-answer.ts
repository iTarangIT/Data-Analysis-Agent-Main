"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";

const QUERY = "(prefers-reduced-motion: reduce)";
function subscribe(callback: () => void) {
  const media = window.matchMedia(QUERY);
  media.addEventListener("change", callback);
  return () => media.removeEventListener("change", callback);
}
const getSnapshot = () => window.matchMedia(QUERY).matches;
const getServerSnapshot = () => true;

/** Presentation only: never changes the answer retained in the run state. */
export function useTypedAnswer(text: string, enabled: boolean): string {
  const reduced = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const [shown, setShown] = useState("");
  const progress = useRef({ source: "", shown: "" });

  useEffect(() => {
    const previous = progress.current;
    const prefix = text.startsWith(previous.source) ? previous.shown : "";
    if (!enabled || reduced) {
      progress.current = { source: text, shown: text };
      const timer = setTimeout(() => setShown(text), 0);
      return () => clearTimeout(timer);
    }
    progress.current = { source: text, shown: prefix };
    if (prefix === text) {
      const timer = setTimeout(() => setShown(text), 0);
      return () => clearTimeout(timer);
    }

    // Keep original whitespace, including line breaks. Batch words on very long answers
    // so a browser frame is the lower bound, rather than thousands of tiny timers.
    const words = text.slice(prefix.length).match(/\s*\S+\s*|\s+/g) ?? [];
    const duration = Math.min(words.length * 30, 1500);
    const start = Date.now();
    const timer = setInterval(() => {
      const count = Math.min(words.length, Math.floor((Date.now() - start) / duration * words.length));
      const value = prefix + words.slice(0, count).join("");
      progress.current = { source: text, shown: value };
      setShown(value);
      if (count === words.length) clearInterval(timer);
    }, 15);
    return () => clearInterval(timer);
  }, [text, enabled, reduced]);

  if (!enabled || reduced) return text;
  return text.startsWith(shown) ? shown : "";
}
