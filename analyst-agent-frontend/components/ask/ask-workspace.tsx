"use client";

import Link from "next/link";
import { useState } from "react";

import { ResultTable } from "@/components/ask/result-table";
import { RunErrorPanel } from "@/components/ask/run-error";
import { RunTimeline } from "@/components/ask/run-timeline";
import { SqlBlock } from "@/components/ask/sql-block";
import { Button } from "@/components/ui/button";
import { isRunning } from "@/features/ask/run-types";
import { useRun } from "@/features/ask/use-run";
import type { Connection } from "@/lib/api/types";

/**
 * The transcript.
 *
 * Question, then SQL, then the table, then the answer, in the order the stream delivers them,
 * so the page fills downwards as the agent works rather than appearing all at once.
 *
 * The thread id is minted once per conversation and reused for every follow-up, which is what
 * makes the agent replay the earlier turns.
 */
export function AskWorkspace({
  connections,
  threadId,
}: {
  connections: Connection[];
  threadId: string;
}) {
  const { state, ask, cancel, reset } = useRun();
  const [question, setQuestion] = useState("");
  const [connectionId, setConnectionId] = useState(connections[0]?.id ?? "");

  const busy = isRunning(state.phase);
  const canAsk = question.trim().length >= 3 && connectionId !== "" && !busy;
  const started = state.phase !== "idle";

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!canAsk) return;
    const asked = question.trim();
    setQuestion("");
    await ask({ connectionId, question: asked, threadId });
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl px-5 py-10 sm:px-8">
          {!started ? (
            <Opening connections={connections} />
          ) : (
            <article className="flex flex-col gap-7 bg-paper p-6 sm:p-8">
              <h1 className="text-[1.5rem] leading-[1.3] font-normal text-ink">
                {state.question}
              </h1>

              <RunTimeline state={state} />

              {state.sql ? <SqlBlock sql={state.sql} /> : null}
              {state.result ? <ResultTable result={state.result} /> : null}

              {state.answer ? (
                <p className="max-w-[68ch] text-[1.0625rem] leading-[1.65] text-ink">
                  {state.answer}
                </p>
              ) : null}

              {state.error ? <RunErrorPanel error={state.error} /> : null}

              {state.phase === "cancelled" ? (
                <p className="text-[0.875rem] text-ink-muted">You stopped this run.</p>
              ) : null}
            </article>
          )}
        </div>
      </div>

      <div className="shrink-0 border-t border-rule-ground bg-ground">
        <form onSubmit={submit} className="mx-auto w-full max-w-3xl px-5 py-4 sm:px-8">
          <div className="flex flex-col gap-3">
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void submit(e);
              }}
              rows={2}
              disabled={connections.length === 0}
              placeholder={
                connections.length === 0
                  ? "Add a connection before you can ask anything"
                  : started
                    ? "Ask a follow-up"
                    : "Ask a question about your data"
              }
              aria-label="Your question"
              className="w-full resize-none rounded-sm border border-rule-ground bg-ground-raised px-3 py-2.5 text-[0.9375rem] text-ground-ink placeholder:text-ground-muted focus-visible:outline-none disabled:opacity-60"
            />

            <div className="flex flex-wrap items-center gap-3">
              {connections.length > 1 ? (
                <select
                  value={connectionId}
                  onChange={(e) => setConnectionId(e.target.value)}
                  aria-label="Data source"
                  className="h-8 rounded-sm border border-rule-ground bg-ground-raised px-2 text-[0.8125rem] text-ground-ink"
                >
                  {connections.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              ) : connections.length === 1 ? (
                <span className="font-mono text-[0.75rem] text-ground-muted">
                  {connections[0].name}
                </span>
              ) : null}

              <span className="ml-auto flex items-center gap-2">
                {started && !busy ? (
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={reset}
                    className="h-8 px-2 text-[0.8125rem] text-ground-muted hover:bg-ground-raised hover:text-ground-ink"
                  >
                    New question
                  </Button>
                ) : null}

                {busy ? (
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={cancel}
                    className="h-8 px-3 text-[0.8125rem] text-ground-muted hover:bg-ground-raised hover:text-ground-ink"
                  >
                    Stop
                  </Button>
                ) : (
                  <Button
                    type="submit"
                    disabled={!canAsk}
                    className="h-8 bg-paper px-4 text-[0.8125rem] text-ground hover:bg-paper/90"
                  >
                    Ask
                  </Button>
                )}
              </span>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}

/** The empty state. An invitation to act, and a route out when there is nothing to act on. */
function Opening({ connections }: { connections: Connection[] }) {
  if (connections.length === 0) {
    return (
      <div className="bg-paper p-8">
        <h1 className="text-[1.5rem] font-normal text-ink">Connect a database first</h1>
        <p className="mt-2 max-w-[52ch] text-[0.9375rem] leading-relaxed text-ink-muted">
          Point this at a Postgres database and you can ask it questions in plain English. It
          only ever reads.
        </p>
        <Link
          href="/connections"
          className="mt-6 inline-block bg-ground px-4 py-2 text-[0.875rem] text-paper"
        >
          Add a connection
        </Link>
      </div>
    );
  }

  return (
    <div className="bg-paper p-8">
      <h1 className="text-[1.5rem] font-normal text-ink">Ask a question</h1>
      <p className="mt-2 max-w-[54ch] text-[0.9375rem] leading-relaxed text-ink-muted">
        Write it the way you would ask a colleague. You will see the SQL it wrote, the rows it
        returned, and what it makes of them.
      </p>
    </div>
  );
}
