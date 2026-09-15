"use client";

import { ArrowUp, Loader2, ShieldCheck, Sparkles } from "lucide-react";
import { useState } from "react";

import { PastTurn } from "@/components/ask/past-turn";
import { ResultChart } from "@/components/ask/result-chart";
import { ResultTable } from "@/components/ask/result-table";
import { RunErrorPanel } from "@/components/ask/run-error";
import { RunTimeline } from "@/components/ask/run-timeline";
import { ThreadList } from "@/components/ask/thread-list";
import { Button } from "@/components/ui/button";
import { buildChart } from "@/features/ask/chart";
import { SOURCE_LABEL, sourceOf } from "@/features/ask/source";
import type { RunState } from "@/features/ask/run-types";
import { isRunning } from "@/features/ask/run-types";
import { useRun } from "@/features/ask/use-run";
import type { RunSummary, Thread } from "@/lib/api/types";

/**
 * The ask screen: threads, the conversation, and the composer.
 *
 * There is no source picker. This deployment answers from two fixed sources and the agent
 * routes between them on whether the question is about now or about what has been recorded,
 * so choosing is not a decision to put in front of anyone. The transcript says which source
 * answered instead, after the fact, because nobody selected it.
 *
 * Three further things are worth knowing before changing anything here.
 *
 * A run is started from the submit handler and never from an effect. React double-invokes
 * effects in development and a run costs tokens against the tenant's daily budget.
 *
 * The turns this hook accumulates are this sitting only, and they are not history. A reload
 * clears them; the runs page is the record, and reopening a thread replays it from the agent
 * as `history`.
 *
 * The result table can be five hundred columns wide, so every flex and grid child that can
 * contain it carries `min-w-0`. Without it the table refuses to shrink and stretches the
 * whole transcript instead of scrolling inside its own box.
 */

export function AskWorkspace({
  threadId,
  threads,
  history,
  userInitials,
}: {
  threadId: string;
  threads: Thread[];
  history: RunSummary[];
  userInitials: string;
}) {
  const { state, turns, ask, cancel, reset } = useRun();
  const [question, setQuestion] = useState("");

  const busy = isRunning(state.phase);
  const canAsk = question.trim().length >= 3 && !busy;
  const started = state.phase !== "idle";
  const empty = !started && turns.length === 0 && history.length === 0;

  async function submit(event: { preventDefault: () => void }) {
    event.preventDefault();
    if (!canAsk) return;
    const asked = question.trim();
    // Cleared before the await, so the composer empties the instant you send.
    setQuestion("");
    // No connection id: the agent routes this to whichever source can answer it.
    await ask({ question: asked, threadId });
  }

  return (
    <div className="flex min-h-0 flex-1">
      <aside className="hidden w-[248px] shrink-0 border-r border-line bg-surface lg:block">
        <ThreadList threads={threads} activeId={threadId} />
      </aside>

      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-end gap-3 border-b border-line bg-surface px-5 sm:px-6">
          {started && !busy ? (
            <Button
              variant="ghost"
              onClick={reset}
              className="h-8 px-2.5 text-[0.8125rem] text-ink-muted hover:bg-surface-sunk hover:text-ink"
            >
              New question
            </Button>
          ) : null}
        </header>

        <div className="flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-3xl px-5 py-8 sm:px-6">
            {empty ? (
              <Opening />
            ) : (
              <div className="flex flex-col gap-8">
                {history.length > 0 ? (
                  <section className="flex flex-col gap-5">
                    <p className="text-[0.6875rem] font-semibold tracking-[0.08em] text-ink-faint uppercase">
                      Earlier in this thread
                    </p>
                    {history.map((run) => (
                      <TurnRow key={run.id} avatar={<UserAvatar initials={userInitials} />}>
                        <PastTurn run={run} />
                      </TurnRow>
                    ))}
                  </section>
                ) : null}

                {turns.map((turn, i) => (
                  <Turn key={(turn.runId ?? "turn") + "-" + i} turn={turn} initials={userInitials} />
                ))}

                {started ? (
                  <Turn turn={state} initials={userInitials} onCancel={cancel} live />
                ) : null}
              </div>
            )}
          </div>
        </div>

        <div className="shrink-0 px-5 pt-2 pb-5 sm:px-6">
          <form onSubmit={submit} className="mx-auto w-full max-w-3xl">
            <div className="rounded-xl border border-line bg-surface p-3 shadow-card focus-within:border-brand/40 focus-within:ring-2 focus-within:ring-brand/15">
              <textarea
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) void submit(event);
                }}
                rows={2}
                aria-label="Your question"
                placeholder={started ? "Ask a follow-up" : "Ask a question about your data"}
                className="w-full resize-none border-0 bg-transparent px-1 py-1 text-[0.9375rem] text-ink placeholder:text-ink-faint focus-visible:outline-none disabled:opacity-60"
              />

              <div className="mt-2 flex items-center gap-3">
                <p className="flex min-w-0 items-center gap-1.5 truncate text-[0.75rem] text-ink-muted">
                  <ShieldCheck
                    aria-hidden
                    className="size-3.5 shrink-0 text-success"
                    strokeWidth={2}
                  />
                  Read-only. It never writes to your database.
                </p>

                <span className="ml-auto flex shrink-0 items-center gap-3">
                  <kbd className="hidden font-mono text-[0.6875rem] text-ink-faint sm:inline">
                    Ctrl + Enter
                  </kbd>
                  <button
                    type="submit"
                    disabled={!canAsk}
                    aria-label={busy ? "Running" : "Ask"}
                    className="flex size-9 shrink-0 items-center justify-center rounded-full bg-brand text-brand-fg transition-colors hover:bg-brand-hover disabled:opacity-40 disabled:hover:bg-brand"
                  >
                    {busy ? (
                      <Loader2 aria-hidden className="size-4 animate-spin" />
                    ) : (
                      <ArrowUp aria-hidden className="size-4" strokeWidth={2.25} />
                    )}
                  </button>
                </span>
              </div>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}

