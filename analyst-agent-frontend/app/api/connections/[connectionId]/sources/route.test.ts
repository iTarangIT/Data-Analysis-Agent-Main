// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/errors";

import { GET, POST } from "./route";

vi.mock("server-only", () => ({}));
const requireSessionOr401 = vi.hoisted(() => vi.fn());
vi.mock("@/lib/auth/dal", () => ({ requireSessionOr401 }));
const agentJson = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/agent-client", () => ({ agentJson }));
const revalidatePath = vi.hoisted(() => vi.fn());
vi.mock("next/cache", () => ({ revalidatePath }));

const SOURCE = {
  id: "s1",
  origin: "gdrive_folder",
  label: "Sales",
  status: "active",
  combine: true,
  rules: [{ id: "root", kind: "folder", recursive: true }],
  files: [],
};

const RULES = {
  source_id: "s1",
  rules: [{ id: "root", kind: "folder", recursive: true }],
  combine: true,
};

function post(body: unknown) {
  return new Request("http://app.test/api/connections/c1/sources", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

const ctx = () => ({ params: Promise.resolve({ connectionId: "c1" }) });

beforeEach(() => {
  requireSessionOr401.mockReset();
  agentJson.mockReset();
  revalidatePath.mockReset();
  requireSessionOr401.mockResolvedValue({ accessToken: "tok", email: "a@example.com" });
});

describe("GET /api/connections/[connectionId]/sources", () => {
  it("asks nothing of the agent for someone signed out", async () => {
    requireSessionOr401.mockRejectedValueOnce(
      new ApiError("your session has ended", 401, "unauthorized"),
    );

    const response = await GET(new Request("http://app.test/api/connections/c1/sources"), ctx());

    expect(response.status).toBe(401);
    expect(agentJson).not.toHaveBeenCalled();
  });

  it("reads this connection's sources with the token", async () => {
    const sources = { sync_status: "syncing", synced_at: null, sources: [SOURCE] };
    agentJson.mockResolvedValueOnce(sources);

    const response = await GET(new Request("http://app.test/api/connections/c1/sources"), ctx());

    expect(await response.json()).toEqual(sources);
    expect(agentJson).toHaveBeenCalledWith("/connections/c1/sources", { token: "tok" });
  });

  it("passes a missing connection on as a 404", async () => {
    agentJson.mockRejectedValueOnce(new ApiError("connection not found", 404, "not_found"));

    const response = await GET(new Request("http://app.test/api/connections/c1/sources"), ctx());

    expect(response.status).toBe(404);
    expect((await response.json()).error).toBe("connection not found");
  });
});

describe("POST /api/connections/[connectionId]/sources", () => {
  it("sizes a choice without saving anything or revalidating a page", async () => {
    const run = { files: 3, bytes: 4096, skipped: [], fits: true, limit: 52_428_800 };
    agentJson.mockResolvedValueOnce(run);

    const response = await POST(post({ ...RULES, dry_run: true }), ctx());

    expect(await response.json()).toEqual(run);
    const [path, options] = agentJson.mock.calls[0];
    expect(path).toBe("/connections/c1/sources");
    expect(options).toMatchObject({
      method: "POST",
      token: "tok",
      body: { ...RULES, dry_run: true },
      timeoutMs: 60_000,
    });
    expect(revalidatePath).not.toHaveBeenCalled();
  });

  it("saves a choice and revalidates the pages that count its tables", async () => {
    agentJson.mockResolvedValueOnce(SOURCE);

    const response = await POST(post(RULES), ctx());

    expect(await response.json()).toEqual(SOURCE);
    expect(revalidatePath.mock.calls.map(([path]) => path)).toEqual([
      "/connections/c1/tables",
      "/connections",
      "/ask",
    ]);
  });

  it("refuses a rule of a kind it does not know without asking the agent", async () => {
    const response = await POST(
      post({ ...RULES, rules: [{ id: "root", kind: "table", recursive: false }] }),
      ctx(),
    );

    expect(response.status).toBe(422);
    expect(agentJson).not.toHaveBeenCalled();
  });

  it("answers a saved source it cannot read with its own message", async () => {
    agentJson.mockResolvedValueOnce({ id: "s1" });

    const response = await POST(post(RULES), ctx());

    expect(response.status).toBe(500);
    expect((await response.json()).error).toBe("could not add that source");
    expect(revalidatePath).not.toHaveBeenCalled();
  });
});
