// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/errors";

import { GET } from "./route";

vi.mock("server-only", () => ({}));
const getSession = vi.hoisted(() => vi.fn());
vi.mock("@/lib/auth/dal", () => ({ getSession }));
const agentFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/agent-client", () => ({ agentFetch }));

beforeEach(() => {
  getSession.mockReset();
  agentFetch.mockReset();
  getSession.mockResolvedValue({ accessToken: "tok", email: "a@example.com" });
});

describe("GET /api/health", () => {
  it("answers 200 once the agent does", async () => {
    agentFetch.mockResolvedValueOnce(new Response(null, { status: 200 }));

    expect((await GET()).status).toBe(200);
  });

  // Once the agent is waking the host holds this request until it is up, which took 58 s live.
  it("waits long enough for the agent to finish waking", async () => {
    agentFetch.mockResolvedValueOnce(new Response(null, { status: 200 }));

    await GET();

    const [, options] = agentFetch.mock.calls[0];
    expect(options.timeoutMs).toBeGreaterThanOrEqual(90_000);
  });

  it("answers 503 while the agent is still waking", async () => {
    agentFetch.mockRejectedValueOnce(new ApiError("the analyst service did not respond in time", 504, "upstream"));

    expect((await GET()).status).toBe(503);
  });

  it("asks nothing of the agent for someone signed out", async () => {
    getSession.mockResolvedValueOnce(null);

    expect((await GET()).status).toBe(401);
    expect(agentFetch).not.toHaveBeenCalled();
  });
});
