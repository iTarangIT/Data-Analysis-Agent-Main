import { randomUUID } from "node:crypto";

import { AskWorkspace } from "@/components/ask/ask-workspace";
import { agentJson } from "@/lib/api/agent-client";
import { agentAwake } from "@/lib/api/agent-awake";
import type { Connection, RunPage } from "@/lib/api/types";
import { requireSession } from "@/lib/auth/dal";

export const metadata = { title: "Ask" };
export const dynamic = "force-dynamic";

export default async function AskPage({ searchParams }: PageProps<"/ask">) {
  const session = await requireSession("/ask");
  // The layout shows the agent waking; nothing here could load until it has.
  if (!(await agentAwake())) return null;
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
  // between the handler and this render for nothing. Neither is load-bearing: an unreachable
  // agent still renders the page, which says so rather than showing an empty list that reads
  // as "you have no connections". The thread list is the sidebar's, read by the layout.
  const [{ connections, unreachable }, history] = await Promise.all([
    agentJson<Connection[]>("/connections", { token: session.accessToken }).then(
      (connections) => ({ connections, unreachable: false }),
      () => ({ connections: [] as Connection[], unreachable: true }),
    ),
    continuing
      ? agentJson<RunPage>(
          `/runs?limit=50&thread_id=${encodeURIComponent(threadId)}`,
          { token: session.accessToken },
        ).catch((): RunPage => ({ items: [], next_cursor: null }))
      : Promise.resolve<RunPage>({ items: [], next_cursor: null }),
  ]);

  return (
    <AskWorkspace
      // Keyed on the thread, so opening another conversation starts from a clean transcript
      // rather than carrying this sitting's turns into it. And on whether the agent answered,
      // so a retry that reaches it remounts and picks a connection from the ones it returned.
      key={unreachable ? `${threadId}:unreachable` : threadId}
      connections={connections}
      unreachable={unreachable}
      threadId={threadId}
      // The agent returns newest first; a transcript reads oldest first.
      history={[...history.items].reverse()}
    />
  );
}
