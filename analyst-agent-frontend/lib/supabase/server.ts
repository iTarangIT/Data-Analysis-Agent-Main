import "server-only";

import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

import { env } from "@/lib/env";

/**
 * How the Supabase session cookies are written.
 *
 * httpOnly, unlike Supabase's default, because nothing in the browser reads them: this app
 * never creates a browser client. Every sign-in, refresh and sign-out happens in a server
 * action, a route handler or the proxy, so the session stays out of reach of page scripts.
 */
export const SESSION_COOKIE_OPTIONS = {
  httpOnly: true,
  secure: process.env.NODE_ENV === "production",
  // Lax, not strict: a link into the app from elsewhere should not land on the sign-in page
  // for someone who is already signed in, and the OAuth return is a top-level navigation.
  sameSite: "lax",
  path: "/",
} as const;

/**
 * A Supabase client over this request's cookies, for server components, server actions and
 * route handlers. Create one per request; it is only a configured fetch.
 */
export async function createClient() {
  const jar = await cookies();

  return createServerClient(env.SUPABASE_URL, env.SUPABASE_PUBLISHABLE_KEY, {
    cookieOptions: SESSION_COOKIE_OPTIONS,
    cookies: {
      getAll: () => jar.getAll(),
      setAll(toSet) {
        try {
          for (const { name, value, options } of toSet) jar.set(name, value, options);
        } catch {
          // A server component cannot write cookies. That is safe to ignore: `proxy.ts` has
          // already refreshed the session before any page renders.
        }
      },
    },
  });
}
