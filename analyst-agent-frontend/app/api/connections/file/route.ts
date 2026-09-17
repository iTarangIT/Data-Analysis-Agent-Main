import "server-only";

import { revalidatePath } from "next/cache";
import { z } from "zod";

import { UploadedFiles } from "@/features/connections/uploads";
import { agentJson } from "@/lib/api/agent-client";
import { ApiError, failureResponse } from "@/lib/api/errors";
import type { Connection } from "@/lib/api/types";
import { requireSessionOr401 } from "@/lib/auth/dal";

export const dynamic = "force-dynamic";
export const maxDuration = 120;

const Dataset = z.object({
  name: z.string().trim().min(1, { error: "Name this dataset." }).max(200),
  files: UploadedFiles,
});

export async function POST(request: Request) {
  try {
    const session = await requireSessionOr401();
    const form = await request.formData().catch(() => null);
    const parsed = Dataset.safeParse({ name: form?.get("name"), files: form?.getAll("files") });
    if (!parsed.success) {
      throw new ApiError(
        parsed.error.issues[0]?.message ?? "That upload could not be read.",
        422,
        "invalid_request",
      );
    }

    const upstream = new FormData();
    upstream.set("name", parsed.data.name);
    for (const file of parsed.data.files) upstream.append("files", file, file.name);

    const connection = await agentJson<Connection>("/connections/file", {
      method: "POST",
      token: session.accessToken,
      body: upstream,
      timeoutMs: 120_000,
    });

    revalidatePath("/connections");
    revalidatePath("/ask");
    return Response.json(connection, { status: 201 });
  } catch (error) {
    return failureResponse(error, "could not add that dataset");
  }
}
