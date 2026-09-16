"use client";

import { useEffect, useRef, useState } from "react";

import {
  AnswerText,
  AssistantMessage,
  MessageActions,
  UserMessage,
} from "@/components/ask/chat-message";
import { RunErrorPanel } from "@/components/ask/run-error";
import { RunProcess } from "@/components/ask/run-process";
import { Skeleton } from "@/components/ui/skeleton";
import type { RunDetail, RunSummary } from "@/lib/api/types";

/**
 * A turn from before this sitting, replayed from the agent.
 *
 * It reads like any other message, but without a result table. The agent records how many
 * rows came back, never what they were, so there is no table to restore and there never will
 * be -- asking again is how you get fresh numbers, and the action row offers exactly that.
 *
 * The thread's list carries no SQL or answer text, because both are unbounded and a thread of
 * fifty would be a heavy payload just to find your place. Each answer is fetched when its turn
 * comes within a screen of the viewport, the same way the runs page fetches one it opens, so a
 * long thread costs requests only for what someone actually scrolls to.
 */

/** How far outside the viewport a turn starts loading, so it is usually ready on arrival. */
const PRELOAD_MARGIN = "600px 0px";

export function PastTurn({
  run,
  latest,
  onAskAgain,
}: {
  run: RunSummary;
  latest: boolean;
  onAskAgain?: () => void;
}) {
  const root = useRef<HTMLDivElement>(null);
  const [near, setNear] = useState(false);

  useEffect(() => {
    const element = root.current;
    if (!element || near) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) setNear(true);
      },
      { rootMargin: PRELOAD_MARGIN },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [near]);

  return (
    <div ref={root} className="flex flex-col gap-5">
      <UserMessage>{run.question}</UserMessage>
      <AssistantMessage>
        {near ? (
          <Reply runId={run.id} latest={latest} onAskAgain={onAskAgain} />
        ) : (
          <ReplySkeleton />
        )}
      </AssistantMessage>
    </div>
  );
}

function Reply({
  runId,
  latest,
  onAskAgain,
}: {
  runId: string;
  latest: boolean;
  onAskAgain?: () => void;
}) {
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Fetching here is correct, unlike starting a run: this reads a row that is about to be on
  // screen, costs nothing against the budget, and is abandoned if the turn goes away first.
  useEffect(() => {
    const controller = new AbortController();
    fetch(`/api/runs/${runId}`, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("failed");
        setDetail((await response.json()) as RunDetail);
      })
      .catch(() => {
        if (!controller.signal.aborted) setError("Could not load that answer.");
      });
    return () => controller.abort();
  }, [runId]);

  if (error) return <p className="text-[0.875rem] text-fault">{error}</p>;
  if (!detail) return <ReplySkeleton />;

  return (
    <>
      {detail.answer ? <AnswerText shown={detail.answer} full={detail.answer} /> : null}
      {detail.error ? <RunErrorPanel error={{ kind: "agent", message: detail.error }} /> : null}
      {!detail.answer && !detail.error ? (
        <p className="text-[0.875rem] text-ink-muted">No answer was recorded for this run.</p>
      ) : null}
      <MessageActions copyText={detail.answer} onAskAgain={onAskAgain} persistent={latest}>
        <RunProcess detail={detail} />
      </MessageActions>
    </>
  );
}

/** Roughly the height of a short answer and its action row, so loading one barely moves the page. */
function ReplySkeleton() {
  return (
    <div role="presentation" className="flex flex-col gap-2.5 pt-1.5 pb-8">
      <Skeleton className="h-3.5 w-11/12 rounded-full bg-surface-sunk" />
      <Skeleton className="h-3.5 w-3/4 rounded-full bg-surface-sunk" />
    </div>
  );
}
