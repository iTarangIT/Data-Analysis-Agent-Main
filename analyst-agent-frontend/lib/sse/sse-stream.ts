import { createSseFrameDecoder, type SseFrame } from "./sse-frame";

export type SseOutcome =
  | { kind: "complete" } // a terminal frame arrived and the handler said to stop
  | { kind: "closed" } // the body ended with no terminal frame: a truncated run
  | { kind: "aborted" }
  | { kind: "transport"; message: string };

/**
 * Read an SSE body to completion, handing each frame to `onFrame`.
 *
 * `EventSource` cannot be used here and the reason is worth stating: it is GET-only, cannot
 * set a request header, and reconnects on its own. Against an endpoint that is POST, metered
 * and side-effecting, that last one would silently re-run the question and re-bill for it.
 *
 * Return "stop" from `onFrame` when a terminal frame arrives. That cancels the body, which
 * propagates back through the route handler to the agent, so a cancelled run is not left
 * streaming into nothing.
 */
export async function readSseStream(
  body: ReadableStream<Uint8Array>,
  onFrame: (frame: SseFrame) => "stop" | void,
  signal: AbortSignal,
): Promise<SseOutcome> {
  const reader = body.getReader();
  const decoder = createSseFrameDecoder();

  const onAbort = () => {
    reader.cancel(new DOMException("aborted", "AbortError")).catch(() => {});
  };
  signal.addEventListener("abort", onAbort, { once: true });

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) return { kind: "closed" };

      for (const frame of decoder.push(value)) {
        if (onFrame(frame) === "stop") {
          await reader.cancel().catch(() => {});
          return { kind: "complete" };
        }
      }
    }
  } catch (error) {
    if (signal.aborted) return { kind: "aborted" };
    return {
      kind: "transport",
      message: error instanceof Error ? error.message : "the stream failed",
    };
  } finally {
    signal.removeEventListener("abort", onAbort);
    reader.releaseLock();
  }
}
