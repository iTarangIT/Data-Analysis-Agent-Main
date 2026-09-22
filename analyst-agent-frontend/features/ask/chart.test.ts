import { describe, expect, it } from "vitest";

import type { ChartSpec } from "@/lib/api/types";

import { buildChart, forecastTable } from "./chart";
import type { ResultTable } from "./run-types";

function table(columns: string[], rows: ResultTable["rows"]): ResultTable {
  return { columns, rows, truncated: false };
}

describe("buildChart", () => {
  it("plots one series in the order the rows arrived", () => {
    const chart = buildChart(
      { type: "bar", x: "dealer", y: ["revenue"] },
      table(
        ["dealer", "revenue"],
        [
          ["Pioneer", 300],
          ["Shakti", 100],
        ],
      ),
    );

    expect(chart.kind).toBe("chart");
    if (chart.kind !== "chart") return;
    expect(chart.categories).toEqual(["Pioneer", "Shakti"]);
    expect(chart.series).toHaveLength(1);
    expect(chart.series[0].column).toBe("revenue");
    expect(chart.series[0].points.map((p) => p?.value)).toEqual([300, 100]);
  });

  it("labels a decimal with the text the database sent, not the parsed number", () => {
    // Postgres NUMERIC arrives as "266300.00". Printing the parsed number would
    // drop the trailing zero the database chose to express.
    const chart = buildChart(
      { type: "bar", x: "region", y: ["takings"] },
      table(["region", "takings"], [["West", "266300.00"]]),
    );

    if (chart.kind !== "chart") throw new Error("expected a chart");
    expect(chart.series[0].points[0]).toEqual({ value: 266300, text: "266300.00" });
  });

  it("keeps an integer beyond what a double can hold", () => {
    // 9007199254740993 is 2^53 + 1. The geometry may round it; the label must not.
    const chart = buildChart(
      { type: "bar", x: "k", y: ["n"] },
      table(["k", "n"], [["a", "9007199254740993"]]),
    );

    if (chart.kind !== "chart") throw new Error("expected a chart");
    expect(chart.series[0].points[0]?.text).toBe("9007199254740993");
  });

  it("leaves a gap where a cell is null", () => {
    const chart = buildChart(
      { type: "line", x: "day", y: ["runs"] },
      table(
        ["day", "runs"],
        [
          ["Mon", 4],
          ["Tue", null],
        ],
      ),
    );

    if (chart.kind !== "chart") throw new Error("expected a chart");
    expect(chart.series[0].points).toEqual([{ value: 4, text: "4" }, null]);
  });

  it("leaves a gap where a cell is text that is not a number", () => {
    const chart = buildChart(
      { type: "bar", x: "k", y: ["n"] },
      table(
        ["k", "n"],
        [
          ["a", "unknown"],
          ["b", 7],
        ],
      ),
    );

    if (chart.kind !== "chart") throw new Error("expected a chart");
    expect(chart.series[0].points).toEqual([null, { value: 7, text: "7" }]);
  });

  it("refuses a spec whose x column is not in the result", () => {
    const chart = buildChart(
      { type: "bar", x: "missing", y: ["revenue"] },
      table(["dealer", "revenue"], [["Pioneer", 1]]),
    );

    expect(chart.kind).toBe("none");
  });

  it("refuses a spec when none of its y columns are in the result", () => {
    const chart = buildChart(
      { type: "bar", x: "dealer", y: ["profit"] },
      table(["dealer", "revenue"], [["Pioneer", 1]]),
    );

    expect(chart.kind).toBe("none");
  });

  it("drops a y column the result does not have and plots the rest", () => {
    const chart = buildChart(
      { type: "bar", x: "dealer", y: ["revenue", "profit"] },
      table(["dealer", "revenue"], [["Pioneer", 1]]),
    );

    if (chart.kind !== "chart") throw new Error("expected a chart");
    expect(chart.series.map((s) => s.column)).toEqual(["revenue"]);
  });

  it("refuses a fourth series, which no palette here can separate", () => {
    // The neutral ramp tops out at three steps: a fourth lands at dE 13 against
    // its neighbour, below the threshold full-colour vision can tell apart.
    const chart = buildChart(
      { type: "line", x: "day", y: ["a", "b", "c", "d"] },
      table(["day", "a", "b", "c", "d"], [["Mon", 1, 2, 3, 4]]),
    );

    expect(chart.kind).toBe("none");
  });

  it("refuses a result with no rows", () => {
    const chart = buildChart({ type: "bar", x: "dealer", y: ["revenue"] }, table(["dealer", "revenue"], []));

    expect(chart.kind).toBe("none");
  });

  it("refuses a result where every plotted cell is a gap", () => {
    const chart = buildChart(
      { type: "bar", x: "k", y: ["n"] },
      table(["k", "n"], [["a", null], ["b", "nope"]]),
    );

    expect(chart.kind).toBe("none");
  });

  it("anchors the domain at zero so bar lengths stay proportional", () => {
    const chart = buildChart(
      { type: "bar", x: "k", y: ["n"] },
      table(["k", "n"], [["a", 80], ["b", 100]]),
    );

    if (chart.kind !== "chart") throw new Error("expected a chart");
    expect(chart.min).toBe(0);
    expect(chart.max).toBe(100);
  });

  it("extends the domain below zero when a value is negative", () => {
    const chart = buildChart(
      { type: "line", x: "k", y: ["n"] },
      table(["k", "n"], [["a", -20], ["b", 60]]),
    );

    if (chart.kind !== "chart") throw new Error("expected a chart");
    expect(chart.min).toBe(-20);
    expect(chart.max).toBe(60);
  });

  it("prints a category from whatever the x cell was", () => {
    const chart = buildChart(
      { type: "bar", x: "k", y: ["n"] },
      table(["k", "n"], [[null, 1], [true, 2]]),
    );

    if (chart.kind !== "chart") throw new Error("expected a chart");
    expect(chart.categories).toEqual(["null", "true"]);
  });
});

