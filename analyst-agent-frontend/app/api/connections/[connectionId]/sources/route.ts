import "server-only";

import { revalidatePath } from "next/cache";
import { z } from "zod";

import {
  DatasetSourceSchema,
  DatasetSourcesSchema,
  DryRunSchema,
} from "@/features/connections/google";
import { agentJson } from "@/lib/api/agent-client";
import { ApiError, failureResponse } from "@/lib/api/errors";
import { requireSessionOr401 } from "@/lib/auth/dal";

export const dynamic = "force-dynamic";
export const maxDuration = 60;

const SourceRules = z.object({
  source_id: z.string().min(1).max(200),
  rules: z
    .array(
      z.object({
        id: z
          .string()
          .min(1)
          .max(200)
          .regex(/^[A-Za-z0-9_-]+$/),
        kind: z.enum(["folder", "file", "sheet"]),
        recursive: z.boolean(),
      }),
    )
    .max(500),
  combine: z.boolean(),
  dry_run: z.boolean().optional(),
});

export async function GET(
  _request: Request,
  ctx: RouteContext<"/api/connections/[connectionId]/sources">,
) {
  try {
    const session = await requireSessionOr401();
    const { connectionId } = await ctx.params;

    const sources = await agentJson<unknown>(
      `/connections/${encodeURIComponent(connectionId)}/sources`,
      { token: session.accessToken },
    );

    return Response.json(DatasetSourcesSchema.parse(sources));
  } catch (error) {
    return failureResponse(error, "could not load this dataset's sources");
  }
}

export async function POST(
  request: Request,
  ctx: RouteContext<"/api/connections/[connectionId]/sources">,
) {
  try {
    const session = await requireSessionOr401();
    const { connectionId } = await ctx.params;
    const parsed = SourceRules.safeParse(await request.json().catch(() => null));
    if (!parsed.success) {
      throw new ApiError("That choice of files could not be read.", 422, "invalid_request");
    }

    const reply = await agentJson<unknown>(
      `/connections/${encodeURIComponent(connectionId)}/sources`,
      { method: "POST", token: session.accessToken, body: parsed.data, timeoutMs: 60_000 },
    );
    if (parsed.data.dry_run) return Response.json(DryRunSchema.parse(reply));

    const source = DatasetSourceSchema.parse(reply);
    revalidatePath(`/connections/${connectionId}/tables`);
    revalidatePath("/connections");
    revalidatePath("/ask");
    return Response.json(source);
  } catch (error) {
    return failureResponse(error, "could not add that source");
  }
}
