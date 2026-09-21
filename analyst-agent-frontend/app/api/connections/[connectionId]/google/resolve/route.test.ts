// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/errors";

import { POST } from "./route";

vi.mock("server-only", () => ({}));
const requireSessionOr401 = vi.hoisted(() => vi.fn());
vi.mock("@/lib/auth/dal", () => ({ requireSessionOr401 }));
const agentJson = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/agent-client", () => ({ agentJson }));

const LINK = "https://drive.google.com/drive/folders/abc";

function post(body: unknown) {
  return new Request("http://app.test/api/connections/c1/google/resolve", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

function ctx(connectionId = "c1") {
  return { params: Promise.resolve({ connectionId }) };
}

beforeEach(() => {
  requireSessionOr401.mockReset();
  agentJson.mockReset();
  requireSessionOr401.mockResolvedValue({ accessToken: "tok", email: "a@example.com" });
});

describe("POST /api/connections/[connectionId]/google/resolve", () => {
  it("asks nothing of the agent for someone signed out", async () => {
    requireSessionOr401.mockRejectedValueOnce(
      new ApiError("your session has ended", 401, "unauthorized"),
    );

    const response = await POST(post({ url: LINK }), ctx());

    expect(response.status).toBe(401);
    expect(agentJson).not.toHaveBeenCalled();
  });

  it("forwards the link and an owner's confirmation to this connection, with the token", async () => {
    agentJson.mockResolvedValueOnce({ status: "unverified", share_with: null, source: null });

    const response = await POST(post({ url: ` ${LINK} `, confirm_unverified: true }), ctx());

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ status: "unverified", share_with: null, source: null });
    const [path, options] = agentJson.mock.calls[0];
    expect(path).toBe("/connections/c1/google/resolve");
    expect(options).toMatchObject({
      method: "POST",
      token: "tok",
      body: { url: LINK, confirm_unverified: true },
      timeoutMs: 30_000,
    });
  });

  it("escapes the connection id in the agent's path", async () => {
    agentJson.mockResolvedValueOnce({ status: "needs_share", share_with: "r@x.com", source: null });

    await POST(post({ url: LINK }), ctx("a/b"));

    expect(agentJson.mock.calls[0][0]).toBe("/connections/a%2Fb/google/resolve");
  });

  it("refuses an empty link without asking the agent", async () => {
    const response = await POST(post({ url: "   " }), ctx());

    expect(response.status).toBe(422);
    expect((await response.json()).error).toBe("Paste a Google Drive or Google Sheets link.");
    expect(agentJson).not.toHaveBeenCalled();
  });

  it("passes the agent's refusal on with its status", async () => {
    agentJson.mockRejectedValueOnce(
      new ApiError("paste a Google Drive or Google Sheets link", 400, "invalid_request"),
    );

    const response = await POST(post({ url: "https://example.com" }), ctx());

    expect(response.status).toBe(400);
    expect(await response.json()).toMatchObject({
      error: "paste a Google Drive or Google Sheets link",
      code: "invalid_request",
    });
  });

  it("answers a reply it cannot read with its own message rather than passing it on", async () => {
    agentJson.mockResolvedValueOnce({ status: "maybe" });

    const response = await POST(post({ url: LINK }), ctx());

    expect(response.status).toBe(500);
    expect((await response.json()).error).toBe("could not check that link");
  });
});
