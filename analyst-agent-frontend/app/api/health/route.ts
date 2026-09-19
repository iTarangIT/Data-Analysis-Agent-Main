import "server-only";

import { agentFetch } from "@/lib/api/agent-client";
import { getSession } from "@/lib/auth/dal";

export const dynamic = "force-dynamic";

/**
 * Whether the agent is awake, for the panel that waits while it wakes.
 *
 * Waits up to two minutes: once the agent is waking, the host holds requests to it until it is
 * up, which takes a minute or more. This request does not start the wake - the host turns away
 * a request from this server to a sleeping service at once - so the panel has the browser do
 * that.
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
