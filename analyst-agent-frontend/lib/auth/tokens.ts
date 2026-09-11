import "server-only";

import { agentJson } from "@/lib/api/agent-client";
import type { AuthResponse } from "@/lib/api/types";

/**
 * Refresh coordination.
 *
 * Several requests can notice an expiring access token at the same moment: a page render, a
 * connections revalidation and a history poll all firing at once. Without coordination each
 * would rotate the refresh token, and every one but the winner would present an
 * already-rotated token. The agent would then have to decide whether that is theft.
 *
 * This map collapses them into one upstream call. It only works within a single Node process,
 * which is honest about its limits: the real protection is the agent's own reuse grace
 * window, which survives more than one instance. This is the cheap half of a two-part fix.
 */
const inFlight = new Map<string, Promise<AuthResponse>>();

export function refreshSession(refreshToken: string): Promise<AuthResponse> {
  const existing = inFlight.get(refreshToken);
  if (existing) return existing;

  const pending = agentJson<AuthResponse>("/auth/refresh", {
    method: "POST",
    body: { refresh_token: refreshToken },
  }).finally(() => {
    inFlight.delete(refreshToken);
  });

  inFlight.set(refreshToken, pending);
  return pending;
}
