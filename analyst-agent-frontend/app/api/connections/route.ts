import "server-only";

import { agentJson } from "@/lib/api/agent-client";
import { ApiError } from "@/lib/api/errors";
import type { Connection } from "@/lib/api/types";
import { getSession } from "@/lib/auth/dal";

export const dynamic = "force-dynamic";

/**
 * Revalidation only.
 *
 * Pages read connections directly from the agent in their server component, because fetching
 * through your own route handler adds a round trip for nothing. This exists so a client
 * component can refresh the list after a change without a navigation.
 */
export async function GET() {
  const session = await getSession();
  if (!session) {
    return Response.json({ error: "your session has ended", code: "unauthorized" }, { status: 401 });
  }

  try {
    return Response.json(
      await agentJson<Connection[]>("/connections", { token: session.accessToken }),
    );
  } catch (error) {
    const api = error as ApiError;
    return Response.json(
      { error: api.message ?? "could not load connections", code: api.code ?? "unknown" },
      { status: api.status ?? 500 },
    );
  }
}
