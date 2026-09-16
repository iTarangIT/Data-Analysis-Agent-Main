import type { Thread } from "@/lib/api/types";

/**
 * The sidebar's list of conversations, as an SWR key.
 *
 * The sidebar lives in the app layout, and layouts do not re-render on navigation, so the
 * list cannot come from the page that asks the question. The ask screen writes to this key
 * instead: optimistically when a question is sent, and for real once the run settles.
 */
export const THREADS_KEY = "/api/threads?limit=30";

export async function fetchThreads(url: string): Promise<Thread[]> {
  const response = await fetch(url);
  if (!response.ok) throw new Error("could not load threads");
  return (await response.json()) as Thread[];
}

/**
 * The list as it will look once the agent has recorded the question just asked.
 *
 * A new conversation is titled by its first question, which is what the agent does too, so
 * the row does not change name when the real list replaces this one.
 */
export function withAskedThread(
  threads: Thread[],
  asked: { threadId: string; question: string; connectionId: string; at: string },
): Thread[] {
  const existing = threads.find((thread) => thread.thread_id === asked.threadId);
  const rest = threads.filter((thread) => thread.thread_id !== asked.threadId);

  const updated: Thread = existing
    ? {
        ...existing,
        run_count: existing.run_count + 1,
        last_run_at: asked.at,
        last_status: "running",
      }
    : {
        thread_id: asked.threadId,
        title: asked.question,
        run_count: 1,
        last_run_at: asked.at,
        last_status: "running",
        connection_id: asked.connectionId,
      };

  return [updated, ...rest];
}
