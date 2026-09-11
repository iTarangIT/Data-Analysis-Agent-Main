import "server-only";

import { z } from "zod";

import { agentJson } from "@/lib/api/agent-client";
import { ApiError } from "@/lib/api/errors";
import type { Thread } from "@/lib/api/types";
import { getSession } from "@/lib/auth/dal";

export const dynamic = "force-dynamic";

const Limit = z.coerce.number().int().min(1).max(100).catch(30);

/**
 * Every conversation, for the thread column on the ask screen.
 *
 * Revalidation only, like the connections route: the ask page reads threads straight from
 * the agent when it renders. This exists so the column can refresh after a run finishes
 * without throwing away the transcript on screen.
 */
export async function GET(request: Request) {
  const session = await getSession();
  if (!session) {
    return Response.json({ error: "your session has ended", code: "unauthorized" }, { status: 401 });
  }

  const limit = Limit.parse(new URL(request.url).searchParams.get("limit"));

  try {
    return Response.json(
      await agentJson<Thread[]>(`/runs/threads?limit=${limit}`, { token: session.accessToken }),
    );
  } catch (error) {
    const api = error as ApiError;
    return Response.json(
      { error: api.message ?? "could not load threads", code: api.code ?? "unknown" },
      { status: api.status ?? 500 },
    );
  }
}
