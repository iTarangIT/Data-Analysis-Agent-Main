import "server-only";

import { env } from "@/lib/env";

import { ApiError, normalizeAgentError } from "./errors";

/**
 * The one place an Authorization header is attached.
 *
 * Everything the browser sees goes through a route handler or a server action; neither hands
 * the token onward. Keeping the header in a single `server-only` module is what makes that
 * claim checkable rather than aspirational.
 */

type Options = {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  token?: string;
  signal?: AbortSignal;
  /** Streaming calls set their own ceiling; the default applies to JSON only. */
  timeoutMs?: number;
};

function headers(options: Options): HeadersInit {
  const out: Record<string, string> = { accept: "application/json" };
  if (options.body !== undefined && !(options.body instanceof FormData)) {
    out["content-type"] = "application/json";
  }
  if (options.token) out.authorization = `Bearer ${options.token}`;
  return out;
}

function encode(body: unknown): BodyInit | undefined {
  if (body === undefined || body instanceof FormData) return body;
  return JSON.stringify(body);
}

/** Perform the call, mapping anything that is not a response into an ApiError. */
export async function agentFetch(path: string, options: Options = {}): Promise<Response> {
  const timeout = AbortSignal.timeout(options.timeoutMs ?? env.AGENT_API_TIMEOUT_MS);
  const signal = options.signal
    ? AbortSignal.any([options.signal, timeout])
    : timeout;

  try {
    return await fetch(`${env.AGENT_API_URL}${path}`, {
      method: options.method ?? "GET",
      headers: headers(options),
      body: encode(options.body),
      signal,
      // Every read here is per-tenant and request-time. Caching one would serve one
      // customer's connections to another.
      cache: "no-store",
    });
  } catch (error) {
    if (options.signal?.aborted) throw error; // the caller went away; not our error to report
    const aborted = error instanceof Error && error.name === "TimeoutError";
    throw new ApiError(
      aborted ? "the analyst service did not respond in time" : "could not reach the analyst service",
      504,
      "upstream",
    );
  }
}

/** Call and parse, throwing a normalized ApiError on any non-2xx. */
export async function agentJson<T>(path: string, options: Options = {}): Promise<T> {
  const response = await agentFetch(path, options);
  if (!response.ok) throw await normalizeAgentError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
