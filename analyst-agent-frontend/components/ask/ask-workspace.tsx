"use client";

import { ChevronDown, Database } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { mutate } from "swr";

import { AgentOrb } from "@/components/ask/agent-orb";
import {
  AnswerText,
  AssistantMessage,
  MessageActions,
  UserMessage,
} from "@/components/ask/chat-message";
import { Composer } from "@/components/ask/composer";
import { PastTurn } from "@/components/ask/past-turn";
import { ResultChart } from "@/components/ask/result-chart";
import { ResultTable } from "@/components/ask/result-table";
import { RunErrorPanel } from "@/components/ask/run-error";
import { RunProcess } from "@/components/ask/run-process";
import { RunStatus } from "@/components/ask/run-status";
import { SidebarTrigger } from "@/components/app-shell/sidebar-context";
import { buildChart, forecastTable } from "@/features/ask/chart";
import type { RunState } from "@/features/ask/run-types";
import { isRunning } from "@/features/ask/run-types";
import { THREADS_KEY, withAskedThread } from "@/features/ask/threads";
import { useRun } from "@/features/ask/use-run";
import { useTranscriptScroll } from "@/features/ask/use-transcript-scroll";
import { useTypedAnswer } from "@/features/ask/use-typed-answer";
import type { Connection, RunSummary, Thread } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/**
 * The ask screen: the conversation and the composer. The list of conversations is the
 * sidebar's, in the app shell.
 *
 * Four things are worth knowing before changing anything here.
 *
 * A run is started from the submit handler and never from an effect. React double-invokes
 * effects in development and a run costs tokens against the tenant's daily budget.
 *
 * The turns this hook accumulates are this sitting only, and they are not history. A reload
 * clears them; the runs page is the record, and reopening a thread replays it from the agent
 * as `history`. A run can be in both when the page re-renders the thread it is in, so history
 * drops anything this sitting already shows.
 *
 * The result table can be five hundred columns wide, so every flex and grid child that can
 * contain it carries `min-w-0`. Without it the table refuses to shrink and stretches the
 * whole transcript instead of scrolling inside its own box.
 *
 * The composer is one element for the life of the page. An empty conversation centres it with
 * spacers around it rather than rendering a second composer, so sending the first question
 * does not unmount the textarea you were typing in and throw away its focus.
 */

