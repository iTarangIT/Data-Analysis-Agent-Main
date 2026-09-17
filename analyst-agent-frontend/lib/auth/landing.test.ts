import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/errors";

import { whereToLand } from "./landing";

// A marker that throws outside a React Server environment; it guards bundling, not behaviour.
vi.mock("server-only", () => ({}));
// The agent is the boundary here: these pin what the app decides from its answers.
const agentJson = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/agent-client", () => ({ agentJson }));

const onboarding = () =>
  new ApiError("this account has no organisation yet", 403, "onboarding_required");

beforeEach(() => {
  agentJson.mockReset();
});

describe("whereToLand", () => {
  it("sends a member straight on", async () => {
    agentJson.mockResolvedValueOnce({ id: "u1" });

    await expect(whereToLand({ accessToken: "tok", next: "/connections" })).resolves.toBe(
      "/connections",
    );
    expect(agentJson).toHaveBeenCalledWith("/auth/me", { token: "tok" });
  });

  it("sends someone with no organisation to name one, keeping where they were headed", async () => {
    agentJson.mockRejectedValueOnce(onboarding());

    await expect(whereToLand({ accessToken: "tok", next: "/connections" })).resolves.toBe(
      "/welcome?next=%2Fconnections",
    );
  });

  it("does not clutter /welcome with the default destination", async () => {
    agentJson.mockRejectedValueOnce(onboarding());

    await expect(whereToLand({ accessToken: "tok", next: "/ask" })).resolves.toBe("/welcome");
  });

  it("creates the organisation named at sign-up instead of asking again", async () => {
    agentJson.mockRejectedValueOnce(onboarding()).mockResolvedValueOnce({ id: "u1" });

    await expect(
      whereToLand({ accessToken: "tok", next: "/ask", tenantName: "Acme Logistics" }),
    ).resolves.toBe("/ask");
    expect(agentJson).toHaveBeenLastCalledWith("/auth/provision", {
      method: "POST",
      token: "tok",
      body: { tenant_name: "Acme Logistics" },
    });
  });

  it("treats an organisation that already exists as done", async () => {
    agentJson
      .mockRejectedValueOnce(onboarding())
      .mockRejectedValueOnce(new ApiError("an account already exists", 409, "conflict"));

    await expect(
      whereToLand({ accessToken: "tok", next: "/ask", tenantName: "Acme" }),
    ).resolves.toBe("/ask");
  });

  it("falls back to asking when creating the organisation fails", async () => {
    agentJson
      .mockRejectedValueOnce(onboarding())
      .mockRejectedValueOnce(new ApiError("sign-up is closed", 403, "forbidden"));

    await expect(
      whereToLand({ accessToken: "tok", next: "/ask", tenantName: "Acme" }),
    ).resolves.toBe("/welcome");
  });

  it("ignores a blank organisation name from sign-up", async () => {
    agentJson.mockRejectedValueOnce(onboarding());

    await expect(
      whereToLand({ accessToken: "tok", next: "/ask", tenantName: "   " }),
    ).resolves.toBe("/welcome");
    expect(agentJson).toHaveBeenCalledTimes(1);
  });

  /** The page they land on reports an unreachable agent properly; a redirect cannot. */
  it("carries on when the agent cannot answer at all", async () => {
    agentJson.mockRejectedValueOnce(new ApiError("could not reach the analyst service", 504, "upstream"));

    await expect(whereToLand({ accessToken: "tok", next: "/ask" })).resolves.toBe("/ask");
  });
});
