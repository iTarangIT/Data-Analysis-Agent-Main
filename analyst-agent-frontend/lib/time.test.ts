import { describe, expect, it, vi, afterEach, beforeEach } from "vitest";

import { dayBucket, when } from "./time";

const NOW = new Date("2026-09-11T12:00:00Z");

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("when", () => {
  it("says just now for anything inside the last minute", () => {
    expect(when("2026-09-11T11:59:40Z")).toBe("just now");
  });

  it("counts minutes for the first hour", () => {
    expect(when("2026-09-11T11:20:00Z")).toBe("40m ago");
  });

  it("counts hours for the first day", () => {
    expect(when("2026-09-11T04:00:00Z")).toBe("8h ago");
  });

  it("falls back to a date once it is more than a day old", () => {
    expect(when("2026-09-01T12:00:00Z")).not.toMatch(/ago|just now/);
  });
});

describe("dayBucket", () => {
  it("buckets this morning as today", () => {
    expect(dayBucket(NOW.toISOString())).toBe("Today");
  });

  it("buckets the day before as yesterday", () => {
    const yesterday = new Date(NOW.getTime() - 86_400_000);
    expect(dayBucket(yesterday.toISOString())).toBe("Yesterday");
  });

  it("names the day for anything older", () => {
    const lastWeek = new Date(NOW.getTime() - 7 * 86_400_000);
    expect(dayBucket(lastWeek.toISOString())).not.toMatch(/Today|Yesterday/);
  });
});
