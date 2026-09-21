// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GET } from "./route";

vi.mock("server-only", () => ({}));
const requireSessionOr401 = vi.hoisted(() => vi.fn());
vi.mock("@/lib/auth/dal", () => ({ requireSessionOr401 }));
const agentJson = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/agent-client", () => ({ agentJson }));

const LISTING = { folder_id: "sub", children: [], supported: 0, unsupported: 0, bytes: 0 };

const ctx = () => ({ params: Promise.resolve({ connectionId: "c1" }) });

beforeEach(() => {
  requireSessionOr401.mockReset();
  agentJson.mockReset();
  requireSessionOr401.mockResolvedValue({ accessToken: "tok", email: "a@example.com" });
});

describe("GET /api/connections/[connectionId]/google/tree", () => {
  it("lists one folder of a source, passing only the source and folder on", async () => {
    agentJson.mockResolvedValueOnce(LISTING);

    const response = await GET(
      new Request("http://app.test/api/connections/c1/google/tree?source_id=s1&folder_id=sub&x=1"),
      ctx(),
    );

    expect(await response.json()).toEqual(LISTING);
    expect(agentJson).toHaveBeenCalledWith(
      "/connections/c1/google/tree?source_id=s1&folder_id=sub",
      { token: "tok", timeoutMs: 30_000 },
    );
  });

  it("refuses a listing with no source without asking the agent", async () => {
    const response = await GET(new Request("http://app.test/api/connections/c1/google/tree"), ctx());

    expect(response.status).toBe(422);
    expect(agentJson).not.toHaveBeenCalled();
  });
});
