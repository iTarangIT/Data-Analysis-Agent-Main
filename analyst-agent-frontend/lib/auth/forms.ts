import { z } from "zod";

/**
 * What the sign-in, sign-up and welcome forms accept, checked before anything reaches Supabase
 * or the agent. Kept apart from the server actions so the rules can be tested on their own.
 */

// Trimmed before the format check: pasted addresses often carry a trailing space.
const email = z.string().trim().pipe(z.email({ error: "Enter a valid email address." }));

const tenantName = z
  .string()
  .trim()
  .min(1, { error: "Name your organisation." })
  // The agent's column is 200 characters.
  .max(200, { error: "Use at most 200 characters." });

export const LoginSchema = z.object({
  email,
  password: z.string().min(1, { error: "Enter your password." }),
});

export const RegisterSchema = z.object({
  email,
  password: z
    .string()
    .min(12, { error: "Use at least 12 characters." })
    .max(128, { error: "Use at most 128 characters." }),
  tenant_name: tenantName,
});

export const WelcomeSchema = z.object({ tenant_name: tenantName });

/** Field name to its first message, which is what a form shows under each input. */
export function fieldErrors(error: z.ZodError): Record<string, string> {
  const out: Record<string, string> = {};
  for (const issue of error.issues) {
    const key = String(issue.path[0] ?? "form");
    if (!out[key]) out[key] = issue.message;
  }
  return out;
}
