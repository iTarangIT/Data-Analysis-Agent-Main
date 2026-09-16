import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AnswerText } from "./chat-message";

afterEach(cleanup);

const markdown = [
  "### Welcome",
  "",
  "This is a **rich markdown** showcase.",
  "",
  "| Name | Role |",
  "|------|------|",
  "| Alice | Engineer |",
  "",
  "> Simplicity is the ultimate sophistication.",
  "",
  "Use `let total = items.length` to count elements.",
].join("\n");

describe("AnswerText", () => {
  it("renders an answer's markdown rather than its syntax", () => {
    const { container } = render(<AnswerText shown={markdown} full={markdown} />);
    expect(screen.getByRole("heading", { level: 3, name: "Welcome" })).toBeTruthy();
    expect(container.querySelector("[data-streamdown=strong]")?.textContent).toBe("rich markdown");
    expect(screen.getByRole("table")).toBeTruthy();
    expect(screen.getByRole("cell", { name: "Alice" })).toBeTruthy();
    expect(container.querySelector("blockquote")?.textContent).toContain("Simplicity");
    expect(container.querySelector("code")?.textContent).toBe("let total = items.length");
    expect(container.textContent).not.toContain("**");
  });

  it("does not read money as math", () => {
    const text = "Revenue rose from $5 to $10 per device.";
    const { container } = render(<AnswerText shown={text} full={text} />);
    expect(container.querySelector(".katex")).toBeNull();
    expect(container.textContent).toContain("$5 to $10");
  });

  it("while typing, hides the partial copy from assistive tech and offers the whole answer", () => {
    const full = "There are **490** vehicles.";
    const { container } = render(<AnswerText shown="There are" full={full} />);
    expect(container.querySelector("[aria-hidden='true']")?.textContent).toContain("There are");
    expect(container.querySelector(".sr-only")?.textContent).toBe(full);
  });

  it("drops the streaming caret once the answer has finished arriving", () => {
    const text = "There are 490 vehicles.";
    const { container, rerender } = render(<AnswerText shown={text} full={text} streaming />);
    const caret = () => container.querySelector("[style*='--streamdown-caret']");
    expect(caret()).not.toBeNull();
    // Same text, stream over: only the streaming flag changes.
    rerender(<AnswerText shown={text} full={text} streaming={false} />);
    expect(caret()).toBeNull();
  });

  it("once typed out, is one copy that assistive tech can read", () => {
    const full = "There are 490 vehicles.";
    const { container } = render(<AnswerText shown={full} full={full} />);
    expect(container.querySelector("[aria-hidden='true']")).toBeNull();
    expect(container.querySelector(".sr-only")).toBeNull();
  });
});
