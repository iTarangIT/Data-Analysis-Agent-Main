"use client";

import { Check, ChevronDown } from "lucide-react";
import { useId, useState } from "react";
import { RunTimeline } from "@/components/ask/run-timeline";
import { SqlBlock } from "@/components/ask/sql-block";
import { confirmedRejections, processSummary } from "@/features/ask/run-process";
import type { RunState } from "@/features/ask/run-types";
import type { RunDetail } from "@/lib/api/types";
import { cn } from "@/lib/utils";

type Props = { state: RunState; detail?: never } | { detail: RunDetail; state?: never };

export function RunProcess({ state, detail }: Props) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const phase = state?.phase ?? detail!.status;
  const duration = state ? state.durationMs ?? 0 : detail!.duration_ms;
  const rejected = state ? confirmedRejections(state) : 0;
  const summary = processSummary(phase, duration, state?.attempts.length, rejected);
  const tool = state
    ? state.stageLog.includes("sql_guard") ? "query_database" : null
    : detail!.tool === "sql" ? "query_database" : detail!.tool;
  const rows = state ? state.result?.rows.length : detail!.rows_returned;
  const sql = state?.sql ?? detail?.sql;
  const queries = state?.attempts.filter((attempt) => attempt.sql) ?? [];
  return (
    <div className="min-w-0">
      <button type="button" aria-expanded={open} aria-controls={id}
        onClick={() => setOpen((value) => !value)}
        className="flex max-w-full items-center gap-2 text-left text-[0.8125rem] text-ink-muted hover:text-ink">
        {phase === "done" ? <Check aria-hidden className="size-3.5 shrink-0 text-success" /> : null}
        <span>{summary}</span>
        <ChevronDown aria-hidden className={cn("size-3.5 shrink-0", open && "rotate-180")} />
      </button>
      {open ? (
        <section id={id} aria-label="How this was answered" className="mt-3 flex min-w-0 flex-col gap-3 rounded-lg border border-line bg-surface p-4">
          <h3 className="text-xs font-semibold text-ink">How this was answered</h3>
          {state ? <RunTimeline state={state} /> : null}
          <p className="text-xs text-ink-muted">Tool: <span className="font-mono">{tool ?? (state ? "None recorded" : "Not recorded")}</span></p>
          {queries.length ? queries.map((query, index) => <SqlBlock key={index} sql={query.sql!} />)
            : sql ? <SqlBlock sql={sql} /> : <p className="text-xs text-ink-muted">No SQL was recorded.</p>}
          {rejected > 0 ? <p className="text-xs text-ink-muted">Rejected SQL text is not available in the stream.</p> : null}
          <p className="text-xs text-ink-muted">
            {rows === undefined ? "Rows: not available" : `${rows} ${rows === 1 ? "row" : "rows"} returned`}
            {state?.result ? ` · ${state.result.truncated ? "Result cut off" : "Result not cut off"}` : detail ? " · Truncation not recorded" : ""}
          </p>
          <p className="text-xs text-ink-muted">Total time: {(duration / 1000).toFixed(1)}s</p>
          {detail ? <p className="text-xs text-ink-muted">Tokens: {detail.prompt_tokens} prompt · {detail.completion_tokens} completion</p> : null}
        </section>
      ) : null}
    </div>
  );
}
