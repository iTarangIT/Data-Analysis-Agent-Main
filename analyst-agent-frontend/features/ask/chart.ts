import type { ChartSpec, ForecastSeries } from "@/lib/api/types";

import { isNumericCell, renderCell } from "./cells";
import type { Cell, ResultTable } from "./run-types";

/**
 * Turning a ChartSpec and a result table into something plottable.
 *
 * Separate from the component for the same reason `cells.ts` is: it is the place a mistake
 * ships a wrong figure rather than an ugly one. Two rules carry most of the weight.
 *
 * First, a point holds both a `value` and a `text`. The value is for geometry only. The text
 * is what the database actually sent -- "266300.00" with the trailing zero it chose, or an
 * integer past 2^53 that a double cannot hold -- and it is the only thing ever printed. A
 * chart that labels its bars from the parsed number is the same bug as calling Number() on a
 * table cell, just harder to notice.
 *
 * Second, three series is the ceiling. The palette here is one neutral hue stepped light to
 * dark, because the design system has no categorical colours to spend and `live` is reserved
 * for the machine working. Measured on that ramp a fourth step lands around dE 13 against its
 * neighbour, under the threshold where full-colour vision separates them, so a fourth series
 * would be drawn in a colour nobody can read. Past three, the table below carries the values.
 */

/** How many series the neutral ramp can separate. See the note above. */
export const MAX_SERIES = 3;

export type ChartPoint = {
  /** For geometry only. Never printed. */
  value: number;
  /** Exactly what the agent sent. The only thing printed. */
  text: string;
};

export type ChartSeries = {
  column: string;
  /** One entry per category, in row order. Null is a gap, not a zero. */
  points: (ChartPoint | null)[];
};

export type PlottableChart = {
  kind: "chart";
  type: ChartSpec["type"];
  xColumn: string;
  categories: string[];
  series: ChartSeries[];
  /** The domain to scale against. Always includes zero so bar lengths stay proportional. */
  min: number;
  max: number;
  /** Forecast only: the low-to-high range at each category, null where there is none. */
  band?: ({ lo: number; hi: number } | null)[];
  /** Forecast only: the index of the last actual point, where the forecast takes over. */
  split?: number;
  /** Forecast only: how much of the outcome the band is meant to hold. */
  interval?: number;
};

export type NoChart = { kind: "none"; reason: string };

function text(value: Cell): string {
  const rendered = renderCell(value);
  return rendered.kind === "null" ? "null" : rendered.text;
}

function point(value: Cell): ChartPoint | null {
  if (!isNumericCell(value)) return null;
  // Safe here and only here: the result feeds the drawing, never the label.
  return { value: Number(value), text: text(value) };
}

export function buildChart(spec: ChartSpec, result: ResultTable): PlottableChart | NoChart {
  // Drawn from the spec alone: it carries the cleaned series the forecast was made from,
  // which is not the raw rows the table below shows.
  if (spec.type === "forecast" && spec.forecast) return forecastChart(spec, spec.forecast);
  if (result.rows.length === 0) return { kind: "none", reason: "The query matched nothing." };

  const xIndex = result.columns.indexOf(spec.x);
  if (xIndex === -1) {
    return { kind: "none", reason: `The result has no column called ${spec.x}.` };
  }

  const plotted = spec.y
    .map((column) => ({ column, index: result.columns.indexOf(column) }))
    .filter((y) => y.index !== -1);

  if (plotted.length === 0) {
    return { kind: "none", reason: "None of the columns to plot are in the result." };
  }

  if (plotted.length > MAX_SERIES) {
    return {
      kind: "none",
      reason: `${plotted.length} series is more than a chart can tell apart. The table has every figure.`,
    };
  }

  const categories = result.rows.map((row) => text(row[xIndex]));
  const series = plotted.map(({ column, index }) => ({
    column,
    points: result.rows.map((row) => point(row[index])),
  }));

  const values = series.flatMap((s) => s.points.filter((p) => p !== null).map((p) => p.value));
  if (values.length === 0) {
    return { kind: "none", reason: "Nothing in those columns is a number." };
  }

  return {
    kind: "chart",
    type: spec.type,
    xColumn: spec.x,
    categories,
    series,
    min: Math.min(0, ...values),
    max: Math.max(0, ...values),
  };
}

function forecastChart(spec: ChartSpec, forecast: ForecastSeries): PlottableChart | NoChart {
  const { history, points, interval } = forecast;
  if (history.length === 0 || points.length === 0) {
    return { kind: "none", reason: "The forecast has nothing to draw." };
  }

  const split = history.length - 1;
  const [, last] = history[split];
  const actual = [...history.map(([, value]) => point(value)), ...points.map(() => null)];
  // Starts on the last actual point, so the dashed line leaves from where the solid one ends
  // and the band fans out from a single point rather than appearing from nowhere.
  const predicted = [
    ...history.map((_, i) => (i === split ? point(last) : null)),
    ...points.map(([, mean]) => point(mean)),
  ];
  const band = [
    ...history.map((_, i) => (i === split ? { lo: last, hi: last } : null)),
    ...points.map(([, , lo, hi]) => ({ lo, hi })),
  ];
  const values = [
    ...history.map(([, value]) => value),
    ...points.flatMap(([, mean, lo, hi]) => [mean, lo, hi]),
  ];

  return {
    kind: "chart",
    type: "forecast",
    xColumn: spec.x,
    categories: [...history.map(([period]) => period), ...points.map(([period]) => period)],
    series: [
      { column: spec.y[0], points: actual },
      { column: "forecast", points: predicted },
    ],
    band,
    split,
    interval,
    min: Math.min(0, ...values),
    max: Math.max(0, ...values),
  };
}

/** The forecast as rows, for the table under the chart. */
export function forecastTable(spec: ChartSpec): ResultTable | null {
  if (spec.type !== "forecast" || !spec.forecast) return null;
  const percent = `${Math.round(spec.forecast.interval * 100)}%`;
  return {
    columns: [spec.x, `${spec.y[0]} forecast`, `low (${percent})`, `high (${percent})`],
    rows: spec.forecast.points.map(([period, mean, lo, hi]) => [period, mean, lo, hi]),
    truncated: false,
  };
}
