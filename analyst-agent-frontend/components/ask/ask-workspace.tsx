"use client";

import { ArrowUp, ChevronDown, Database, ShieldCheck, Sparkles } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { PastTurn } from "@/components/ask/past-turn";
import { ResultChart } from "@/components/ask/result-chart";
import { ResultTable } from "@/components/ask/result-table";
import { RunErrorPanel } from "@/components/ask/run-error";
import { RunProcess } from "@/components/ask/run-process";
import { RunStatus } from "@/components/ask/run-status";
import { ThreadList } from "@/components/ask/thread-list";
import { Button } from "@/components/ui/button";
import { buildChart } from "@/features/ask/chart";
import type { RunState } from "@/features/ask/run-types";
import { isRunning } from "@/features/ask/run-types";
import { useRun } from "@/features/ask/use-run";
import { useTranscriptScroll } from "@/features/ask/use-transcript-scroll";
import { useTypedAnswer } from "@/features/ask/use-typed-answer";
import type { Connection, RunSummary, Thread } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/**
 * The ask screen: threads, the conversation, and the composer.
 *
 * Three things are worth knowing before changing anything here.
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
  connections,
  threadId,
  threads,
  history,
  userInitials,
}: {
  connections: Connection[];
  threadId: string;
  threads: Thread[];
  history: RunSummary[];
  userInitials: string;
}) {
  const { state, turns, ask, cancel, reset } = useRun();
  const { viewportRef, contentRef, onSubmit: followSubmittedQuestion } = useTranscriptScroll();
  const [question, setQuestion] = useState("");
  const [connectionId, setConnectionId] = useState(connections[0]?.id ?? "");

  const busy = isRunning(state.phase);
  const started = state.phase !== "idle";
  const empty = !started && turns.length === 0 && history.length === 0;
  const activeConnection = connections.find((c) => c.id === connectionId) ?? null;
  // The agent refuses a connection whose tables were listed but none chosen, so the composer
  // says so before a question is typed rather than after it is sent. Zero listed means the
  // tables have not been read yet, which the first question does itself.
  const needsTables =
    activeConnection !== null &&
    activeConnection.total_tables > 0 &&
    activeConnection.selected_tables === 0;
  const canAsk = question.trim().length >= 3 && connectionId !== "" && !needsTables && !busy;

  async function submit(event: { preventDefault: () => void }) {
    event.preventDefault();
    if (!canAsk) return;
    const asked = question.trim();
    // Cleared before the await, so the composer empties the instant you send.
    setQuestion("");
    followSubmittedQuestion();
    await ask({ connectionId, question: asked, threadId });
  }

  return (
    <div className="flex min-h-0 flex-1">
      <aside className="hidden w-[248px] shrink-0 border-r border-line bg-surface lg:block">
        <ThreadList threads={threads} activeId={threadId} />
      </aside>

      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line bg-surface px-5 sm:px-6">
          <ConnectionChip
            connections={connections}
            value={connectionId}
            onChange={setConnectionId}
            active={activeConnection}
          />

          {needsTables ? (
            <Link
              href={`/connections/${connectionId}/tables`}
              className="text-[0.8125rem] font-medium text-brand transition-colors hover:text-brand-hover"
            >
              Choose its tables
            </Link>
          ) : null}

          {started && !busy ? (
            <Button
              variant="ghost"
              onClick={reset}
              className="ml-auto h-8 px-2.5 text-[0.8125rem] text-ink-muted hover:bg-surface-sunk hover:text-ink"
            >
              New question
            </Button>
          ) : null}
        </header>

        <div ref={viewportRef} className="flex-1 overflow-y-auto [overflow-anchor:none]">
          <div ref={contentRef} className="mx-auto w-full max-w-3xl px-5 py-8 sm:px-6">
            {empty ? (
              <Opening connections={connections} />
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
                disabled={connections.length === 0 || needsTables}
                aria-label="Your question"
                placeholder={
                  connections.length === 0
                    ? "Connect a database before asking anything"
                    : needsTables
                      ? "Choose which tables the agent may read before asking"
                      : started
                      ? "Ask a follow-up"
                      : "Ask a question about your data"
                }
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
                      <span aria-hidden className="size-2.5 rounded-sm bg-current" />
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
  const answer = useTypedAnswer(turn.answer, Boolean(live));
  // Ask before laying out: ResultChart returns null when the spec cannot be drawn honestly,
  // and without this the table would sit half-width beside an empty column.
  const plottable =
    turn.chart !== null &&
    turn.result !== null &&
    buildChart(turn.chart, turn.result).kind !== "none";

  return (
    <div className="flex flex-col gap-6">
      <TurnRow avatar={<UserAvatar initials={initials} />}>
        <p className="text-[0.9375rem] leading-[1.6] font-medium text-ink">{turn.question}</p>
      </TurnRow>

      <TurnRow avatar={<AgentAvatar />}>
        <div className="flex flex-col gap-5">
          {isRunning(turn.phase) ? (
            <RunStatus state={turn} onCancel={live ? onCancel : undefined} />
          ) : (
            <RunProcess state={turn} />
          )}

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
            <p className="max-w-[68ch] text-[0.9375rem] leading-[1.7] whitespace-pre-wrap text-ink">
              <span aria-hidden>{answer}</span>
              <span className="sr-only">{turn.answer}</span>
            </p>
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

/**
 * The connection selector. Still a native select, laid transparently over a chip: no portal,
 * no open state, and the platform's own picker and keyboard handling on every device.
 */
