import "server-only";

import { cookies } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";

import { REFRESH_COOKIE, clearedCookies, sessionCookies } from "@/lib/auth/cookies";
import { refreshSession } from "@/lib/auth/tokens";

export const dynamic = "force-dynamic";

/**
 * The one place a document navigation can get a rotated cookie pair written.
 *
 * `proxy.ts` cannot do this itself: Next allows cookies to be set only from a server function
 * or a route handler, and the proxy is meant to stay free of network calls. So it redirects
 * here, this rotates, and the person continues to where they were going. That costs one extra
 * round trip at most once every fifteen minutes, on navigation only.
 */
export async function GET(request: NextRequest) {
  const jar = await cookies();
  const refresh = jar.get(REFRESH_COOKIE)?.value;
  const next = safeNext(request.nextUrl.searchParams.get("next"));

  if (!refresh) return signOut(request, next);

  try {
    const auth = await refreshSession(refresh);
    const response = NextResponse.redirect(new URL(next, request.nextUrl));
    for (const cookie of sessionCookies(auth)) {
      response.cookies.set(cookie.name, cookie.value, cookie.options);
    }
    return response;
  } catch {
    return signOut(request, next);
  }
}

function signOut(request: NextRequest, next: string) {
  const login = new URL("/login", request.nextUrl);
  if (next !== "/ask") login.searchParams.set("next", next);
  const response = NextResponse.redirect(login);
  for (const cookie of clearedCookies()) {
    response.cookies.set(cookie.name, cookie.value, cookie.options);
  }
  return response;
}

/** Same-origin only. An open redirect here would be handed a valid session on arrival. */
function safeNext(value: string | null): string {
  if (!value || !value.startsWith("/") || value.startsWith("//")) return "/ask";
  return value;
}
