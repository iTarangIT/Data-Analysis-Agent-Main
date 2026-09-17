/**
 * The agent speaks three error shapes, not one, and a client that assumes a single shape
 * renders "undefined" on the two most common failures.
 *
 *   { "error": "connection not found" }        domain errors: 400, 401, 403, 404, 409, 429
 *   { "detail": "missing bearer token" }       auth failures raised as HTTPException
 *   { "detail": [ { "loc": [...], "msg": ...}] }   pydantic request validation, 422
 *
 * A dead upstream adds a fourth: HTML, or nothing at all.
 */

export type ApiErrorCode =
  | "unauthorized"
  | "forbidden"
  | "not_found"
  | "conflict"
  | "rate_limited"
  | "budget_exhausted"
  | "invalid_request"
  | "upstream"
  | "unknown";

export class ApiError extends Error {
  readonly status: number;
  readonly code: ApiErrorCode;
  /** Field name to message, when the failure was per-field. Drives inline form errors. */
  readonly fieldErrors: Record<string, string>;

  constructor(
    message: string,
    status: number,
    code: ApiErrorCode,
    fieldErrors: Record<string, string> = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.fieldErrors = fieldErrors;
  }
}

export function failureResponse(error: unknown, fallback: string): Response {
  const api = error instanceof ApiError ? error : new ApiError(fallback, 500, "unknown");
  return Response.json(
    { error: api.message, code: api.code, fieldErrors: api.fieldErrors },
    { status: api.status },
  );
}

function codeFor(status: number, message: string): ApiErrorCode {
  if (status === 401) return "unauthorized";
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 409) return "conflict";
  if (status === 422 || status === 400) return "invalid_request";
  if (status === 429) {
    // Both are 429 but they need different words: one says wait a moment, the other says
    // wait until tomorrow.
    return message.includes("budget") ? "budget_exhausted" : "rate_limited";
  }
  if (status >= 500) return "upstream";
  return "unknown";
}

type ValidationItem = { loc?: unknown[]; msg?: string };

/**
 * Pydantic prefixes its messages with machine wording. The rest of the sentence is usually
 * the useful part and worth keeping, so only the prefix is dropped.
 */
const MACHINE_PREFIX = /^(value error,\s*|value is not a valid [^:]+:\s*|assertion failed,\s*)/i;

function humanise(message: string): string {
  const trimmed = message.replace(MACHINE_PREFIX, "").trim();
  if (!trimmed) return message;
  return trimmed.charAt(0).toUpperCase() + trimmed.slice(1);
}

/** Turn pydantic's array into field name -> message. `loc` is ["body", "email"]. */
function fieldErrorsFrom(detail: ValidationItem[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const item of detail) {
    const path = Array.isArray(item.loc) ? item.loc : [];
    const field = path.filter((p) => p !== "body").join(".");
    if (field && item.msg && !out[field]) out[field] = humanise(item.msg);
  }
  return out;
}

/**
 * Read a failed response into one shape. Never throws: a parse failure here would replace a
 * real error with a confusing one.
 */
export async function normalizeAgentError(response: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // HTML from a proxy, or an empty body. Fall through to the status-only message.
  }

  let message = "";
  let fieldErrors: Record<string, string> = {};

  if (body && typeof body === "object") {
    const record = body as Record<string, unknown>;

    if (typeof record.error === "string") {
      message = record.error;
    } else if (typeof record.detail === "string") {
      message = record.detail;
    } else if (Array.isArray(record.detail)) {
      fieldErrors = fieldErrorsFrom(record.detail as ValidationItem[]);
      const first = Object.values(fieldErrors)[0];
      message = first ?? "that request was not valid";
    }
  }

  if (!message) {
    message =
      response.status >= 500
        ? "the analyst service is not responding"
        : `request failed (${response.status})`;
  }

  return new ApiError(message, response.status, codeFor(response.status, message), fieldErrors);
}
