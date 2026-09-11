"use client";

import { useState, useTransition } from "react";

import { Eyebrow, Panel } from "@/components/panel";
import { summariseUsage } from "@/features/ask/usage";
import type { Usage } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/**
 * What the organisation has spent.
 *
 * Every figure comes from the agent's `/usage` aggregate, so these cover the account rather
 * than whichever page of runs happens to be loaded. The window is the reader's to change.
 *
 * The capacity bar reads `tokens_last_24h`, a rolling window, because that is the number the
 * agent compares against the ceiling when it refuses a run. Summing the latest calendar-day
 * bucket instead would draw a bar that disagrees with the error people actually hit.
 */

const WINDOWS = [30, 90] as const;

export function RunUsage({ initial }: { initial: Usage }) {
  const [usage, setUsage] = useState(initial);
  const [days, setDays] = useState<number>(30);
  const [pending, startTransition] = useTransition();

  const totals = summariseUsage(usage);

  function choose(next: number) {
    if (next === days) return;
    setDays(next);
    startTransition(async () => {
      const response = await fetch(`/api/usage?days=${next}`);
      if (response.ok) setUsage((await response.json()) as Usage);
    });
  }

  return (
    <section className="flex flex-col gap-4">
      <dl className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Figure label="Total runs" value={totals.runs.toLocaleString()} />
        <Figure label="Data tokens" value={compact(totals.tokens)} />
        <Figure label="Rows processed" value={compact(totals.rowsReturned)} />
        <Figure
          label="Errors"
          value={totals.errors.toLocaleString()}
          tone={totals.errors > 0 ? "fault" : undefined}
        />
      </dl>

      <div className="grid gap-4 lg:grid-cols-[1.8fr_1fr]">
        <Panel className="flex min-w-0 flex-col p-5">
          <div className="flex items-center justify-between gap-3">
            <Eyebrow>Consumption trend</Eyebrow>
            <div className="flex shrink-0 items-center gap-1 rounded-md bg-surface-sunk p-0.5">
              {WINDOWS.map((window) => (
                <button
                  key={window}
                  type="button"
                  onClick={() => choose(window)}
                  aria-pressed={days === window}
                  className={cn(
                    "rounded-[0.3125rem] px-2 py-1 font-mono text-[0.6875rem] transition-colors",
                    days === window
                      ? "bg-surface text-ink shadow-sm"
                      : "text-ink-muted hover:text-ink",
                  )}
                >
                  {window}D
                </button>
              ))}
            </div>
          </div>

          <div className={cn("mt-5 flex-1 transition-opacity", pending && "opacity-50")}>
            <Bars usage={usage} peak={totals.peakRuns} />
          </div>
        </Panel>

        <Budget usage={usage} totals={totals} />
      </div>
    </section>
  );
}

/**
 * Thousands and millions, because a token count runs to eight digits and the exact figure
 * is never the point. The full number stays in the title attribute.
 */
function compact(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 10_000) return `${Math.round(value / 1000).toLocaleString()}k`;
  return value.toLocaleString();
}

function Figure({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "fault";
}) {
  return (
    <Panel className="p-5">
      <dt>
        <Eyebrow>{label}</Eyebrow>
      </dt>
      <dd
        className={cn(
          "mt-2 font-mono text-2xl tabular-nums",
          tone === "fault" ? "text-fault" : "text-ink",
        )}
      >
        {value}
      </dd>
    </Panel>
  );
}

/**
 * Runs per day. Bars rather than a line, because these are counts of discrete things on
 * discrete days and a line would imply a value existed between them.
 */
function Bars({ usage, peak }: { usage: Usage; peak: number }) {
  const days = usage.days;

  if (days.length === 0) {
    return (
      <p className="py-8 text-center text-[0.875rem] text-ink-muted">
        Nothing has run in this window.
      </p>
    );
  }

  const ceiling = Math.max(peak, 1);

  return (
    <figure className="m-0">
      <div
        className="flex h-40 items-end gap-px"
        role="img"
        aria-label={`Runs per day across ${days.length} days, peaking at ${peak}.`}
      >
        {days.map((day) => (
          <div
            key={day.day}
            title={`${day.day}: ${day.runs} run${day.runs === 1 ? "" : "s"}`}
            style={{ height: `${Math.max((day.runs / ceiling) * 100, day.runs > 0 ? 3 : 1.5)}%` }}
            className={cn(
              "min-w-0 flex-1 rounded-t-[2px]",
              day.runs === 0
                ? "bg-line"
                : day.runs === peak
                  ? "bg-brand"
                  : "bg-series-3",
            )}
          />
        ))}
      </div>

      <figcaption className="mt-2 flex justify-between font-mono text-[0.6875rem] text-ink-muted">
        <span>{days[0].day}</span>
        <span>{days[days.length - 1].day}</span>
      </figcaption>
    </figure>
  );
}

const TONE = {
  ok: { bar: "bg-brand", text: "text-ink-muted", label: null },
  warning: { bar: "bg-warning", text: "text-warning", label: "Warning" },
  critical: { bar: "bg-fault", text: "text-fault", label: "Critical" },
  unknown: { bar: "bg-line", text: "text-ink-muted", label: null },
} as const;

function Budget({
  usage,
  totals,
}: {
  usage: Usage;
  totals: ReturnType<typeof summariseUsage>;
}) {
  const tone = TONE[totals.budgetState];
  const percent = totals.budgetUsed === null ? null : Math.round(totals.budgetUsed * 100);

  return (
    <Panel className="flex min-w-0 flex-col p-5">
      <Eyebrow>Daily budget</Eyebrow>
      <p className="mt-2 text-[0.8125rem] text-ink-muted">
        A rolling twenty-four hours, not a calendar day.
      </p>

      {percent === null ? (
        <p className="mt-5 text-[0.875rem] text-ink-muted">
          This organisation has no token ceiling set, so there is nothing to draw.
        </p>
      ) : (
        <>
          <div className="mt-5 flex items-baseline justify-between gap-2">
            <span className="font-mono text-sm tabular-nums text-ink">{percent}% used</span>
            {tone.label ? (
              <span className={cn("text-[0.75rem] font-medium", tone.text)}>{tone.label}</span>
            ) : null}
          </div>

          <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-surface-sunk">
            <div
              className={cn("h-full rounded-full transition-all", tone.bar)}
              style={{ width: `${Math.max(percent, 1)}%` }}
            />
          </div>

          <p className="mt-3 font-mono text-[0.75rem] text-ink-muted tabular-nums">
            {usage.tokens_last_24h.toLocaleString()} /{" "}
            {usage.daily_token_budget.toLocaleString()} tokens
          </p>
        </>
      )}

      <p className="mt-auto pt-5 font-mono text-[0.75rem] text-ink-muted tabular-nums">
        {usage.runs_last_24h.toLocaleString()} run
        {usage.runs_last_24h === 1 ? "" : "s"} in the last 24h
      </p>
    </Panel>
  );
}
