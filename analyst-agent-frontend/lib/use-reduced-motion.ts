"use client";

import { useSyncExternalStore } from "react";

const QUERY = "(prefers-reduced-motion: reduce)";

// Absent in jsdom and some embedded webviews. No preference is the honest reading of that.
const supported = () => typeof window.matchMedia === "function";

function subscribe(callback: () => void) {
  if (!supported()) return () => {};
  const media = window.matchMedia(QUERY);
  media.addEventListener("change", callback);
  return () => media.removeEventListener("change", callback);
}

const getSnapshot = () => supported() && window.matchMedia(QUERY).matches;
// The server cannot know, so it assumes the quiet version. The client corrects it on hydration.
const getServerSnapshot = () => true;

/**
 * Whether the reader has asked their OS for less motion.
 *
 * The CSS rule in globals.css only reaches CSS animations. The typed answer, the shimmer and
 * the orb are all driven from JavaScript, so each of them asks here instead.
 */
export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
