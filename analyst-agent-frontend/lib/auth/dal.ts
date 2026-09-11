import "server-only";

import { cache } from "react";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { agentJson } from "@/lib/api/agent-client";
import { ApiError } from "@/lib/api/errors";
import type { User } from "@/lib/api/types";

import { ACCESS_COOKIE, REFRESH_COOKIE, isFresh, sessionCookies } from "./cookies";
import { refreshSession } from "./tokens";

/**
 * The data access layer.
 *
 * `proxy.ts` does an optimistic cookie check and nothing more, which is all Next's own
 * guidance allows it to do. So this is the real gate, and **every server component, server
 * action and route handler calls it**. A server action in particular is reachable by a direct
 * POST, not only through the form that renders it.
 *
 * Wrapped in React's `cache` so one render asks once, however many components need it.
 */

export type Session = {
  accessToken: string;
  /** Set when the token was rotated here and the caller must write the new cookies. */
  rotated?: ReturnType<typeof sessionCookies>;
};

/**
 * The current access token, refreshed if it is close to expiring.
 *
 * Returns null rather than redirecting, so a route handler can answer 401 and a page can
 * redirect, each as appropriate.
 */
export const getSession = cache(async (): Promise<Session | null> => {
  const jar = await cookies();
  const access = jar.get(ACCESS_COOKIE)?.value;
  if (access && isFresh(access)) return { accessToken: access };

  const refresh = jar.get(REFRESH_COOKIE)?.value;
  if (!refresh) return null;

  try {
    const auth = await refreshSession(refresh);
    return { accessToken: auth.access_token, rotated: sessionCookies(auth) };
  } catch {
    // The refresh token was revoked, expired, or replayed. Either way there is no session.
    return null;
  }
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

/** The signed-in person. Returns null when the token names no user, which /auth/me 404s on. */
export const getCurrentUser = cache(async (): Promise<User | null> => {
  const session = await getSession();
  if (!session) return null;
  try {
    return await agentJson<User>("/auth/me", { token: session.accessToken });
  } catch {
    return null;
  }
});
