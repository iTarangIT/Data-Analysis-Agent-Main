import "server-only";

import { agentFetch } from "@/lib/api/agent-client";
import { getSession } from "@/lib/auth/dal";

export const dynamic = "force-dynamic";

/**
 * Whether the agent is awake, for the panel that waits while it wakes.
 *
 * Waits up to two minutes, because waking is what this request is for: the host holds a
 * request to a sleeping service while it starts, which takes a minute or more. With a ten-second
 * limit the panel was seen spinning while the agent stayed asleep, and a single request that
 * waited woke it in 72 seconds.
 */
export async function GET() {
  const session = await getSession();
  if (!session) {
    return Response.json({ error: "your session has ended", code: "unauthorized" }, { status: 401 });
  }

  try {
    const response = await agentFetch("/health", { timeoutMs: 120_000 });
    return Response.json({ awake: response.ok }, { status: response.ok ? 200 : 503 });
  } catch {
    return Response.json({ awake: false }, { status: 503 });
  }
}
