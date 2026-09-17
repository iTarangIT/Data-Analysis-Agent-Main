"use server";

import type { AuthError } from "@supabase/supabase-js";
import { redirect } from "next/navigation";

import { agentJson } from "@/lib/api/agent-client";
import { ApiError } from "@/lib/api/errors";
import { requireSession } from "@/lib/auth/dal";
import { fieldErrors, LoginSchema, RegisterSchema, WelcomeSchema } from "@/lib/auth/forms";
import { whereToLand } from "@/lib/auth/landing";
import { safeNext } from "@/lib/auth/next";
import { env } from "@/lib/env";
import { createClient } from "@/lib/supabase/server";

/**
 * Sign-in, sign-up, sign-out, and naming an organisation.
 *
 * Server actions rather than route handlers because each one has to write session cookies and
 * then navigate, which is exactly what a server function can do and a client-side submit
 * cannot. They also work before the page has hydrated.
 *
 * Errors are returned, never thrown. A thrown error in a form action becomes an error page;
 * what the person needs is the form again, with the problem named on it.
 */

export type FormState = {
  message?: string;
  fieldErrors?: Record<string, string>;
  /**
   * What was submitted, echoed back so the form can refill itself.
   *
   * React resets an uncontrolled form once its action completes, so without this a failed
   * sign-up silently wipes everything the person typed. Passwords are never echoed.
   */
  values?: Record<string, string>;
};

/** Every non-secret field, so a rejected form comes back filled in. */
function keep(formData: FormData, fields: string[]): Record<string, string> {
  const values: Record<string, string> = {};
  for (const field of fields) {
    const value = formData.get(field);
    if (typeof value === "string") values[field] = value;
  }
  return values;
}

/** Supabase's rate limits apply per IP and per project, and read differently to a person. */
function isRateLimited(error: AuthError): boolean {
  return error.status === 429 || (error.code ?? "").startsWith("over_");
}

export async function login(_prev: FormState, formData: FormData): Promise<FormState> {
  const parsed = LoginSchema.safeParse({
    email: formData.get("email"),
    password: formData.get("password"),
  });
  const typed = keep(formData, ["email"]);
  if (!parsed.success) return { fieldErrors: fieldErrors(parsed.error), values: typed };

  const supabase = await createClient();
  const { error } = await supabase.auth.signInWithPassword(parsed.data);

  if (error) {
    if (error.code === "email_not_confirmed") {
      return {
        values: typed,
        message: "Confirm your email address first. The link is in your inbox.",
      };
    }
    if (isRateLimited(error)) {
      return { values: typed, message: "Too many attempts. Wait a minute and try again." };
    }
    // One message for a wrong password and an unknown address alike. Saying which would tell
    // anyone whether an address has an account.
    return {
      values: typed,
      message:
        error.code === "invalid_credentials"
          ? "That email and password do not match an account."
          : "Could not sign in. Try again.",
    };
  }

  // Outside any try: redirect works by throwing. The app layout sends someone with no
  // organisation to /welcome from wherever this lands.
  redirect(safeNext(formData.get("next")));
}

export async function register(_prev: FormState, formData: FormData): Promise<FormState> {
  const parsed = RegisterSchema.safeParse({
    email: formData.get("email"),
    password: formData.get("password"),
    tenant_name: formData.get("tenant_name"),
  });
  const typed = keep(formData, ["email", "tenant_name"]);
  if (!parsed.success) return { fieldErrors: fieldErrors(parsed.error), values: typed };

  const { email, password, tenant_name } = parsed.data;
  const supabase = await createClient();
  const { data, error } = await supabase.auth.signUp({
    email,
    password,
    options: {
      emailRedirectTo: `${env.APP_URL}/api/auth/confirm`,
      // Kept on the Supabase user until the address is confirmed, then used to create the
      // organisation, so the name is not asked for a second time.
      data: { tenant_name },
    },
  });

  if (error) {
    if (error.code === "weak_password") {
      return { values: typed, fieldErrors: { password: error.message } };
    }
    if (error.code === "user_already_exists" || error.code === "email_exists") {
      return { values: typed, fieldErrors: { email: "An account with that email already exists." } };
    }
    if (isRateLimited(error)) {
      return { values: typed, message: "Too many sign-ups just now. Try again in a little while." };
    }
    return { values: typed, message: "Could not create the account. Try again." };
  }

  // A session straight away means the project does not require confirming the address.
  if (data.session) {
    redirect(
      await whereToLand({ accessToken: data.session.access_token, next: "/ask", tenantName: tenant_name }),
    );
  }

  // Supabase answers the same way for an address that already has an account, so this page
  // reveals nothing about who has signed up.
  redirect(`/register/sent?email=${encodeURIComponent(email)}`);
}

/** Starts Google's sign-in. The person comes back to /api/auth/callback. */
export async function signInWithGoogle(formData: FormData): Promise<void> {
  const next = safeNext(formData.get("next"));
  const callback = new URL("/api/auth/callback", env.APP_URL);
  if (next !== "/ask") callback.searchParams.set("next", next);

  const supabase = await createClient();
  const { data, error } = await supabase.auth.signInWithOAuth({
    provider: "google",
    options: { redirectTo: callback.toString() },
  });

  redirect(error || !data.url ? "/login?error=google" : data.url);
}

export async function createOrganisation(_prev: FormState, formData: FormData): Promise<FormState> {
  const session = await requireSession("/welcome");

  const parsed = WelcomeSchema.safeParse({ tenant_name: formData.get("tenant_name") });
  const typed = keep(formData, ["tenant_name"]);
  if (!parsed.success) return { fieldErrors: fieldErrors(parsed.error), values: typed };

  const next = safeNext(formData.get("next"));

  try {
    await agentJson("/auth/provision", {
      method: "POST",
      token: session.accessToken,
      body: parsed.data,
    });
  } catch (error) {
    const api = error instanceof ApiError ? error : null;
    if (api?.code === "conflict") {
      // A second tab or a double submit already made them a member, which is fine. An address
      // that belongs to an older account they have not proven is not, and saying so beats
      // bouncing them back to this page.
      const landing = await whereToLand({ accessToken: session.accessToken, next });
      if (!landing.startsWith("/welcome")) redirect(landing);
      return {
        values: typed,
        message:
          "This email address already has an organisation. Sign in the way you did before, or confirm the address to reach it.",
      };
    }
    if (api && Object.keys(api.fieldErrors).length > 0) {
      return { values: typed, fieldErrors: api.fieldErrors };
    }
    return {
      values: typed,
      message:
        api?.code === "forbidden"
          ? "New organisations cannot be created right now."
          : "Could not create the organisation. Try again.",
    };
  }

  redirect(next);
}

export async function logout() {
  const supabase = await createClient();
  // This device only. Signing out of a laptop should not sign the same person out of a phone.
  await supabase.auth.signOut({ scope: "local" });
  redirect("/login");
}
