// @vitest-environment node
import { NextRequest } from "next/server";
import { describe, expect, it, vi } from "vitest";

import { GET } from "./route";

vi.mock("server-only", () => ({}));
vi.mock("@/lib/env", () => ({ env: { APP_URL: "https://app.example.com" } }));
const verifyOtp = vi.hoisted(() => vi.fn());
vi.mock("@/lib/supabase/server", () => ({
  createClient: async () => ({ auth: { verifyOtp } }),
}));
const whereToLand = vi.hoisted(() => vi.fn());
vi.mock("@/lib/auth/landing", () => ({ whereToLand }));

const confirm = (query: string) =>
  new NextRequest(`http://localhost:10000/api/auth/confirm?${query}`);

describe("GET /api/auth/confirm", () => {
  it("lands on the app's public address, not the one Next listens on", async () => {
    verifyOtp.mockResolvedValueOnce({
      data: { session: { access_token: "tok" }, user: { user_metadata: {} } },
      error: null,
    });
    whereToLand.mockResolvedValueOnce("/ask");

    const response = await GET(confirm("token_hash=h&type=email"));

    expect(response.headers.get("location")).toBe("https://app.example.com/ask");
  });

  it("sends a link of the wrong kind back to the public login page", async () => {
    const response = await GET(confirm("token_hash=h&type=recovery"));

    expect(response.headers.get("location")).toBe("https://app.example.com/login?error=confirm");
  });
});
