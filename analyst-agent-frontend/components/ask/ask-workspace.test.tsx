import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { SidebarProvider } from "@/components/app-shell/sidebar-context";

import { AskWorkspace } from "./ask-workspace";

const refresh = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
// The orb loads three.js on the client, which jsdom has no WebGL for.
vi.mock("@/components/ask/agent-orb", () => ({ AgentOrb: () => null }));

beforeAll(() => {
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});

afterEach(() => {
  cleanup();
  refresh.mockReset();
});

function renderWorkspace(unreachable: boolean) {
  return render(
    <SidebarProvider>
      <AskWorkspace connections={[]} threadId="t1" history={[]} unreachable={unreachable} />
    </SidebarProvider>,
  );
}

describe("AskWorkspace with no connections to show", () => {
  it("says the service did not answer, rather than that nothing is connected", () => {
    renderWorkspace(true);

    expect(screen.getByRole("heading", { name: /didn.t answer/i })).toBeTruthy();
    expect(screen.queryByText(/connect a database/i)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(refresh).toHaveBeenCalledOnce();
  });

  it("asks for a connection when the service answered with none", () => {
    renderWorkspace(false);

    expect(screen.getByRole("heading", { name: "Connect a database to get started" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });
});
