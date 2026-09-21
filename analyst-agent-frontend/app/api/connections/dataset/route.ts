import "server-only";

import { revalidatePath } from "next/cache";
import { z } from "zod";

import { agentJson } from "@/lib/api/agent-client";
import { ApiError, failureResponse } from "@/lib/api/errors";
import type { Connection } from "@/lib/api/types";
import { requireSessionOr401 } from "@/lib/auth/dal";

export const dynamic = "force-dynamic";

const EmptyDataset = z.object({
  name: z.string().trim().min(1, { error: "Name this dataset." }).max(200),
});

export async function POST(request: Request) {
  try {
    const session = await requireSessionOr401();
    const parsed = EmptyDataset.safeParse(await request.json().catch(() => null));
    if (!parsed.success) {
      throw new ApiError(
        parsed.error.issues[0]?.message ?? "That name could not be read.",
        422,
        "invalid_request",
      );
    }

    const connection = await agentJson<Connection>("/connections/dataset", {
      method: "POST",
      token: session.accessToken,
      body: parsed.data,
    });

    revalidatePath("/connections");
    revalidatePath("/ask");
    return Response.json(connection, { status: 201 });
  } catch (error) {
    return failureResponse(error, "could not add that dataset");
  }
}
