/**
 * How long ago, in the shortest form that is still unambiguous.
 *
 * Deliberately not a library. Three thresholds and a date is the whole requirement, and the
 * fallback is `toLocaleDateString` so the reader's own locale decides the day-month order.
 */
export function when(iso: string): string {
  const date = new Date(iso);
  const minutes = Math.round((Date.now() - date.getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  if (minutes < 60 * 24) return `${Math.round(minutes / 60)}h ago`;
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/**
 * Which bucket a timestamp falls in, for grouping a list by day.
 *
 * Both sides are flattened to local midnight before the subtraction. Measuring the raw gap
 * instead would call 6pm yesterday "today" whenever the reader is more than six hours from
 * UTC, because a partial day floors to zero. Rounding the result absorbs the 23- and
 * 25-hour days either side of a clock change.
 */
export function dayBucket(iso: string): string {
  const date = new Date(iso);

  const startOfThatDay = new Date(date);
  startOfThatDay.setHours(0, 0, 0, 0);

  const startOfToday = new Date();
  startOfToday.setHours(0, 0, 0, 0);

  const days = Math.round(
    (startOfToday.getTime() - startOfThatDay.getTime()) / 86_400_000,
  );

  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}
