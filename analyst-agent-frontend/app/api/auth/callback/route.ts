import { NextResponse, type NextRequest } from "next/server";

import { whereToLand } from "@/lib/auth/landing";
import { safeNext } from "@/lib/auth/next";
import { env } from "@/lib/env";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

/**
 * Where Google sends someone back, by way of Supabase.
 *
 * A route handler, because finishing sign-in means writing the session cookies. It sits under
 * /api so `proxy.ts` leaves it alone: there is no session to check until this has run.
 */
export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  const code = params.get("code");
  const next = safeNext(params.get("next"));

  // Google reports a cancelled or refused consent as `error` rather than a code.
  if (!code || params.has("error")) return failed();

  const supabase = await createClient();
  const { data, error } = await supabase.auth.exchangeCodeForSession(code);
  if (error || !data.session) return failed();

  const landing = await whereToLand({ accessToken: data.session.access_token, next });
  return NextResponse.redirect(new URL(landing, env.APP_URL));
}

function failed() {
  return NextResponse.redirect(new URL("/login?error=google", env.APP_URL));
}
