import "server-only";

import { z } from "zod";

import { agentJson } from "@/lib/api/agent-client";
import { ApiError, normalizeAgentError } from "@/lib/api/errors";
import type { RunPage } from "@/lib/api/types";
import { getSession, requireSessionOr401 } from "@/lib/auth/dal";
import { env } from "@/lib/env";

export const dynamic = "force-dynamic";
// A run can take forty seconds and the eval harness allows two minutes, so the handler must
// outlive both. This is also why the app has to run as a long-lived Node process: a platform
// that deploys route handlers as short-lived functions will cut the stream mid-run.
export const maxDuration = 120;

const RunBody = z.object({
  connection_id: z.string().min(1),
  thread_id: z.string().min(1).max(100),
  question: z.string().min(3).max(2000),
});

const encoder = new TextEncoder();

function streamHeaders(): HeadersInit {
  // Built fresh rather than copied from upstream, which sets hop-by-hop headers that must not
  // be forwarded through a new connection.
  return {
    "content-type": "text/event-stream; charset=utf-8",
    "cache-control": "no-store, no-transform",
    // Tells nginx and friends not to buffer. We are a new hop, so the agent setting it
    // upstream does nothing for the leg between here and the browser.
    "x-accel-buffering": "no",
    "x-content-type-options": "nosniff",
    connection: "keep-alive",
  };
}

function errorResponse(error: ApiError) {
  return Response.json(
    { error: error.message, code: error.code, fieldErrors: error.fieldErrors },
    { status: error.status },
  );
}

/**
 * Stream a run from the agent to the browser.
 *
 * A route handler rather than a server action because a server action cannot return a stream
 * to a fetch caller. Bytes are forwarded exactly as they arrive: decoding and re-framing here
 * would corrupt a multi-byte character split across a chunk boundary, for no benefit.
 */
export async function POST(request: Request) {
  let session;
  try {
    session = await requireSessionOr401();
  } catch (error) {
    return errorResponse(error as ApiError);
  }

  const parsed = RunBody.safeParse(await request.json().catch(() => null));
  if (!parsed.success) {
    return Response.json({ error: "that question could not be sent", code: "invalid_request" }, {
      status: 422,
    });
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${env.AGENT_API_URL}/runs`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        accept: "text/event-stream",
        authorization: `Bearer ${session.accessToken}`,
      },
      body: JSON.stringify(parsed.data),
      // Covers the window before headers arrive, which the stream's own cancellation cannot.
      signal: request.signal,
      cache: "no-store",
    });
  } catch {
    if (request.signal.aborted) return new Response(null, { status: 499 });
    return Response.json(
      { error: "could not reach the analyst service", code: "upstream" },
      { status: 502 },
    );
  }

  // Anything that fails before the stream opens is a real HTTP status with a JSON body: an
  // unknown connection, an exhausted budget, a rate limit. Those are read and re-sent, not
  // streamed, so the client sees a status rather than an error event.
  if (!upstream.ok || !upstream.body) {
    return errorResponse(await normalizeAgentError(upstream));
  }

  const body = upstream.body;
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      // Next flushes response headers only when the first chunk is written, so without this
      // the browser's fetch promise does not settle until the agent's first event, which can
      // be seconds. The symptom looks exactly like a broken parser. It is a valid SSE comment
      // line, and the decoder skips it.
      controller.enqueue(encoder.encode(": open\n\n"));

      const reader = body.getReader();
      try {
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          controller.enqueue(value);
        }
        controller.close();
      } catch (error) {
        controller.error(error);
      } finally {
        reader.releaseLock();
      }
    },
    cancel(reason) {
      // The browser went away, so tear the upstream run down rather than streaming into
      // nothing for another thirty seconds.
      body.cancel(reason).catch(() => {});
    },
  });

  return new Response(stream, { status: 200, headers: streamHeaders() });
}

/** History, for revalidating a list without a navigation. */
export async function GET(request: Request) {
  try {
    const session = await getSession();
    if (!session) throw new ApiError("your session has ended", 401, "unauthorized");

    const incoming = new URL(request.url).searchParams;
    const allowed = new URLSearchParams();
    for (const key of ["thread_id", "status", "connection_id", "limit", "cursor"]) {
      const value = incoming.get(key);
      if (value) allowed.set(key, value);
    }

    const page = await agentJson<RunPage>(`/runs?${allowed}`, { token: session.accessToken });
    return Response.json(page);
  } catch (error) {
    if (error instanceof ApiError) return errorResponse(error);
    return Response.json({ error: "could not load history", code: "unknown" }, { status: 500 });
  }
}
