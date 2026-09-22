"use client";

import { buildChart, type ChartPoint, type PlottableChart } from "@/features/ask/chart";
import type { ResultTable } from "@/features/ask/run-types";
import type { ChartSpec } from "@/lib/api/types";

/**
 * The chart.
 *
 * The agent has been sending a `chart` event all along and nothing drew it. It carries a type,
 * one x column and up to a few y columns; everything else is read off the rows that came back.
 *
 * Colour is one neutral hue stepped light to dark, because the design system has no
 * categorical palette to spend and `live` means the machine is working. That ramp separates
 * three series and no more, which `buildChart` enforces rather than this component.
 *
 * Every printed figure comes from the point's `text`, which is what the database sent. The
 * parsed number only ever decides how long a bar is.
 */

// Literal strings so Tailwind's scanner sees them.
const FILL = ["bg-series-1", "bg-series-2", "bg-series-3"] as const;
const STROKE = ["stroke-series-1", "stroke-series-2", "stroke-series-3"] as const;
const DOT = ["fill-series-1", "fill-series-2", "fill-series-3"] as const;

const LINE_WIDTH = 880;
const LINE_HEIGHT = 140;

export function ResultChart({ spec, result }: { spec: ChartSpec; result: ResultTable }) {
  const chart = buildChart(spec, result);

  // A chart that cannot be drawn honestly is not drawn. The table is directly below.
  if (chart.kind === "none") return null;

  return (
    <figure className="m-0 flex min-w-0 flex-col overflow-hidden rounded-xl border border-line bg-surface shadow-card">
      <figcaption className="flex items-baseline justify-between gap-3 border-b border-line px-4 py-2.5">
        <span className="min-w-0 truncate text-xs font-medium text-ink-muted">
          {chart.type === "forecast"
            ? `${chart.series[0].column} by ${chart.xColumn}, with a forecast`
            : `${chart.series.map((s) => s.column).join(", ")} by ${chart.xColumn}`}
        </span>
        <span className="shrink-0 font-mono text-[0.6875rem] text-ink-faint">{chart.type}</span>
      </figcaption>

      {chart.series.length > 1 ? <Legend chart={chart} /> : null}

      {chart.type === "bar" ? <Bars chart={chart} /> : <Line chart={chart} />}
    </figure>
  );
}

function Legend({ chart }: { chart: PlottableChart }) {
  return (
    <ul className="flex flex-wrap gap-4 border-b border-line px-3 py-2">
      {chart.series.map((series, i) => (
        <li key={series.column} className="flex items-center gap-2">
          <span aria-hidden className={`h-2.5 w-2.5 rounded-xs ${FILL[i]}`} />
          <span className="font-mono text-[0.75rem] text-ink-muted">{series.column}</span>
        </li>
      ))}
      {chart.band && chart.interval !== undefined ? (
        <li className="flex items-center gap-2">
          <span aria-hidden className="h-2.5 w-2.5 rounded-xs bg-series-3 opacity-60" />
          <span className="font-mono text-[0.75rem] text-ink-muted">
            {Math.round(chart.interval * 100)}% range
          </span>
        </li>
      ) : null}
    </ul>
  );
}

/** Where a value sits across the domain, 0 to 100. */
function percent(value: number, chart: PlottableChart): number {
  const span = chart.max - chart.min;
  if (span === 0) return 0;
  return ((value - chart.min) / span) * 100;
}

