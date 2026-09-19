import "server-only";

import { cache } from "react";

import { agentFetch } from "./agent-client";

/**
 * Whether the agent answers at all, asked once per render and given five seconds.
 *
 * On a plan that sleeps when idle, the agent takes about a minute to wake. Without this, every
 * read on the page waits out its own timeout and then renders empty, which reads as "you have
 * no account and no connections" rather than "not yet". The layout asks first and shows the
 * agent waking instead; each page asks too, because Next renders a page alongside its layout
 * whether or not the layout shows it. `cache` makes all of that one request.
 */
export const agentAwake = cache(async (): Promise<boolean> => {
  try {
    return (await agentFetch("/health", { timeoutMs: 5_000 })).ok;
  } catch {
    return false;
  }
});
