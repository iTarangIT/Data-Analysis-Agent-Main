import "server-only";

import { z } from "zod";

import { agentJson } from "@/lib/api/agent-client";
import { ApiError } from "@/lib/api/errors";
import type { Usage } from "@/lib/api/types";
import { getSession } from "@/lib/auth/dal";

export const dynamic = "force-dynamic";

// The agent rejects anything outside this range itself; validating here as well means a
// mistyped querystring fails as a 400 from us rather than a 422 relayed from upstream.
const Days = z.coerce.number().int().min(1).max(90).catch(30);

/**
 * The tenant's usage over a window, for the range toggle on the runs page.
 *
 * Read through the browser rather than the server component because the window is
 * something the reader changes, and refetching one aggregate is cheaper than a navigation.
 */
export async function GET(request: Request) {
  const session = await getSession();
  if (!session) {
    return Response.json({ error: "your session has ended", code: "unauthorized" }, { status: 401 });
  }

  const days = Days.parse(new URL(request.url).searchParams.get("days"));

  try {
    return Response.json(
      await agentJson<Usage>(`/usage?days=${days}`, { token: session.accessToken }),
    );
  } catch (error) {
    const api = error as ApiError;
    return Response.json(
      { error: api.message ?? "could not load usage", code: api.code ?? "unknown" },
      { status: api.status ?? 500 },
    );
  }
}
