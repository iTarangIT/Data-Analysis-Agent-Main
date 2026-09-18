"use client";

import { Check, ChevronDown, ChevronRight } from "lucide-react";
import { Fragment, useId, useState } from "react";
import { RunTimeline } from "@/components/ask/run-timeline";
import { SqlBlock } from "@/components/ask/sql-block";
import {
  answeringAttempt, buildProcessSteps, confirmedRejections, plainSummary, processSummary, rowCount,
  type PlainSummary,
} from "@/features/ask/run-process";
import type { Attempt, RunState } from "@/features/ask/run-types";
import type { RunDetail } from "@/lib/api/types";
import { cn } from "@/lib/utils";

type Props = { state: RunState; detail?: never } | { detail: RunDetail; state?: never };

export function RunProcess({ state, detail }: Props) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const phase = state?.phase ?? detail!.status;
  const duration = state ? state.durationMs ?? 0 : detail!.duration_ms;
  // A live run and a saved one carry the same record. Only a run saved before steps were kept
  // has none, and then nothing is shown in its place rather than something guessed.
  const trace = state ? { stages: state.stageLog, attempts: state.attempts } : detail!.trace;
  const attempts = trace?.attempts ?? [];
  const summary = processSummary(phase, duration, trace ? attempts.length : undefined, confirmedRejections(attempts));
  const steps = trace ? buildProcessSteps(trace.stages, attempts, phase) : [];
  const simple = trace ? plainSummary(attempts, phase) : null;
  const tool = state
    ? state.stageLog.includes("sql_guard") ? "query_database" : null
    : detail!.tool === "sql" ? "query_database" : detail!.tool;
  const rows = state ? state.result?.rows.length : detail!.rows_returned;
  const truncated = state ? state.result?.truncated : answeringAttempt(attempts)?.truncated;
  const accepted = attempts.filter((attempt) => attempt.sql && !attempt.rejected);
  const refused = attempts.filter((attempt) => attempt.sql && attempt.rejected);
  const sql = state?.sql ?? detail?.sql;
  // `contents`, so the toggle and its panel join the message's action row as siblings: the
  // toggle sits beside Copy and Ask again, and the panel wraps onto a full line of its own.
  return (
    <div className="contents">
      <button type="button" aria-expanded={open} aria-controls={id}
        onClick={() => setOpen((value) => !value)}
        className="flex h-8 max-w-full items-center gap-1.5 rounded-lg px-2 text-left text-[0.8125rem] text-ink-muted transition-colors hover:bg-surface-sunk hover:text-ink">
        {phase === "done" ? <Check aria-hidden className="size-3.5 shrink-0 text-success" /> : null}
        <span>{summary}</span>
        <ChevronDown aria-hidden className={cn("size-3.5 shrink-0", open && "rotate-180")} />
      </button>
      {open ? (
        <section id={id} aria-label="How this was answered" className="mt-2 flex min-w-0 basis-full flex-col gap-4 rounded-xl border border-line bg-surface p-4">
          <h3 className="text-xs font-semibold text-ink">How this was answered</h3>
          <RunTimeline steps={steps} />
          {accepted.length ? accepted.map((attempt, index) => (
            <SqlBlock key={index} sql={attempt.sql!} label={accepted.length > 1 ? `Query ${index + 1}` : "Query"} />
          )) : sql ? <SqlBlock sql={sql} /> : <p className="text-xs text-ink-muted">No SQL was recorded.</p>}
          {refused.length ? <RefusedQueries attempts={refused} /> : null}
          <dl className="flex flex-wrap gap-x-6 gap-y-1 text-xs">
            <Fact term="Tool"><span className="font-mono">{tool ?? (state ? "None recorded" : "Not recorded")}</span></Fact>
            <Fact term="Rows">
              {rows === undefined ? "Not available" : rowCount(rows)}
              {truncated === true ? " · cut off" : truncated === false ? " · complete" : ""}
            </Fact>
            <Fact term="Time">{(duration / 1000).toFixed(1)}s</Fact>
            {detail ? <Fact term="Tokens">{detail.prompt_tokens} prompt · {detail.completion_tokens} completion</Fact> : null}
            {detail?.model ? <Fact term="Model"><span className="font-mono">{detail.model}</span></Fact> : null}
          </dl>
          {simple ? <InSimpleTerms summary={simple} /> : null}
        </section>
      ) : null}
    </div>
  );
}

function Fact({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div className="flex min-w-0 gap-2">
      <dt className="text-ink-muted">{term}</dt>
      <dd className="min-w-0 break-words text-ink">{children}</dd>
    </div>
  );
}

/** Closed by default: worth having when something went wrong, noise when nothing did. */
function RefusedQueries({ attempts }: { attempts: Attempt[] }) {
  return (
    <details className="group">
      <summary className="flex w-fit cursor-pointer list-none items-center gap-1.5 rounded-md text-xs text-ink-muted transition-colors hover:text-ink [&::-webkit-details-marker]:hidden">
        <ChevronRight aria-hidden className="size-3.5 shrink-0 group-open:rotate-90" strokeWidth={2} />
        {attempts.length} rejected {attempts.length === 1 ? "query" : "queries"}
      </summary>
      <div className="mt-3 flex flex-col gap-3">
        {attempts.map((attempt, index) => (
          <div key={index} className="flex flex-col gap-1.5">
            <SqlBlock sql={attempt.sql!} label={attempt.at === "database" ? "Failed in the database" : "Rejected"} />
            {attempt.reason ? <p className="text-xs break-words text-ink-muted">Reason: {attempt.reason}</p> : null}
          </div>
        ))}
      </div>
    </details>
  );
}

/** Last, and short, so it is the one part a reader who skips the SQL still gets to. */
function InSimpleTerms({ summary }: { summary: PlainSummary }) {
  const lines = ([["What", summary.what], ["Why", summary.why], ["Means", summary.means]] as const)
    .filter(([, text]) => text);
  return (
    <div className="rounded-lg bg-surface-sunk p-3">
      <h4 className="text-xs font-semibold text-ink">In simple terms</h4>
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-[0.8125rem] leading-5">
        {lines.map(([term, text]) => (
          <Fragment key={term}>
            <dt className="text-ink-muted">{term}</dt>
            <dd className="min-w-0 text-ink">{text}</dd>
          </Fragment>
        ))}
      </dl>
    </div>
  );
}
