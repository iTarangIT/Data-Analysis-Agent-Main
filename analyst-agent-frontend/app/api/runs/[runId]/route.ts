import "server-only";

import { agentJson } from "@/lib/api/agent-client";
import { ApiError } from "@/lib/api/errors";
import type { RunDetail } from "@/lib/api/types";
import { getSession } from "@/lib/auth/dal";

export const dynamic = "force-dynamic";

/** One past run, for a detail view opened without a navigation. */
export async function GET(_request: Request, context: RouteContext<"/api/runs/[runId]">) {
  const session = await getSession();
  if (!session) {
    return Response.json({ error: "your session has ended", code: "unauthorized" }, { status: 401 });
  }

  // Async in Next 16: params is a promise now.
  const { runId } = await context.params;

  try {
    return Response.json(
      await agentJson<RunDetail>(`/runs/${encodeURIComponent(runId)}`, {
        token: session.accessToken,
      }),
    );
  } catch (error) {
    const api = error as ApiError;
    return Response.json(
      { error: api.message ?? "could not load that run", code: api.code ?? "unknown" },
      { status: api.status ?? 500 },
    );
  }
}
