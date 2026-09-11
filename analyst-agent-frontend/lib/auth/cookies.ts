import "server-only";

import type { AuthResponse } from "@/lib/api/types";

/**
 * Where the session lives.
 *
 * Two httpOnly cookies holding the agent's own tokens, with no sealing layer of our own on
 * top. The access token is already a signed JWT and the refresh token is opaque and
 * revocable; wrapping them again would buy nothing against an attacker who can read httpOnly
 * cookies, and would add a secret to rotate.
 *
 * Both are unreadable from JavaScript, which is the point: the browser never holds a token it
 * could send anywhere itself.
 */
export const ACCESS_COOKIE = "aa_at";
export const REFRESH_COOKIE = "aa_rt";

type CookieOptions = {
  httpOnly: true;
  secure: boolean;
  sameSite: "lax";
  path: string;
  maxAge: number;
};

function base(maxAge: number): CookieOptions {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    // Lax, not strict: a link into the app from elsewhere should not land on the sign-in page
    // for someone who is already signed in.
    sameSite: "lax",
    path: "/",
    maxAge,
  };
}

/** The cookie pair for a fresh sign-in or a rotation, sized by what the agent reported. */
export function sessionCookies(auth: AuthResponse) {
  return [
    { name: ACCESS_COOKIE, value: auth.access_token, options: base(auth.expires_in) },
    { name: REFRESH_COOKIE, value: auth.refresh_token, options: base(auth.refresh_expires_in) },
  ] as const;
}

/** Same names and path, zero lifetime, so the browser drops them. */
export function clearedCookies() {
  return [
    { name: ACCESS_COOKIE, value: "", options: base(0) },
    { name: REFRESH_COOKIE, value: "", options: base(0) },
  ] as const;
}

/**
 * Read the `exp` claim without verifying the signature.
 *
 * Deliberately unverified. This app has no signing secret and does not need one: the agent
 * verifies every token it is given, and this is only ever used to decide whether to bother
 * refreshing. Treat the answer as a hint, never as authorisation.
 */
export function accessTokenExpiry(token: string): number | null {
  const payload = token.split(".")[1];
  if (!payload) return null;
  try {
    const json = JSON.parse(
      Buffer.from(payload.replace(/-/g, "+").replace(/_/g, "/"), "base64").toString("utf8"),
    ) as { exp?: unknown };
    return typeof json.exp === "number" ? json.exp : null;
  } catch {
    return null;
  }
}

/**
 * Whether a token will still be valid a minute from now.
 *
 * The skew is what makes a long run safe. The agent checks the bearer once, before the stream
 * opens, so a token that is comfortably fresh at that moment carries a forty-second run to
 * completion even though it expires partway through.
 */
export function isFresh(token: string, skewSeconds = 60): boolean {
  const exp = accessTokenExpiry(token);
  if (exp === null) return false;
  return exp - skewSeconds > Math.floor(Date.now() / 1000);
}
