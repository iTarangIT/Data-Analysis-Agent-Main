import "server-only";

import { cache } from "react";
import { redirect } from "next/navigation";

import { agentJson } from "@/lib/api/agent-client";
import { ApiError } from "@/lib/api/errors";
import type { User } from "@/lib/api/types";
import { createClient } from "@/lib/supabase/server";

/**
 * The data access layer.
 *
 * `proxy.ts` refreshes the session and redirects signed-out navigations, but it runs only for
 * pages. So this is the real gate, and **every server component, server action and route
 * handler calls it**. A server action in particular is reachable by a direct POST, not only
 * through the form that renders it.
 *
 * Wrapped in React's `cache` so one render asks once, however many components need it.
 */

export type Session = {
  /** The Supabase access token, which the agent verifies itself. */
  accessToken: string;
  email: string | null;
};

/**
 * The current session, verified, and refreshed if it had expired.
 *
 * Returns null rather than redirecting, so a route handler can answer 401 and a page can
 * redirect, each as appropriate.
 */
export const getSession = cache(async (): Promise<Session | null> => {
  const supabase = await createClient();

  // Verifies the token's signature, refreshing it first when it has expired. Only after this
  // is the session read from the cookie trustworthy.
  const { data: verified, error } = await supabase.auth.getClaims();
  if (error || !verified?.claims) return null;

  const {
    data: { session },
  } = await supabase.auth.getSession();
  if (!session) return null;

  return { accessToken: session.access_token, email: verified.claims.email ?? null };
});

/** For pages: a session, or a redirect to sign in that comes back here afterwards. */
export async function requireSession(returnTo?: string): Promise<Session> {
  const session = await getSession();
  if (session) return session;

  const next = returnTo ? `?next=${encodeURIComponent(returnTo)}` : "";
  redirect(`/login${next}`);
}

/** For route handlers and server actions: a session, or an ApiError the caller renders. */
export async function requireSessionOr401(): Promise<Session> {
  const session = await getSession();
  if (!session) throw new ApiError("your session has ended", 401, "unauthorized");
  return session;
}

type Membership =
  | { status: "member"; user: User }
  | { status: "onboarding" }
  | { status: "unknown" };

/** Whether the signed-in person belongs to an organisation yet, as the agent sees it. */
export const getMembership = cache(async (): Promise<Membership> => {
  const session = await getSession();
  if (!session) return { status: "unknown" };
  try {
    const user = await agentJson<User>("/auth/me", { token: session.accessToken });
    return { status: "member", user };
  } catch (error) {
    if (error instanceof ApiError && error.code === "onboarding_required") {
      return { status: "onboarding" };
    }
    return { status: "unknown" };
  }
});

/** The signed-in person, or null when the agent could not say. */
export const getCurrentUser = cache(async (): Promise<User | null> => {
  const membership = await getMembership();
  return membership.status === "member" ? membership.user : null;
});

/**
 * For the app's pages: a session and, when the agent can say, the person behind it. Someone
 * signed in with no organisation yet is sent to name one first.
 *
 * An unreachable agent still renders the page, with no user, so it can explain itself.
 */
export async function requireMember(
  returnTo?: string,
): Promise<{ session: Session; user: User | null }> {
  const session = await requireSession(returnTo);
  const membership = await getMembership();
  if (membership.status === "onboarding") redirect("/welcome");
  return { session, user: membership.status === "member" ? membership.user : null };
}
