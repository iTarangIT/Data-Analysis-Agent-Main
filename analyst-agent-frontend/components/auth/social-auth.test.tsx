import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SocialAuth } from "./social-auth";

// A server action cannot be imported into jsdom; the component only hands it to a form.
vi.mock("@/actions/auth", () => ({ signInWithGoogle: vi.fn() }));

afterEach(cleanup);

describe("SocialAuth", () => {
  it("offers Google as a live button that submits a form", () => {
    render(<SocialAuth />);

    const button = screen.getByRole("button", { name: /continue with google/i });
    expect((button as HTMLButtonElement).disabled).toBe(false);
    expect(button.getAttribute("type")).toBe("submit");
    expect(button.closest("form")).not.toBeNull();
  });

  it("carries where to return after signing in", () => {
    render(<SocialAuth next="/connections" />);

    const form = screen.getByRole("button", { name: /continue with google/i }).closest("form")!;
    const next = form.querySelector<HTMLInputElement>('input[name="next"]');
    expect(next?.value).toBe("/connections");
  });

  it("sends no destination when there is none to keep", () => {
    render(<SocialAuth />);

    const form = screen.getByRole("button", { name: /continue with google/i }).closest("form")!;
    expect(form.querySelector('input[name="next"]')).toBeNull();
  });

  it("offers no provider that is not wired up", () => {
    render(<SocialAuth />);

    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(screen.queryByText(/not enabled/i)).toBeNull();
  });
});
