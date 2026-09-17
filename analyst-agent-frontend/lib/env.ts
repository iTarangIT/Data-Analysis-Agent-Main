import "server-only";

import { z } from "zod";

/**
 * Server-side configuration.
 *
 * Nothing here carries a NEXT_PUBLIC_ prefix, so none of it reaches the browser bundle. That
 * is the whole point: if the browser learned the agent's origin it could call it directly,
 * and the token-handling boundary this app exists to provide would be pointless. Supabase is
 * the same: every call to it is made from the server, so the browser never holds a session.
 *
 * The `server-only` import turns an accidental client import into a build error rather than a
 * silent leak.
 */
const schema = z.object({
  AGENT_API_URL: z.url(),
  // Applies to the JSON calls only. The run stream is long-lived and sets its own ceiling.
  AGENT_API_TIMEOUT_MS: z.coerce.number().int().positive().default(10_000),
  SUPABASE_URL: z.url(),
  SUPABASE_PUBLISHABLE_KEY: z.string().min(1),
  // Where this app is reached, for the links Supabase sends people back to after Google and
  // after an email confirmation. Must be on the project's redirect allow list.
  APP_URL: z.url().default("http://localhost:3000"),
});

export const env = schema.parse({
  AGENT_API_URL: process.env.AGENT_API_URL,
  AGENT_API_TIMEOUT_MS: process.env.AGENT_API_TIMEOUT_MS,
  SUPABASE_URL: process.env.SUPABASE_URL,
  SUPABASE_PUBLISHABLE_KEY: process.env.SUPABASE_PUBLISHABLE_KEY,
  APP_URL: process.env.APP_URL,
});
