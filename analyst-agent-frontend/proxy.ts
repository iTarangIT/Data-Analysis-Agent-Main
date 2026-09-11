import { NextResponse, type NextRequest } from "next/server";

import { ACCESS_COOKIE, REFRESH_COOKIE, isFresh } from "@/lib/auth/cookies";

/**
 * What Next 15 called middleware. Next 16 renamed the file and the export to `proxy`, and the
 * runtime is Node and cannot be configured: setting a `runtime` export here throws.
 *
 * This does an **optimistic check only**. It reads the cookie, decodes the expiry, and
 * redirects. It never calls the network and never holds module state, because it runs on every
 * navigation including prefetches and may be deployed to a CDN edge. Next's own guidance is
 * explicit that this must not be the only gate, which is why `lib/auth/dal.ts` re-checks
 * inside every server component, server action and route handler.
 *
 * Rotation cannot happen here either: cookies can only be written from a server function or a
 * route handler, so a stale token is handed to `/api/auth/refresh`, which writes the new pair
 * and sends the person on to where they were going.
 */

const PUBLIC_PATHS = new Set(["/login", "/register"]);

export async function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  const access = request.cookies.get(ACCESS_COOKIE)?.value;
  const refresh = request.cookies.get(REFRESH_COOKIE)?.value;
  const signedIn = access ? isFresh(access) : false;

  if (PUBLIC_PATHS.has(pathname)) {
    return signedIn
      ? NextResponse.redirect(new URL("/ask", request.nextUrl))
      : NextResponse.next();
  }

  if (signedIn) return NextResponse.next();

  if (refresh) {
    const refreshUrl = new URL("/api/auth/refresh", request.nextUrl);
    refreshUrl.searchParams.set("next", pathname + search);
    return NextResponse.redirect(refreshUrl);
  }

  const login = new URL("/login", request.nextUrl);
  if (pathname !== "/") login.searchParams.set("next", pathname + search);
  return NextResponse.redirect(login);
}

export const config = {
  matcher: [
    {
      // `api` is excluded on purpose. The agent is the authority for API auth, and a matched
      // path has its request body cloned and buffered in memory, which is the last thing a
      // long-running run POST needs.
      source: "/((?!api|_next/static|_next/image|favicon.ico|.*\\.svg$).*)",
      // Prefetches would otherwise fire the refresh redirect on every hovered link.
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