const FORECAST: ChartSpec = {
  type: "forecast",
  x: "month",
  y: ["revenue"],
  forecast: {
    grain: "month",
    interval: 0.8,
    history: [
      ["2026-06", 100],
      ["2026-07", 120],
      ["2026-08", 110],
    ],
    points: [
      ["2026-09", 115, 105, 125],
      ["2026-10", 118, 100, 136],
    ],
  },
};

// The table shows the raw rows; a forecast draws from the cleaned series in its spec.
const NO_ROWS: ResultTable = { columns: [], rows: [], truncated: false };

function drawn(spec: ChartSpec) {
  const chart = buildChart(spec, NO_ROWS);
  if (chart.kind !== "chart") throw new Error(`expected a chart, got: ${chart.reason}`);
  return chart;
}

describe("buildChart for a forecast", () => {
  it("runs the forecast periods on after the history", () => {
    const chart = drawn(FORECAST);

    expect(chart.categories).toEqual(["2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]);
    expect(chart.split).toBe(2);
  });

  it("draws actuals only across the history", () => {
    expect(drawn(FORECAST).series[0].points.map((p) => p?.value ?? null)).toEqual([
      100, 120, 110, null, null,
    ]);
  });

  it("starts the forecast on the last actual point so the two lines meet", () => {
    const forecast = drawn(FORECAST).series[1];

    expect(forecast.column).toBe("forecast");
    expect(forecast.points.map((p) => p?.value ?? null)).toEqual([null, null, 110, 115, 118]);
  });

  it("fans the range out from the last actual point", () => {
    expect(drawn(FORECAST).band).toEqual([
      null,
      null,
      { lo: 110, hi: 110 },
      { lo: 105, hi: 125 },
      { lo: 100, hi: 136 },
    ]);
  });

  it("scales to the top of the range, not just the forecast line", () => {
    const chart = drawn(FORECAST);

    expect(chart.max).toBe(136);
    expect(chart.min).toBe(0);
  });
});

describe("forecastTable", () => {
  it("lists each forecast period with its range", () => {
    expect(forecastTable(FORECAST)).toEqual({
      columns: ["month", "revenue forecast", "low (80%)", "high (80%)"],
      rows: [
        ["2026-09", 115, 105, 125],
        ["2026-10", 118, 100, 136],
      ],
      truncated: false,
    });
  });

  it("is nothing for any other chart", () => {
    expect(forecastTable({ type: "line", x: "month", y: ["revenue"] })).toBeNull();
  });
});
