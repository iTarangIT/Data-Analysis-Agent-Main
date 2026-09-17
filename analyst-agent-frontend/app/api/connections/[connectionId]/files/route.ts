import "server-only";

import { revalidatePath } from "next/cache";

import { UploadedFiles } from "@/features/connections/uploads";
import { agentJson } from "@/lib/api/agent-client";
import { ApiError, failureResponse } from "@/lib/api/errors";
import type { ConnectionTables } from "@/lib/api/types";
import { requireSessionOr401 } from "@/lib/auth/dal";

export const dynamic = "force-dynamic";
export const maxDuration = 120;

export async function POST(
  request: Request,
  ctx: RouteContext<"/api/connections/[connectionId]/files">,
) {
  try {
    const session = await requireSessionOr401();
    const { connectionId } = await ctx.params;
    const form = await request.formData().catch(() => null);
    const parsed = UploadedFiles.safeParse(form?.getAll("files"));
    if (!parsed.success) {
      throw new ApiError(
        parsed.error.issues[0]?.message ?? "That upload could not be read.",
        422,
        "invalid_request",
      );
    }

    const upstream = new FormData();
    for (const file of parsed.data) upstream.append("files", file, file.name);

    const tables = await agentJson<ConnectionTables>(
      `/connections/${encodeURIComponent(connectionId)}/files`,
      { method: "POST", token: session.accessToken, body: upstream, timeoutMs: 120_000 },
    );

    revalidatePath(`/connections/${connectionId}/tables`);
    revalidatePath("/connections");
    revalidatePath("/ask");
    return Response.json(tables);
  } catch (error) {
    return failureResponse(error, "could not add those files");
  }
}
