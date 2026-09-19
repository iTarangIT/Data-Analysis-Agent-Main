import "server-only";

import { agentFetch } from "@/lib/api/agent-client";
import { getSession } from "@/lib/auth/dal";

export const dynamic = "force-dynamic";

/**
 * Whether the agent is awake, for the panel that waits while it wakes.
 *
 * Each call gives up after ten seconds and the panel simply asks again, so a waking agent
 * shows up within a few seconds of answering rather than after one long request times out.
 */
export async function GET() {
  const session = await getSession();
  if (!session) {
    return Response.json({ error: "your session has ended", code: "unauthorized" }, { status: 401 });
  }

  try {
    const response = await agentFetch("/health", { timeoutMs: 10_000 });
    return Response.json({ awake: response.ok }, { status: response.ok ? 200 : 503 });
  } catch {
    return Response.json({ awake: false }, { status: 503 });
  }
}
