import { describe, expect, it } from "vitest";

import { normalizeAgentError } from "./errors";

function reply(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("normalizeAgentError", () => {
  /**
   * A signed-in person with no organisation gets a 403 like any other refusal. Only the code
   * tells the app to send them to /welcome rather than show "forbidden".
   */
  it("keeps the agent's onboarding code instead of the generic one for a 403", async () => {
    const error = await normalizeAgentError(
      reply(403, { error: "this account has no organisation yet", code: "onboarding_required" }),
    );

    expect(error.code).toBe("onboarding_required");
    expect(error.status).toBe(403);
    expect(error.message).toBe("this account has no organisation yet");
  });

  it("still calls any other 403 forbidden", async () => {
    const error = await normalizeAgentError(reply(403, { error: "this account has been disabled" }));

    expect(error.code).toBe("forbidden");
  });

  it("ignores a code it does not know rather than passing it through", async () => {
    const error = await normalizeAgentError(reply(403, { error: "no", code: "made_up" }));

    expect(error.code).toBe("forbidden");
  });
});