function Bars({ chart }: { chart: PlottableChart }) {
  // With no negatives this is 0 and every bar simply starts at the left edge.
  const zero = percent(0, chart);

  return (
    <div className="flex flex-col gap-3 px-3 py-4">
      {chart.categories.map((category, row) => (
        <div key={`${category}-${row}`} className="flex items-start gap-3">
          <span
            title={category}
            className="w-[11rem] shrink-0 truncate pt-0.5 text-[0.8125rem] text-ink"
          >
            {category}
          </span>

          <div className="flex min-w-0 flex-1 flex-col gap-0.5">
            {chart.series.map((series, i) => (
              <Bar
                key={series.column}
                point={series.points[row]}
                column={series.column}
                zero={zero}
                chart={chart}
                fill={FILL[i]}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function Bar({
  point,
  column,
  zero,
  chart,
  fill,
}: {
  point: ChartPoint | null;
  column: string;
  zero: number;
  chart: PlottableChart;
  fill: string;
}) {
  if (!point) {
    return <span className="font-mono text-[0.75rem] text-ink-muted">no value</span>;
  }

  const at = percent(point.value, chart);
  const left = Math.min(zero, at);
  const width = Math.abs(at - zero);

  return (
    <span className="group flex items-center gap-2">
      <span className="relative h-5 min-w-0 flex-1">
        <span
          aria-hidden
          style={{ left: `${left}%`, width: `${Math.max(width, 0.4)}%` }}
          // Flat against the baseline, rounded only at the end the data reaches.
          className={`absolute inset-y-0 rounded-e-[4px] ${fill}`}
        />
      </span>
      <span className="shrink-0 font-mono text-[0.75rem] tabular-nums text-ink-muted">
        <span className="sr-only">{column}: </span>
        {point.text}
      </span>
    </span>
  );
}

function Line({ chart }: { chart: PlottableChart }) {
  const step = chart.categories.length > 1 ? LINE_WIDTH / (chart.categories.length - 1) : 0;
  // Where the forecast takes over, as a share of the width. Near either edge its label would sit
  // on top of the first or last one, which is the common case for a one-period forecast.
  const splitAt = chart.split === undefined ? null : ((chart.split * step) / LINE_WIDTH) * 100;
  const labelSplit = splitAt !== null && splitAt > 15 && splitAt < 85;

  function x(index: number): number {
    return chart.categories.length > 1 ? index * step : LINE_WIDTH / 2;
  }

  function y(value: number): number {
    return LINE_HEIGHT - (percent(value, chart) / 100) * LINE_HEIGHT;
  }

  return (
    <div className="px-3 py-4">
      <svg
        viewBox={`-4 -8 ${LINE_WIDTH + 8} ${LINE_HEIGHT + 16}`}
        className="w-full"
        role="img"
        aria-label={summarise(chart)}
      >
        <line
          x1={0}
          y1={y(0)}
          x2={LINE_WIDTH}
          y2={y(0)}
          className="stroke-line"
          strokeWidth={1}
        />

        {chart.band ? (
          <polygon className="fill-series-3 opacity-60" points={bandPoints(chart.band, x, y)} />
        ) : null}

        {chart.split !== undefined ? (
          <line
            x1={x(chart.split)}
            y1={0}
            x2={x(chart.split)}
            y2={LINE_HEIGHT}
            className="stroke-line-strong"
            strokeWidth={1}
            strokeDasharray="3 3"
          />
        ) : null}

        {chart.series.map((series, i) =>
          // A gap breaks the line rather than being drawn through.
          runs(series.points).map((run, r) => (
            <polyline
              key={`${series.column}-${r}`}
              fill="none"
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
              className={STROKE[i]}
              strokeDasharray={chart.type === "forecast" && i === 1 ? "6 5" : undefined}
              points={run.map(({ index, point }) => `${x(index)},${y(point.value)}`).join(" ")}
            />
          )),
        )}

        {chart.series.map((series, i) => {
          const last = lastPoint(series.points);
          if (!last) return null;
          return (
            <circle
              key={series.column}
              cx={x(last.index)}
              cy={y(last.point.value)}
              r={4.5}
              // Ringed in the surface colour so the mark stays legible on the line.
              className={`${DOT[i]} stroke-surface`}
              strokeWidth={2}
            />
          );
        })}
      </svg>

      <div className="relative mt-1 flex justify-between font-mono text-[0.75rem] text-ink-muted">
        <span>{chart.categories[0]}</span>
        {labelSplit && chart.split !== undefined ? (
          <span className="absolute -translate-x-1/2 text-ink" style={{ left: `${splitAt}%` }}>
            {chart.categories[chart.split]}
          </span>
        ) : null}
        <span>{chart.categories[chart.categories.length - 1]}</span>
      </div>
    </div>
  );
}

type Indexed = { index: number; point: ChartPoint };

/** Contiguous stretches of real points, so a gap is a break and not a straight line through. */
function runs(points: (ChartPoint | null)[]): Indexed[][] {
  const out: Indexed[][] = [];
  let current: Indexed[] = [];

  points.forEach((point, index) => {
    if (point) {
      current.push({ index, point });
      return;
    }
    if (current.length > 0) out.push(current);
    current = [];
  });

  if (current.length > 0) out.push(current);
  return out.filter((run) => run.length > 1);
}

function lastPoint(points: (ChartPoint | null)[]): Indexed | null {
  for (let i = points.length - 1; i >= 0; i--) {
    const point = points[i];
    if (point) return { index: i, point };
  }
  return null;
}

/** The band as one closed shape: along the top edge left to right, back along the bottom. */
function bandPoints(
  band: ({ lo: number; hi: number } | null)[],
  x: (index: number) => number,
  y: (value: number) => number,
): string {
  const edge = band.flatMap((b, index) => (b ? [{ index, ...b }] : []));
  const top = edge.map((p) => `${x(p.index)},${y(p.hi)}`);
  const bottom = [...edge].reverse().map((p) => `${x(p.index)},${y(p.lo)}`);
  return [...top, ...bottom].join(" ");
}

function summarise(chart: PlottableChart): string {
  if (chart.type === "forecast" && chart.split !== undefined) {
    const ahead = chart.categories.length - chart.split - 1;
    return `${chart.series[0].column} by ${chart.xColumn}, ${chart.split + 1} actual points then a ${ahead}-point forecast, from ${chart.min} to ${chart.max}.`;
  }
  const names = chart.series.map((s) => s.column).join(", ");
  return `${names} by ${chart.xColumn}, ${chart.categories.length} points, from ${chart.min} to ${chart.max}.`;
}
