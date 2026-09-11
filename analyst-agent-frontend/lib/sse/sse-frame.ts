/**
 * A Server-Sent Events frame decoder. Pure: no fetch, no DOM, no timers.
 *
 * Split out from the stream reader because this is where the bugs live, and because a pure
 * function can be driven byte-by-byte in a test.
 *
 * The one thing that makes this work against the agent: **sse-starlette separates lines with
 * CRLF**, not LF (`sse_starlette/event.py`, `DEFAULT_SEPARATOR = "\r\n"`, and the route never
 * overrides it). Frames therefore end with "\r\n\r\n". A decoder that splits the buffer on
 * "\n\n" matches nothing, emits no events, and leaves the UI waiting forever on a stream that
 * is arriving perfectly well.
 */

export type SseFrame = {
  /** The `event:` field, or "message" when the frame carried none. */
  event: string;
  /** All `data:` lines, joined with newlines, per the WHATWG spec. */
  data: string;
};

function parseFrame(raw: string): SseFrame | null {
  let event = "message";
  const dataLines: string[] = [];

  for (const line of raw.split("\n")) {
    // A line starting with a colon is a comment. sse-starlette's keepalive arrives as
    // `: ping - <timestamp>`, and the route handler opens with `: open`.
    if (line === "" || line.startsWith(":")) continue;

    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    // Exactly one, so `data:  x` really does mean a value that starts with a space.
    if (value.startsWith(" ")) value = value.slice(1);

    if (field === "event") event = value;
    else if (field === "data") dataLines.push(value);
    // `id` and `retry` are ignored: the agent sends neither, and this client never reconnects.
  }

  // A frame made only of comments is a keepalive, not an event.
  return dataLines.length === 0 ? null : { event, data: dataLines.join("\n") };
}

export function createSseFrameDecoder() {
  // `stream: true` carries a partial multi-byte character across chunk boundaries. Without it
  // an answer containing a rupee sign or an em dash can decode to a replacement character
  // whenever the split lands mid-character.
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  // A CRLF can be split across two chunks. Normalising each chunk on its own would turn the
  // lone trailing "\r" into "\n" and then accept the next chunk's "\n" as a second one,
  // inventing a frame boundary in the middle of a frame. So the "\r" is held back instead.
  let pendingCarriageReturn = false;

  return {
    /** Feed one chunk. Returns whichever frames completed. */
    push(chunk: Uint8Array): SseFrame[] {
      let text = decoder.decode(chunk, { stream: true });

      if (pendingCarriageReturn) {
        // If this chunk opens with "\n", the two halves were one CRLF; otherwise the "\r" was
        // a line ending on its own. Either way it yields exactly one newline.
        if (text.startsWith("\n")) text = text.slice(1);
        buffer += "\n";
        pendingCarriageReturn = false;
      }
      if (text.endsWith("\r")) {
        text = text.slice(0, -1);
        pendingCarriageReturn = true;
      }

      buffer += text.replace(/\r\n|\r/g, "\n");

      const frames: SseFrame[] = [];
      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const raw = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const frame = parseFrame(raw);
        if (frame) frames.push(frame);
        boundary = buffer.indexOf("\n\n");
      }
      return frames;
    },

    /**
     * Whatever is left once the stream closed. Per the spec an event without its blank line
     * never fired, so this is diagnostic only: the run state machine already treats a stream
     * that ends without a terminal event as a failure.
     */
    remainder(): string {
      return buffer;
    },
  };
}
