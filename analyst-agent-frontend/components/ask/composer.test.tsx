import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Composer } from "./composer";

afterEach(cleanup);

function Harness({
  onSubmit = vi.fn(),
  onStop = vi.fn(),
  busy = false,
  canSend = true,
  initial = "How many alerts?",
}: {
  onSubmit?: () => void;
  onStop?: () => void;
  busy?: boolean;
  canSend?: boolean;
  initial?: string;
}) {
  const [value, setValue] = useState(initial);
  return (
    <Composer
      value={value}
      onChange={setValue}
      onSubmit={onSubmit}
      onStop={onStop}
      busy={busy}
      canSend={canSend}
      placeholder="Ask anything"
    />
  );
}

describe("Composer", () => {
  it("sends on Enter", () => {
    const onSubmit = vi.fn();
    render(<Harness onSubmit={onSubmit} />);
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    expect(onSubmit).toHaveBeenCalledOnce();
  });

  it("leaves Shift+Enter to make a new line", () => {
    const onSubmit = vi.fn();
    render(<Harness onSubmit={onSubmit} />);
    const event = fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter", shiftKey: true });
    expect(onSubmit).not.toHaveBeenCalled();
    // Not prevented, so the browser inserts the newline itself.
    expect(event).toBe(true);
  });

  it("does not send while an input method is still composing a character", () => {
    const onSubmit = vi.fn();
    render(<Harness onSubmit={onSubmit} />);
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter", isComposing: true });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("does not send what it may not send, by key or by button", () => {
    const onSubmit = vi.fn();
    render(<Harness onSubmit={onSubmit} canSend={false} />);
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    const send = screen.getByRole("button", { name: "Send" }) as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    fireEvent.click(send);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("turns the send button into a working Stop while a run is going", () => {
    const onSubmit = vi.fn();
    const onStop = vi.fn();
    render(<Harness onSubmit={onSubmit} onStop={onStop} busy canSend={false} />);
    expect(screen.queryByRole("button", { name: "Send" })).toBeNull();
    const stop = screen.getByRole("button", { name: "Stop" }) as HTMLButtonElement;
    expect(stop.disabled).toBe(false);
    fireEvent.click(stop);
    expect(onStop).toHaveBeenCalledOnce();
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
