import "server-only";

import { revalidatePath } from "next/cache";

import { agentJson } from "@/lib/api/agent-client";
import { failureResponse } from "@/lib/api/errors";
import { requireSessionOr401 } from "@/lib/auth/dal";

export const dynamic = "force-dynamic";

export async function POST(
  _request: Request,
  ctx: RouteContext<"/api/connections/[connectionId]/sync">,
) {
  try {
    const session = await requireSessionOr401();
    const { connectionId } = await ctx.params;

    const queued = await agentJson<unknown>(
      `/connections/${encodeURIComponent(connectionId)}/sync`,
      { method: "POST", token: session.accessToken },
    );

    revalidatePath(`/connections/${connectionId}/tables`);
    revalidatePath("/connections");
    revalidatePath("/ask");
    return Response.json(queued, { status: 202 });
  } catch (error) {
    return failureResponse(error, "could not start a sync");
  }
}
