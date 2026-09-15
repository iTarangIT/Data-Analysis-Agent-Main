import { randomUUID } from "node:crypto";

import { AskWorkspace } from "@/components/ask/ask-workspace";
import { agentJson } from "@/lib/api/agent-client";
import { initialsOf } from "@/lib/initials";
import type { Connection, RunPage, Thread } from "@/lib/api/types";
import { getCurrentUser, requireSession } from "@/lib/auth/dal";

export const metadata = { title: "Ask" };
export const dynamic = "force-dynamic";

export default async function AskPage({ searchParams }: PageProps<"/ask">) {
  const session = await requireSession("/ask");
  // searchParams is a promise in Next 16.
  const { thread } = await searchParams;

  /**
   * The conversation id lives in the URL. It used to be minted on every render, which meant
   * a thread ended the moment anyone looked at another screen -- the agent was still replaying
   * history against an id the browser had already thrown away. A new id is minted only when
   * there is no thread to continue.
   */
  const threadId = typeof thread === "string" && thread.length > 0 ? thread : randomUUID();
  const continuing = typeof thread === "string" && thread.length > 0;

  // Read straight from the agent. Going through our own route handlers would add a round trip
  // between the handler and this render for nothing. None of the three is load-bearing: an
  // unreachable agent still renders the page, and the composer says why.
  const [connections, threads, history] = await Promise.all([
    agentJson<Connection[]>("/connections", { token: session.accessToken }).catch(
      (): Connection[] => [],
    ),
    agentJson<Thread[]>("/runs/threads?limit=30", { token: session.accessToken }).catch(
      (): Thread[] => [],
    ),
    continuing
      ? agentJson<RunPage>(
          `/runs?limit=50&thread_id=${encodeURIComponent(threadId)}`,
          { token: session.accessToken },
        ).catch((): RunPage => ({ items: [], next_cursor: null }))
      : Promise.resolve<RunPage>({ items: [], next_cursor: null }),
  ]);

  const user = await getCurrentUser();

  return (
    <AskWorkspace
      connections={connections}
      threadId={threadId}
      threads={threads}
      // The agent returns newest first; a transcript reads oldest first.
      history={[...history.items].reverse()}
      userInitials={initialsOf(user)}
    />
  );
}