export function AskWorkspace({
  connections,
  unreachable,
  threadId,
  history,
}: {
  connections: Connection[];
  /** The agent did not answer, so `connections` is empty for want of an answer, not of any. */
  unreachable: boolean;
  threadId: string;
  history: RunSummary[];
}) {
  const { state, turns, ask, cancel } = useRun();
  const { viewportRef, contentRef, onSubmit: followSubmittedQuestion } = useTranscriptScroll();
  const [question, setQuestion] = useState("");
  // A continued thread keeps asking the database it was asking, if that still exists.
  const [connectionId, setConnectionId] = useState(() => {
    const last = history[history.length - 1]?.connection_id;
    return connections.some((c) => c.id === last) ? last : (connections[0]?.id ?? "");
  });

  const busy = isRunning(state.phase);
  const started = state.phase !== "idle";
  const shown = new Set([...turns.map((turn) => turn.runId), state.runId]);
  const past = history.filter((run) => !shown.has(run.id));
  const empty = !started && turns.length === 0 && past.length === 0;
  const activeConnection = connections.find((c) => c.id === connectionId) ?? null;
  // The agent refuses a connection whose tables were listed but none chosen, so the composer
  // says so before a question is typed rather than after it is sent. Zero listed means the
  // tables have not been read yet, which the first question does itself.
  const needsTables =
    activeConnection !== null &&
    activeConnection.total_tables > 0 &&
    activeConnection.selected_tables === 0;
  const ready = connectionId !== "" && !needsTables;
  const canSend = question.trim().length >= 3 && ready && !busy;

  async function send(asked: string) {
    followSubmittedQuestion();

    // A new conversation gets its id into the address bar, so the sidebar can mark it and a
    // reload comes back to it. Replaced, not pushed: Back should leave the chat, not un-ask.
    const url = new URL(window.location.href);
    if (url.searchParams.get("thread") !== threadId) {
      url.searchParams.set("thread", threadId);
      window.history.replaceState(null, "", url);
    }

    // Undefined until the sidebar's first fetch lands; returning it leaves that list alone.
    void mutate<Thread[]>(
      THREADS_KEY,
      (current) =>
        current &&
        withAskedThread(current, {
          threadId,
          question: asked,
          connectionId,
          at: new Date().toISOString(),
        }),
      { revalidate: false },
    );

    await ask({ connectionId, question: asked, threadId });
    void mutate(THREADS_KEY);
  }

  function submit() {
    if (!canSend) return;
    const asked = question.trim();
    // Cleared before the await, so the composer empties the instant you send.
    setQuestion("");
    void send(asked);
  }

  const askAgain = ready && !busy ? (asked: string) => () => void send(asked) : null;

  const lastSittingIndex = turns.length - 1;

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-surface">
      <header className="flex h-14 shrink-0 items-center gap-1 px-2 sm:px-3">
        <SidebarTrigger />
        {unreachable ? null : (
          <ConnectionPicker
            connections={connections}
            value={connectionId}
            onChange={setConnectionId}
            active={activeConnection}
          />
        )}
      </header>

      <div
        ref={viewportRef}
        className={cn(
          "min-h-0 overflow-y-auto [overflow-anchor:none]",
          empty ? "flex flex-1 flex-col justify-end" : "flex-1",
        )}
      >
        <div ref={contentRef} className="mx-auto w-full max-w-3xl px-4 sm:px-6">
          {empty ? (
            <Welcome
              connections={connections}
              active={activeConnection}
              unreachable={unreachable}
            />
          ) : (
            <div className="flex flex-col gap-10 pt-4 pb-12">
              {past.map((run, i) => (
                <PastTurn
                  key={run.id}
                  run={run}
                  latest={!started && turns.length === 0 && i === past.length - 1}
                  onAskAgain={askAgain?.(run.question)}
                />
              ))}

              {turns.map((turn, i) => (
                <Turn
                  key={(turn.runId ?? "turn") + "-" + i}
                  turn={turn}
                  latest={!started && i === lastSittingIndex}
                  onAskAgain={turn.question ? askAgain?.(turn.question) : undefined}
                />
              ))}

              {started ? (
                <Turn
                  turn={state}
                  live
                  latest
                  onAskAgain={state.question ? askAgain?.(state.question) : undefined}
                />
              ) : null}
            </div>
          )}
        </div>
      </div>

      <div className="shrink-0 px-3 pb-3 sm:px-6">
        <div className="mx-auto w-full max-w-3xl">
          <Composer
            value={question}
            onChange={setQuestion}
            onSubmit={submit}
            onStop={cancel}
            busy={busy}
            canSend={canSend}
            disabled={connections.length === 0 || needsTables}
            placeholder={
              unreachable
                ? "Waiting for the analyst service"
                : connections.length === 0
                ? "Connect a database before asking anything"
                : needsTables
                  ? "Choose which tables the agent may read before asking"
                  : empty
                    ? "Ask anything about your data"
                    : "Ask a follow-up"
            }
            notice={
              needsTables && activeConnection ? (
                <>
                  <span>No tables are chosen for {activeConnection.name} yet.</span>
                  <Link
                    href={`/connections/${connectionId}/tables`}
                    className="font-medium text-brand transition-colors hover:text-brand-hover"
                  >
                    Choose its tables
                  </Link>
                </>
              ) : null
            }
          />
        </div>
      </div>

      {/* Balances the space above the welcome, which is what centres the composer. */}
      {empty ? <div aria-hidden className="flex-1" /> : null}
    </div>
  );
}

