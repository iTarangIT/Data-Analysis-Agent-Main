"use client";

import { useEffect, useState } from "react";

import { ShimmeringText } from "@/components/ui/shimmering-text";
import { confirmedRejections, STAGE_LABEL } from "@/features/ask/run-process";
import { isRunning, type RunState } from "@/features/ask/run-types";
import { usePrefersReducedMotion } from "@/lib/use-reduced-motion";

/**
 * What the agent is doing right now, while it does it.
 *
 * The label is the real stage from the stream, never a rotating line of filler: a stall on
 * "Running it on IoT database" tells you something a cheerful "Almost there..." would hide.
 * Keyed on the text, so a new stage fades in rather than swapping under the shimmer.
 *
 * Stopping lives on the composer's button, not here, so there is one place to do it.
 */
export function RunStatus({ state }: { state: RunState }) {
  const [now, setNow] = useState(() => Date.now());
  const reduced = usePrefersReducedMotion();
  const live = isRunning(state.phase);
  useEffect(() => {
    if (!live) return;
    const timer = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(timer);
  }, [live, state.startedAt]);
  if (!live) return null;

  const seconds = Math.max(0, Math.floor((now - (state.startedAt ?? now)) / 1000));
  const label = STAGE_LABEL[state.stage ?? "router"];
  const text = `${label}…${confirmedRejections(state) > 0 ? ` · attempt ${state.attempts.length}` : ""}`;

  return (
    <div className="flex min-w-0 items-center gap-2 text-[0.9375rem]">
      <span role="status" title={label} className="min-w-0 truncate">
        {reduced ? (
          <span className="text-ink-muted">{text}</span>
        ) : (
          <ShimmeringText key={text} text={text} startOnView={false} duration={1.8} />
        )}
      </span>
      <span
        className="shrink-0 font-mono text-xs text-ink-faint"
        aria-label={`${seconds} seconds elapsed`}
      >
        ({seconds}s)
      </span>
    </div>
  );
}
