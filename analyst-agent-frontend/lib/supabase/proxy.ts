import "server-only";

import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

import { env } from "@/lib/env";

import { SESSION_COOKIE_OPTIONS } from "./server";

const CACHE_HEADERS = ["cache-control", "expires", "pragma"];

/**
 * Verify, and if need be refresh, the session on a navigation.
 *
 * Server components cannot write cookies, so this is where an expired access token is swapped
 * for a fresh one: the new cookies go onto the request, for the page about to render, and onto
 * the response, for the browser. `signedIn` comes from `getClaims()`, which checks the token's
 * signature against the project's public keys; the cookie alone proves nothing.
 */
export async function updateSession(request: NextRequest) {
  let response = NextResponse.next({ request });

  const supabase = createServerClient(env.SUPABASE_URL, env.SUPABASE_PUBLISHABLE_KEY, {
    cookieOptions: SESSION_COOKIE_OPTIONS,
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll(toSet, headers) {
        for (const { name, value } of toSet) request.cookies.set(name, value);
        response = NextResponse.next({ request });
        for (const { name, value, options } of toSet) response.cookies.set(name, value, options);
        // A response that sets a session must never be cached and served to someone else.
        for (const [key, value] of Object.entries(headers)) response.headers.set(key, value);
      },
    },
  });

  // Nothing may run between creating the client and this call, or a refresh can be lost.
  const { data } = await supabase.auth.getClaims();

  return {
    response,
    signedIn: Boolean(data?.claims),
    /** Any other response returned instead of `response` must carry the refreshed session. */
    carrySession(to: NextResponse): NextResponse {
      for (const cookie of response.cookies.getAll()) to.cookies.set(cookie);
      for (const key of CACHE_HEADERS) {
        const value = response.headers.get(key);
        if (value) to.headers.set(key, value);
      }
      return to;
    },
  };
}
