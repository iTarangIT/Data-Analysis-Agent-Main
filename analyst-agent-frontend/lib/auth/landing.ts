import "server-only";

import { agentJson } from "@/lib/api/agent-client";
import { ApiError } from "@/lib/api/errors";

/**
 * Where someone goes the moment Supabase has signed them in.
 *
 * Signing in proves who they are; it does not make them a member of anything. A first-time
 * Google user has no organisation, so they are sent to name one. Someone who confirmed an email
 * sign-up already named theirs on the form, so it is created here rather than asked for twice.
 */
export async function whereToLand({
  accessToken,
  next,
  tenantName,
}: {
  accessToken: string;
  next: string;
  tenantName?: string;
}): Promise<string> {
  try {
    await agentJson("/auth/me", { token: accessToken });
    return next;
  } catch (error) {
    if (!(error instanceof ApiError) || error.code !== "onboarding_required") return next;
  }

  const name = tenantName?.trim();
  if (name) {
    try {
      await agentJson("/auth/provision", {
        method: "POST",
        token: accessToken,
        body: { tenant_name: name },
      });
      return next;
    } catch (error) {
      if (error instanceof ApiError && error.code === "conflict") return next;
    }
  }

  return next === "/ask" ? "/welcome" : `/welcome?next=${encodeURIComponent(next)}`;
}