/** One question and everything the agent handed back for it. */
function Turn({
  turn,
  live,
  latest,
  onAskAgain,
}: {
  turn: RunState;
  live?: boolean;
  latest: boolean;
  onAskAgain?: () => void;
}) {
  const answer = useTypedAnswer(turn.answer, Boolean(live));
  const running = isRunning(turn.phase);
  // Ask before laying out: ResultChart returns null when the spec cannot be drawn honestly,
  // and the table should not leave a gap where a chart was going to be.
  const plottable =
    turn.chart !== null &&
    turn.result !== null &&
    buildChart(turn.chart, turn.result).kind !== "none";
  const forecast = turn.chart ? forecastTable(turn.chart) : null;

  return (
    <div className="flex flex-col gap-5">
      <UserMessage>{turn.question}</UserMessage>

      <AssistantMessage>
        {running ? (
          <div className="flex min-w-0 items-center gap-2.5">
            <AgentOrb thinking className="size-7" />
            <RunStatus state={turn} />
          </div>
        ) : null}

        {turn.answer ? (
          <AnswerText shown={answer} full={turn.answer} streaming={Boolean(live) && running} />
        ) : null}

        {plottable && turn.chart && turn.result ? (
          <ResultChart spec={turn.chart} result={turn.result} />
        ) : null}
        {forecast ? <ResultTable result={forecast} /> : null}
        {turn.result ? <ResultTable result={turn.result} /> : null}

        {turn.error ? <RunErrorPanel error={turn.error} /> : null}

        {turn.phase === "cancelled" ? (
          <p className="text-[0.875rem] text-ink-muted">You stopped this run.</p>
        ) : null}

        {running ? null : (
          <MessageActions copyText={turn.answer} onAskAgain={onAskAgain} persistent={latest}>
            <RunProcess state={turn} />
          </MessageActions>
        )}
      </AssistantMessage>
    </div>
  );
}

/**
 * The connection selector. Still a native select, laid transparently over a button-shaped
 * label: no portal, no open state, and the platform's own picker and keyboard handling on
 * every device.
 */
function ConnectionPicker({
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
        className="inline-flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-[0.9375rem] font-medium text-ink-muted transition-colors hover:bg-surface-sunk hover:text-ink"
      >
        <Database aria-hidden className="size-4" strokeWidth={1.75} />
        Connect a database
      </Link>
    );
  }

  const many = connections.length > 1;

  return (
    <div
      className={cn(
        "relative inline-flex min-w-0 items-center gap-2 rounded-lg px-2.5 py-1.5 text-[0.9375rem] font-medium text-ink",
        many && "transition-colors focus-within:ring-2 focus-within:ring-brand/25 hover:bg-surface-sunk",
      )}
    >
      <Database aria-hidden className="size-4 shrink-0 text-ink-muted" strokeWidth={1.75} />
      <span className="max-w-[16rem] truncate">{active?.name}</span>
      {many ? (
        <>
          <ChevronDown aria-hidden className="size-4 shrink-0 text-ink-muted" strokeWidth={2} />
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

function Welcome({
  connections,
  active,
  unreachable,
}: {
  connections: Connection[];
  active: Connection | null;
  unreachable: boolean;
}) {
  const router = useRouter();
  // A refresh re-runs the page's reads, which is the whole retry; the transition is only there
  // to show it is in flight, because waking the agent can take most of a minute.
  const [retrying, startRetry] = useTransition();

  return (
    <div className="flex flex-col items-center pb-8 text-center">
      <AgentOrb className="mb-6 size-16" />

      {unreachable ? (
        <>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">
            The analyst service didn&rsquo;t answer
          </h1>
          <p className="mt-2 max-w-[46ch] text-[0.9375rem] leading-relaxed text-ink-muted">
            It may still be starting up, which can take up to a minute. Your connections are
            safe.
          </p>
          <button
            type="button"
            disabled={retrying}
            onClick={() => startRetry(() => router.refresh())}
            className="mt-5 inline-block rounded-full bg-brand px-4 py-2 text-[0.875rem] font-medium text-brand-fg transition-colors hover:bg-brand-hover disabled:opacity-60"
          >
            {retrying ? "Trying again…" : "Try again"}
          </button>
        </>
      ) : connections.length === 0 ? (
        <>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">
            Connect a database to get started
          </h1>
          <p className="mt-2 max-w-[46ch] text-[0.9375rem] leading-relaxed text-ink-muted">
            Point the agent at a Postgres database with a read-only role, or upload spreadsheets,
            then ask it questions in plain English.
          </p>
          <Link
            href="/connections"
            className="mt-5 inline-block rounded-full bg-brand px-4 py-2 text-[0.875rem] font-medium text-brand-fg transition-colors hover:bg-brand-hover"
          >
            Add a connection
          </Link>
        </>
      ) : (
        <>
          <h1 className="text-2xl font-semibold tracking-tight text-balance text-ink sm:text-[1.75rem]">
            What do you want to know about {active?.name ?? "your data"}?
          </h1>
          <p className="mt-2 max-w-[52ch] text-[0.9375rem] leading-relaxed text-ink-muted">
            Ask in plain English. The agent writes the SQL, checks it, runs it read-only, and
            shows you the query behind every answer.
          </p>
        </>
      )}
    </div>
  );
}
