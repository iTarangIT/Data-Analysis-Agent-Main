import { NextResponse, type NextRequest } from "next/server";

import { updateSession } from "@/lib/supabase/proxy";

/**
 * What Next 15 called middleware. Next 16 renamed the file and the export to `proxy`, and the
 * runtime is Node and cannot be configured: setting a `runtime` export here throws.
 *
 * Two jobs. It keeps the Supabase session alive, because server components cannot write
 * cookies and so cannot store a refreshed token themselves; and it sends a signed-out
 * navigation to sign in before a page starts rendering. Verifying the token is local, against
 * the project's cached public keys; only an expired token costs a call to Supabase.
 *
 * It is still not the gate. Next's own guidance is explicit that this must not be the only
 * check, which is why `lib/auth/dal.ts` re-checks inside every server component, server action
 * and route handler.
 */

// Signed-out pages. A signed-in visitor is sent on to the app instead.
const PUBLIC_PATHS = new Set(["/login", "/register", "/register/sent"]);

export async function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const { response, signedIn, carrySession } = await updateSession(request);

  if (PUBLIC_PATHS.has(pathname)) {
    return signedIn ? carrySession(NextResponse.redirect(new URL("/ask", request.nextUrl))) : response;
  }

  if (signedIn) return response;

  const login = new URL("/login", request.nextUrl);
  if (pathname !== "/") login.searchParams.set("next", pathname + search);
  // Carried even here: a refresh that failed clears the dead session's cookies.
  return carrySession(NextResponse.redirect(login));
}

export const config = {
  matcher: [
    {
      // `api` is excluded on purpose. Route handlers check the session themselves, the auth
      // callbacks must run before there is one, and a matched path has its request body cloned
      // and buffered in memory, which is the last thing a long-running run POST needs.
      source: "/((?!api|_next/static|_next/image|favicon.ico|.*\\.svg$).*)",
      // Prefetches would otherwise refresh the session on every hovered link.
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
