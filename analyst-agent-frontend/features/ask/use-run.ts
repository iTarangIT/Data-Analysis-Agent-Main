"use client";

import { useCallback, useReducer, useRef, useState } from "react";

import { readSseStream } from "@/lib/sse/sse-stream";

import { runReducer } from "./run-machine";
import { IDLE_RUN, type RunEvent, type RunState } from "./run-types";

const TERMINAL_EVENTS = new Set(["done", "error"]);

export type UseRun = {
  /** The run happening now, or the last one to settle. */
  state: RunState;
  /** Earlier turns in this sitting, oldest first. Never includes `state`. */
  turns: RunState[];
  ask: (input: { connectionId: string; question: string; threadId: string }) => Promise<void>;
  cancel: () => void;
  reset: () => void;
};

/**
 * Drive one run, and keep the earlier ones on screen.
 *
 * Started from an event handler, never an effect: React double-invokes effects in
 * development, and a run costs tokens against the tenant's daily budget.
 *
 * The archive lives here rather than in the reducer. `runReducer` stays a pure function of
 * one run, which is what keeps it testable without a notion of history, and what means none
 * of its tests had to change to add this. A settled run is immutable -- the reducer ignores
 * everything but `@submit` and `@reset` once a run is terminal -- so the snapshot pushed
 * here can never be mutated behind our back.
 *
 * This archive is memory only, and the transcript is not history: a reload clears it and the
 * runs page remains the record. Reopening a thread replays it from the agent instead.
 */
export function useRun(): UseRun {
  const [state, dispatch] = useReducer(runReducer, IDLE_RUN);
  const [turns, setTurns] = useState<RunState[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  const ask = useCallback<UseRun["ask"]>(async ({ connectionId, question, threadId }) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    // Archive whatever is on screen before the reducer clears it. A cancelled or failed turn
    // is archived too: it is part of what happened, and dropping it would make the transcript
    // read as though the question was never asked.
    //
    // Reading `state` straight from the closure is safe because this only ever runs from a
    // submit handler, so the value it captured is the one that was on screen when the person
    // pressed send -- and it is read before the dispatch below clears it.
    if (state.phase !== "idle") {
      setTurns((current) => [...current, state]);
    }

    dispatch({ type: "@submit", question, connectionId, threadId });

    let response: Response;
    try {
      response = await fetch("/api/runs", {
        method: "POST",
        headers: { "content-type": "application/json", accept: "text/event-stream" },
        body: JSON.stringify({
          connection_id: connectionId,
          thread_id: threadId,
          question,
        }),
        signal: controller.signal,
      });
    } catch {
      dispatch(
        controller.signal.aborted
          ? { type: "@abort" }
          : { type: "@transport", message: "could not reach the server" },
      );
      return;
    }

    // Everything that fails before the stream opens is a status, not an event.
    if (!response.ok || !response.body) {
      const body = (await response.json().catch(() => ({}))) as {
        error?: string;
        code?: string;
      };
      dispatch({
        type: "@http",
        status: response.status,
        message: body.error ?? "that question could not be run",
        code: body.code,
      });
      return;
    }

    dispatch({ type: "@open" });

    const outcome = await readSseStream(
      response.body,
      ({ event, data }) => {
        let parsed: unknown;
        try {
          parsed = JSON.parse(data);
        } catch {
          return; // a frame we cannot read is not worth failing the run over
        }
        dispatch({ type: event, data: parsed } as RunEvent);
        if (TERMINAL_EVENTS.has(event)) return "stop";
      },
      controller.signal,
    );

    // `complete` needs nothing: the terminal event already moved the machine. The others are
    // the stream ending in a way the agent did not announce.
    if (outcome.kind === "aborted") dispatch({ type: "@abort" });
    else if (outcome.kind === "transport") {
      dispatch({ type: "@transport", message: outcome.message });
    } else if (outcome.kind === "closed") dispatch({ type: "@closed" });
  }, [state]);

  const cancel = useCallback(() => abortRef.current?.abort(), []);
  const reset = useCallback(() => {
    abortRef.current?.abort();
    setTurns([]);
    dispatch({ type: "@reset" });
  }, []);

  return { state, turns, ask, cancel, reset };
}
