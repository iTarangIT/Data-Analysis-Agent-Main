import "server-only";

import { revalidatePath } from "next/cache";

import { DatasetSourcesSchema } from "@/features/connections/google";
import { agentJson } from "@/lib/api/agent-client";
import { failureResponse } from "@/lib/api/errors";
import { requireSessionOr401 } from "@/lib/auth/dal";

export const dynamic = "force-dynamic";

export async function DELETE(
  _request: Request,
  ctx: RouteContext<"/api/connections/[connectionId]/sources/[sourceId]">,
) {
  try {
    const session = await requireSessionOr401();
    const { connectionId, sourceId } = await ctx.params;

    const sources = await agentJson<unknown>(
      `/connections/${encodeURIComponent(connectionId)}/sources/${encodeURIComponent(sourceId)}`,
      { method: "DELETE", token: session.accessToken, timeoutMs: 20_000 },
    );

    revalidatePath(`/connections/${connectionId}/tables`);
    revalidatePath("/connections");
    revalidatePath("/ask");
    return Response.json(DatasetSourcesSchema.parse(sources));
  } catch (error) {
    return failureResponse(error, "could not remove that source");
  }
}
