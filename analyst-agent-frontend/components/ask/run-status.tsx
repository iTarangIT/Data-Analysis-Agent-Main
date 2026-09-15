"use client";

import { useEffect, useState } from "react";
import { confirmedRejections, STAGE_LABEL } from "@/features/ask/run-process";
import { isRunning, type RunState } from "@/features/ask/run-types";

export function RunStatus({ state, onCancel }: { state: RunState; onCancel?: () => void }) {
  const [now, setNow] = useState(() => Date.now());
  const live = isRunning(state.phase);
  useEffect(() => {
    if (!live) return;
    const timer = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(timer);
  }, [live, state.startedAt]);
  if (!live) return null;
  const seconds = Math.max(0, Math.floor((now - (state.startedAt ?? now)) / 1000));
  return (
    <div className="flex min-w-0 items-center gap-2 text-[0.8125rem] sm:gap-3">
      <span aria-hidden className="is-live inline-block shrink-0 text-xl leading-none text-brand">✻</span>
      <span role="status" title={STAGE_LABEL[state.stage ?? "router"]} className="min-w-0 truncate text-ink-muted">
        {STAGE_LABEL[state.stage ?? "router"]}…
        {confirmedRejections(state) > 0 ? ` · attempt ${state.attempts.length}` : ""}
      </span>
      <span className="shrink-0 font-mono text-xs text-ink-faint" aria-label={`${seconds} seconds elapsed`}>({seconds}s)</span>
      {onCancel ? <button type="button" onClick={onCancel} className="shrink-0 text-xs font-medium text-fault underline-offset-4 hover:underline">Cancel</button> : null}
    </div>
  );
}
