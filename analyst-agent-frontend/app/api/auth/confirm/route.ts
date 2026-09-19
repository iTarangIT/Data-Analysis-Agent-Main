import type { EmailOtpType } from "@supabase/supabase-js";
import { NextResponse, type NextRequest } from "next/server";

import { whereToLand } from "@/lib/auth/landing";
import { env } from "@/lib/env";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

// A sign-up confirmation, and nothing else: a recovery or email-change link must not arrive
// here and quietly sign someone in.
const CONFIRMATIONS = new Set<EmailOtpType>(["email", "signup"]);

/**
 * The link in the confirmation email.
 *
 * Verified by its token hash rather than a PKCE code, so the link works in whichever browser
 * opens it, not only the one that signed up. That needs the Supabase "Confirm signup" template
 * to link here with `token_hash` and `type`.
 */
export async function GET(request: NextRequest) {
  const tokenHash = request.nextUrl.searchParams.get("token_hash");
  const type = request.nextUrl.searchParams.get("type") as EmailOtpType | null;

  if (!tokenHash || !type || !CONFIRMATIONS.has(type)) return failed();

  const supabase = await createClient();
  const { data, error } = await supabase.auth.verifyOtp({ type, token_hash: tokenHash });
  if (error || !data.session) return failed();

  const tenantName = data.user?.user_metadata?.tenant_name;
  const landing = await whereToLand({
    accessToken: data.session.access_token,
    next: "/ask",
    tenantName: typeof tenantName === "string" ? tenantName : undefined,
  });
  return NextResponse.redirect(new URL(landing, env.APP_URL));
}

function failed() {
  return NextResponse.redirect(new URL("/login?error=confirm", env.APP_URL));
}
