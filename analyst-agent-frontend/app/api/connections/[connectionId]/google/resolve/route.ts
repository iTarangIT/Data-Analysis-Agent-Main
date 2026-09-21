import "server-only";

import { z } from "zod";

import { ResolveResultSchema } from "@/features/connections/google";
import { agentJson } from "@/lib/api/agent-client";
import { ApiError, failureResponse } from "@/lib/api/errors";
import { requireSessionOr401 } from "@/lib/auth/dal";

export const dynamic = "force-dynamic";

const GoogleLink = z.object({
  url: z
    .string()
    .trim()
    .min(1, { error: "Paste a Google Drive or Google Sheets link." })
    .max(2000),
  confirm_unverified: z.boolean().optional(),
});

export async function POST(
  request: Request,
  ctx: RouteContext<"/api/connections/[connectionId]/google/resolve">,
) {
  try {
    const session = await requireSessionOr401();
    const { connectionId } = await ctx.params;
    const parsed = GoogleLink.safeParse(await request.json().catch(() => null));
    if (!parsed.success) {
      throw new ApiError(
        parsed.error.issues[0]?.message ?? "That link could not be read.",
        422,
        "invalid_request",
      );
    }

    const result = await agentJson<unknown>(
      `/connections/${encodeURIComponent(connectionId)}/google/resolve`,
      { method: "POST", token: session.accessToken, body: parsed.data, timeoutMs: 30_000 },
    );

    return Response.json(ResolveResultSchema.parse(result));
  } catch (error) {
    return failureResponse(error, "could not check that link");
  }
}
