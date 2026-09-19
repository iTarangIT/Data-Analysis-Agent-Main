// @vitest-environment node
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GET } from "./route";

vi.mock("server-only", () => ({}));
vi.mock("@/lib/env", () => ({ env: { APP_URL: "https://app.example.com" } }));
const exchangeCodeForSession = vi.hoisted(() => vi.fn());
vi.mock("@/lib/supabase/server", () => ({
  createClient: async () => ({ auth: { exchangeCodeForSession } }),
}));
const whereToLand = vi.hoisted(() => vi.fn());
vi.mock("@/lib/auth/landing", () => ({ whereToLand }));

// What Next hands a route handler behind Render's proxy: the address it listens on, not the
// one the browser used.
const callback = (query: string) =>
  new NextRequest(`http://localhost:10000/api/auth/callback?${query}`);

beforeEach(() => {
  exchangeCodeForSession.mockReset();
  whereToLand.mockReset();
});

describe("GET /api/auth/callback", () => {
  it("lands on the app's public address, not the one Next listens on", async () => {
    exchangeCodeForSession.mockResolvedValueOnce({
      data: { session: { access_token: "tok" } },
      error: null,
    });
    whereToLand.mockResolvedValueOnce("/welcome");

    const response = await GET(callback("code=abc"));

    expect(response.headers.get("location")).toBe("https://app.example.com/welcome");
  });

  it("sends a refused consent back to the public login page", async () => {
    const response = await GET(callback("error=access_denied"));

    expect(response.headers.get("location")).toBe("https://app.example.com/login?error=google");
    expect(exchangeCodeForSession).not.toHaveBeenCalled();
  });
});
