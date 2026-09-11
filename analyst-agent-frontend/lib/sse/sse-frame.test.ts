import { describe, expect, it } from "vitest";

import { createSseFrameDecoder } from "./sse-frame";

const bytes = (s: string) => new TextEncoder().encode(s);

/**
 * The agent streams through sse-starlette, whose separator is CRLF:
 *
 *   sse_starlette/event.py:13   DEFAULT_SEPARATOR = "\r\n"
 *
 * and the route builds `EventSourceResponse(...)` without overriding it. So frames end with
 * "\r\n\r\n", and a decoder that splits on "\n\n" finds nothing at all. Every fixture here is
 * written the way the wire actually looks.
 */
const CRLF = "\r\n";
const frame = (event: string, data: string) =>
  `event: ${event}${CRLF}data: ${data}${CRLF}${CRLF}`;

describe("createSseFrameDecoder", () => {
  it("decodes a CRLF-separated frame", () => {
    const decoder = createSseFrameDecoder();
    const frames = decoder.push(bytes(frame("status", '{"stage":"router"}')));

    expect(frames).toEqual([{ event: "status", data: '{"stage":"router"}' }]);
  });

  it("decodes a whole happy-path run in one chunk", () => {
    const decoder = createSseFrameDecoder();
    const wire = [
      frame("status", '{"stage":"router"}'),
      frame("status", '{"stage":"sql_gen"}'),
      frame("status", '{"stage":"sql_guard"}'),
      frame("sql", '{"sql":"SELECT 1"}'),
      frame("status", '{"stage":"db_exec"}'),
      frame("rows", '{"columns":["n"],"rows":[[1]],"truncated":false}'),
      frame("status", '{"stage":"answer"}'),
      frame("token", '{"text":"One."}'),
      frame("done", '{"run_id":"r1","duration_ms":42}'),
    ].join("");

    expect(decoder.push(bytes(wire)).map((f) => f.event)).toEqual([
      "status",
      "status",
      "status",
      "sql",
      "status",
      "rows",
      "status",
      "token",
      "done",
    ]);
  });

  it("also accepts LF separators", () => {
    // The contract is CRLF today, but a future sse-starlette or a test double may use LF.
    const decoder = createSseFrameDecoder();
    const frames = decoder.push(bytes('event: token\ndata: {"text":"hi"}\n\n'));

    expect(frames).toEqual([{ event: "token", data: '{"text":"hi"}' }]);
  });

  it("emits nothing until a frame is complete", () => {
    const decoder = createSseFrameDecoder();

    expect(decoder.push(bytes(`event: sql${CRLF}data: {"sql":"SEL`))).toEqual([]);
    expect(decoder.push(bytes(`ECT 1"}${CRLF}${CRLF}`))).toEqual([
      { event: "sql", data: '{"sql":"SELECT 1"}' },
    ]);
  });

  it("survives a split between the carriage return and the newline", () => {
    // The nastiest boundary, and the one a naive buffer loses.
    const decoder = createSseFrameDecoder();
    const wire = frame("done", '{"run_id":"r1","duration_ms":1}');
    const cut = wire.length - 3; // lands inside the trailing "\r\n\r\n"

    const first = decoder.push(bytes(wire.slice(0, cut)));
    const second = decoder.push(bytes(wire.slice(cut)));

    expect([...first, ...second]).toEqual([
      { event: "done", data: '{"run_id":"r1","duration_ms":1}' },
    ]);
  });

  it("decodes correctly however the stream is chunked", () => {
    const wire = frame("status", '{"stage":"router"}') + frame("token", '{"text":"ok"}');

    for (let size = 1; size <= wire.length; size++) {
      const decoder = createSseFrameDecoder();
      const seen = [];
      for (let i = 0; i < wire.length; i += size) {
        seen.push(...decoder.push(bytes(wire.slice(i, i + size))));
      }
      expect(seen.map((f) => f.event), `chunk size ${size}`).toEqual(["status", "token"]);
    }
  });

  it("skips the keepalive ping", () => {
    // sse-starlette sends `: ping - <timestamp>` as a bare comment between events.
    const decoder = createSseFrameDecoder();
    const wire =
      `: ping - 2026-09-11 12:00:00+00:00${CRLF}${CRLF}` + frame("token", '{"text":"hi"}');

    expect(decoder.push(bytes(wire))).toEqual([{ event: "token", data: '{"text":"hi"}' }]);
  });

  it("skips the prelude the route handler sends to flush headers", () => {
    const decoder = createSseFrameDecoder();

    expect(decoder.push(bytes(": open\n\n"))).toEqual([]);
  });

  it("ignores a comment line inside an otherwise real frame", () => {
    const decoder = createSseFrameDecoder();
    const wire = `: keepalive${CRLF}event: token${CRLF}data: {"text":"hi"}${CRLF}${CRLF}`;

    expect(decoder.push(bytes(wire))).toEqual([{ event: "token", data: '{"text":"hi"}' }]);
  });

  it("joins a multi-line data field with newlines, per the spec", () => {
    const decoder = createSseFrameDecoder();
    const wire = `event: sql${CRLF}data: SELECT 1${CRLF}data: FROM t${CRLF}${CRLF}`;

    expect(decoder.push(bytes(wire))).toEqual([{ event: "sql", data: "SELECT 1\nFROM t" }]);
  });

  it("strips exactly one leading space after the colon", () => {
    const decoder = createSseFrameDecoder();
    const wire = `event: token${CRLF}data:  two spaces${CRLF}${CRLF}`;

    expect(decoder.push(bytes(wire))[0].data).toBe(" two spaces");
  });

  it("handles a field with no space after the colon", () => {
    const decoder = createSseFrameDecoder();

    expect(decoder.push(bytes(`event:token${CRLF}data:{"a":1}${CRLF}${CRLF}`))).toEqual([
      { event: "token", data: '{"a":1}' },
    ]);
  });

  it("defaults the event name to message when none is given", () => {
    const decoder = createSseFrameDecoder();

    expect(decoder.push(bytes(`data: bare${CRLF}${CRLF}`))).toEqual([
      { event: "message", data: "bare" },
    ]);
  });

  it("keeps a multi-byte character split across two chunks", () => {
    // An answer containing a rupee sign or an em dash arrives as several bytes, and a decoder
    // without streaming state turns the split into a replacement character.
    const decoder = createSseFrameDecoder();
    const wire = frame("token", '{"text":"₹1,200 — up"}');
    const raw = new TextEncoder().encode(wire);
    const cut = 30; // lands mid-character

    const seen = [...decoder.push(raw.slice(0, cut)), ...decoder.push(raw.slice(cut))];

    expect(seen).toHaveLength(1);
    expect(JSON.parse(seen[0].data).text).toBe("₹1,200 — up");
  });

  it("discards an incomplete trailing frame", () => {
    // Per the spec an event without its blank line never fired. The state machine treats the
    // stream ending early as a failure, so nothing is lost by dropping it here.
    const decoder = createSseFrameDecoder();
    decoder.push(bytes(`event: token${CRLF}data: {"text":"cut off"`));

    expect(decoder.remainder()).toContain("cut off");
  });

  it("does not confuse a blank line inside data with the frame end", () => {
    const decoder = createSseFrameDecoder();
    const wire = `event: sql${CRLF}data: SELECT 1${CRLF}data: ${CRLF}data: FROM t${CRLF}${CRLF}`;

    expect(decoder.push(bytes(wire))).toEqual([{ event: "sql", data: "SELECT 1\n\nFROM t" }]);
  });
});
