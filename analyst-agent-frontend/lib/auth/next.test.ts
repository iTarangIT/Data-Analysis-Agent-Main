import { describe, expect, it } from "vitest";

import { safeNext } from "./next";

describe("safeNext", () => {
  it.each([
    ["/connections", "/connections"],
    ["/ask?thread=abc", "/ask?thread=abc"],
    ["/runs#latest", "/runs#latest"],
  ])("keeps a path on this site: %s", (value, expected) => {
    expect(safeNext(value)).toBe(expected);
  });

  /**
   * Each of these would send someone who has just signed in to another origin, with a live
   * session behind them. Browsers read `/\` as `//`, so the backslash form is the same attack.
   */
  it.each([
    "//evil.example",
    "/\\evil.example",
    "https://evil.example/ask",
    "javascript:alert(1)",
    "ask",
    "",
  ])("sends %j to the default instead", (value) => {
    expect(safeNext(value)).toBe("/ask");
  });

  it.each([null, undefined, 42])("treats a missing or non-string value (%j) as absent", (value) => {
    expect(safeNext(value)).toBe("/ask");
  });

  it("uses the fallback it is given", () => {
    expect(safeNext("//evil.example", "/welcome")).toBe("/welcome");
  });
});