function ConnectionChip({
  connections,
  value,
  onChange,
  active,
}: {
  connections: Connection[];
  value: string;
  onChange: (id: string) => void;
  active: Connection | null;
}) {
  if (connections.length === 0) {
    return (
      <Link
        href="/connections"
        className="inline-flex items-center gap-2 rounded-md border border-dashed border-line-strong px-2.5 py-1.5 text-[0.8125rem] text-ink-muted transition-colors hover:border-brand hover:text-brand"
      >
        <Database aria-hidden className="size-3.5" strokeWidth={1.75} />
        Connect a database
      </Link>
    );
  }

  const many = connections.length > 1;

  return (
    <div
      className={cn(
        "relative inline-flex items-center gap-2 rounded-md border border-line bg-surface px-2.5 py-1.5 text-[0.8125rem] text-ink",
        many && "focus-within:ring-2 focus-within:ring-brand/25",
      )}
    >
      <Database aria-hidden className="size-3.5 shrink-0 text-brand" strokeWidth={1.75} />
      <span className="max-w-[14rem] truncate font-medium">{active?.name}</span>
      {many ? (
        <>
          <ChevronDown aria-hidden className="size-3.5 shrink-0 text-ink-muted" strokeWidth={2} />
          <select
            value={value}
            onChange={(event) => onChange(event.target.value)}
            aria-label="Data source"
            className="absolute inset-0 size-full cursor-pointer appearance-none opacity-0"
          >
            {connections.map((connection) => (
              <option key={connection.id} value={connection.id}>
                {connection.name}
              </option>
            ))}
          </select>
        </>
      ) : null}
    </div>
  );
}

function Opening({ connections }: { connections: Connection[] }) {
  if (connections.length === 0) {
    return (
      <div className="py-16 text-center">
        <h1 className="text-xl font-semibold tracking-tight text-ink">Connect a database first</h1>
        <p className="mx-auto mt-2 max-w-[46ch] text-[0.9375rem] leading-relaxed text-ink-muted">
          Point the agent at a Postgres database with a read-only role and you can start asking
          questions of it in plain English.
        </p>
        <Link
          href="/connections"
          className="mt-6 inline-block rounded-md bg-brand px-4 py-2 text-[0.875rem] font-medium text-brand-fg transition-colors hover:bg-brand-hover"
        >
          Add a connection
        </Link>
      </div>
    );
  }

  return (
    <div className="py-16 text-center">
      <h1 className="text-xl font-semibold tracking-tight text-ink">Ask a question</h1>
      <p className="mx-auto mt-2 max-w-[46ch] text-[0.9375rem] leading-relaxed text-ink-muted">
        In plain English. The agent writes the SQL, checks it, runs it read-only, and shows you
        both the query and the rows it came back with.
      </p>
    </div>
  );
}
