import "server-only";

import { z } from "zod";

import { DriveListingSchema } from "@/features/connections/google";
import { agentJson } from "@/lib/api/agent-client";
import { ApiError, failureResponse } from "@/lib/api/errors";
import { requireSessionOr401 } from "@/lib/auth/dal";

export const dynamic = "force-dynamic";

const TreeQuery = z.object({
  source_id: z.string().min(1).max(200),
  folder_id: z.string().min(1).max(200).optional(),
});

export async function GET(
  request: Request,
  ctx: RouteContext<"/api/connections/[connectionId]/google/tree">,
) {
  try {
    const session = await requireSessionOr401();
    const { connectionId } = await ctx.params;
    const search = new URL(request.url).searchParams;
    const parsed = TreeQuery.safeParse({
      source_id: search.get("source_id") ?? undefined,
      folder_id: search.get("folder_id") ?? undefined,
    });
    if (!parsed.success) {
      throw new ApiError("That folder could not be read.", 422, "invalid_request");
    }

    const query = new URLSearchParams({ source_id: parsed.data.source_id });
    if (parsed.data.folder_id) query.set("folder_id", parsed.data.folder_id);
    const listing = await agentJson<unknown>(
      `/connections/${encodeURIComponent(connectionId)}/google/tree?${query}`,
      { token: session.accessToken, timeoutMs: 30_000 },
    );

    return Response.json(DriveListingSchema.parse(listing));
  } catch (error) {
    return failureResponse(error, "could not list that folder");
  }
}
