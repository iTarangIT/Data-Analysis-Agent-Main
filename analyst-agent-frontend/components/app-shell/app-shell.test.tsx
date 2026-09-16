import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "./app-shell";

// A server action cannot be imported into jsdom, and the shell only ever passes it to a form.
vi.mock("@/actions/auth", () => ({ logout: vi.fn() }));
// `usePathname` reads the router, which only exists inside the App Router at runtime.
vi.mock("next/navigation", () => ({ usePathname: () => "/ask" }));

afterEach(cleanup);

describe("AppShell", () => {
  /**
   * `globals.css` hangs the document's `overflow: hidden` off this attribute, so that a node an
   * extension appends to `body` cannot grow the page past the viewport and strand the shell
   * above a band of dead space. Nothing in the component reads it, which is exactly why it is
   * worth pinning: it looks decorative and deleting it would break the layout silently, in
   * whichever browsers happen to have an extension installed.
   */
  it("marks its root for the stylesheet rule that stops the document scrolling", () => {
    const { container } = render(<AppShell user={null}>{null}</AppShell>);

    const root = container.firstElementChild;
    expect(root?.hasAttribute("data-app-shell")).toBe(true);
    expect(root?.className).toContain("h-dvh");
  });
});
