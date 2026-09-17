/**
 * Where to send someone after they sign in, taken from a `next` they could have been handed.
 *
 * Same-origin paths only. A crafted `next` is otherwise an open redirect that arrives with a
 * live session: `//host` and `/\host` are both read by browsers as another origin.
 */
export function safeNext(value: unknown, fallback = "/ask"): string {
  if (typeof value !== "string" || !value.startsWith("/")) return fallback;
  if (value.startsWith("//") || value.startsWith("/\\")) return fallback;
  return value;
}
