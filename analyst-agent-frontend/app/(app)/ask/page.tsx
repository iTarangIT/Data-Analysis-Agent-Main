import { randomUUID } from "node:crypto";

import { AskWorkspace } from "@/components/ask/ask-workspace";
import { agentJson } from "@/lib/api/agent-client";
import type { Connection } from "@/lib/api/types";
import { requireSession } from "@/lib/auth/dal";

export const metadata = { title: "Ask" };
export const dynamic = "force-dynamic";

export default async function AskPage() {
  const session = await requireSession("/ask");

  // Read straight from the agent. Going through our own route handler would add a round trip
  // between the handler and this render for nothing.
  let connections: Connection[] = [];
  try {
    connections = await agentJson<Connection[]>("/connections", {
      token: session.accessToken,
    });
  } catch {
    // An unreachable agent should still render the page; the composer will say why.
  }

  // One id per conversation, minted here so every follow-up reuses it. That is what makes the
  // agent replay the earlier turns rather than answering in isolation.
  return (
    <AskWorkspace
      connections={connections.filter((c) => c.kind !== "web")}
      threadId={randomUUID()}
    />
  );
}
