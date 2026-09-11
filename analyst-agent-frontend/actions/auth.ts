"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { z } from "zod";

import { agentJson } from "@/lib/api/agent-client";
import { ApiError } from "@/lib/api/errors";
import type { AuthResponse } from "@/lib/api/types";
import { REFRESH_COOKIE, clearedCookies, sessionCookies } from "@/lib/auth/cookies";

/**
 * Sign-in, sign-up and sign-out.
 *
 * Server actions rather than route handlers because each one has to set an httpOnly cookie
 * and then navigate, which is exactly what a server function can do and a client-side submit
 * cannot. They also work before the page has hydrated.
 *
 * Errors are returned, never thrown. A thrown error in a form action becomes an error page;
 * what the person needs is the form again, with the problem named on it.
 */

export type FormState = {
  message?: string;
  fieldErrors?: Record<string, string>;
};

const LoginSchema = z.object({
  email: z.email({ error: "Enter a valid email address." }).trim(),
  password: z.string().min(1, { error: "Enter your password." }),
});

const RegisterSchema = z.object({
  email: z.email({ error: "Enter a valid email address." }).trim(),
  password: z
    .string()
    .min(12, { error: "Use at least 12 characters." })
    .max(128, { error: "Use at most 128 characters." }),
  name: z.string().max(200).optional(),
  tenant_name: z
    .string()
    .min(1, { error: "Name your organisation." })
    .max(200)
    .optional(),
});

/** Same-origin only, or a crafted `next` would send a freshly signed-in person elsewhere. */
function safeNext(value: FormDataEntryValue | null): string {
  const next = typeof value === "string" ? value : "";
  if (!next.startsWith("/") || next.startsWith("//")) return "/ask";
  return next;
}

function flatten(error: z.ZodError): Record<string, string> {
  const out: Record<string, string> = {};
  for (const issue of error.issues) {
    const key = String(issue.path[0] ?? "form");
    if (!out[key]) out[key] = issue.message;
  }
  return out;
}

async function writeSession(auth: AuthResponse) {
  const jar = await cookies();
  for (const cookie of sessionCookies(auth)) {
    jar.set(cookie.name, cookie.value, cookie.options);
  }
}

export async function login(_prev: FormState, formData: FormData): Promise<FormState> {
  const parsed = LoginSchema.safeParse({
    email: formData.get("email"),
    password: formData.get("password"),
  });
  if (!parsed.success) return { fieldErrors: flatten(parsed.error) };

  try {
    const auth = await agentJson<AuthResponse>("/auth/login", {
      method: "POST",
      body: parsed.data,
    });
    await writeSession(auth);
  } catch (error) {
    const api = error as ApiError;
    // One message whatever went wrong, matching the agent. Saying "no such account" here
    // would undo the enumeration protection it goes to the trouble of providing.
    return {
      message:
        api.status === 401
          ? "That email and password do not match an account."
          : (api.message ?? "Could not sign in. Try again."),
    };
  }

  // Outside the try: redirect works by throwing, so catching it here would swallow it.
  redirect(safeNext(formData.get("next")));
}

export async function register(_prev: FormState, formData: FormData): Promise<FormState> {
  const parsed = RegisterSchema.safeParse({
    email: formData.get("email"),
    password: formData.get("password"),
    tenant_name: formData.get("tenant_name") || undefined,
    name: formData.get("name") || undefined,
  });
  if (!parsed.success) return { fieldErrors: flatten(parsed.error) };

  try {
    const auth = await agentJson<AuthResponse>("/auth/register", {
      method: "POST",
      body: parsed.data,
    });
    await writeSession(auth);
  } catch (error) {
    const api = error as ApiError;
    if (api.status === 409) {
      return { fieldErrors: { email: "An account with that email already exists." } };
    }
    if (api.fieldErrors && Object.keys(api.fieldErrors).length > 0) {
      return { fieldErrors: api.fieldErrors };
    }
    return { message: api.message ?? "Could not create the account. Try again." };
  }

  redirect("/ask");
}

export async function logout() {
  const jar = await cookies();
  const refresh = jar.get(REFRESH_COOKIE)?.value;

  if (refresh) {
    try {
      await agentJson("/auth/logout", { method: "POST", body: { refresh_token: refresh } });
    } catch {
      // The session is ending either way. Failing to reach the agent must not strand someone
      // on a page they are trying to leave.
    }
  }

  for (const cookie of clearedCookies()) {
    jar.set(cookie.name, cookie.value, cookie.options);
  }
  redirect("/login");
}