/** One question and everything the agent handed back for it. */
function Turn({
  turn,
  initials,
  onCancel,
  live,
}: {
  turn: RunState;
  initials: string;
  onCancel?: () => void;
  live?: boolean;
}) {
  // Ask before laying out: ResultChart returns null when the spec cannot be drawn honestly,
  // and without this the table would sit half-width beside an empty column.
  const plottable =
    turn.chart !== null &&
    turn.result !== null &&
    buildChart(turn.chart, turn.result).kind !== "none";

  // Nobody chose the source, so the turn has to say which one answered.
  const source = sourceOf(turn);

  return (
    <div className="flex flex-col gap-6">
      <TurnRow avatar={<UserAvatar initials={initials} />}>
        <p className="text-[0.9375rem] leading-[1.6] font-medium text-ink">{turn.question}</p>
      </TurnRow>

      <TurnRow avatar={<AgentAvatar />}>
        <div className="flex flex-col gap-5">
          <RunTimeline state={turn} onCancel={live ? onCancel : undefined} />

          {source ? (
            <p className="flex items-center gap-1.5 text-[0.75rem] text-ink-muted">
              <Sparkles aria-hidden className="size-3 shrink-0 text-brand" strokeWidth={2} />
              {SOURCE_LABEL[source]}
            </p>
          ) : null}

          {plottable && turn.chart && turn.result ? (
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              <div className="min-w-0">
                <ResultChart spec={turn.chart} result={turn.result} />
              </div>
              <div className="min-w-0">
                <ResultTable result={turn.result} />
              </div>
            </div>
          ) : turn.result ? (
            <ResultTable result={turn.result} />
          ) : null}

          {turn.answer ? (
            <p className="max-w-[68ch] text-[0.9375rem] leading-[1.7] text-ink">{turn.answer}</p>
          ) : null}

          {turn.error ? <RunErrorPanel error={turn.error} /> : null}

          {turn.phase === "cancelled" ? (
            <p className="text-[0.875rem] text-ink-muted">You stopped this run.</p>
          ) : null}
        </div>
      </TurnRow>
    </div>
  );
}

function TurnRow({ avatar, children }: { avatar: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="flex gap-3.5">
      <div className="shrink-0 pt-0.5">{avatar}</div>
      {/* min-w-0, or a wide result table stretches the whole transcript. */}
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

function UserAvatar({ initials }: { initials: string }) {
  return (
    <span
      aria-hidden
      className="flex size-7 items-center justify-center rounded-full bg-surface-sunk font-mono text-[0.625rem] font-medium text-ink-muted"
    >
      {initials}
    </span>
  );
}

/** A mark, not a monogram: this product has no logo and is not about to grow one here. */
function AgentAvatar() {
  return (
    <span
      aria-hidden
      className="flex size-7 items-center justify-center rounded-full bg-brand-soft text-brand"
    >
      <Sparkles className="size-3.5" strokeWidth={2} />
    </span>
  );
}

function Opening() {
  return (
    <div className="py-16 text-center">
      <h1 className="text-xl font-semibold tracking-tight text-ink">Ask a question</h1>
      <p className="mx-auto mt-2 max-w-[48ch] text-[0.9375rem] leading-relaxed text-ink-muted">
        In plain English. Questions about what is happening now are read live from the
        dashboard; anything already recorded is answered from the IoT database. The agent picks,
        and every answer says which one it came from.
      </p>
    </div>
  );
}
