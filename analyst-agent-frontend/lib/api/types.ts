/** Mirrors the agent's `app/api/schemas.py`. Kept narrow: only what the UI actually reads. */

export type ConnectionKind = "postgres" | "web" | "file";

export type Connection = {
  id: string;
  name: string;
  kind: ConnectionKind;
  has_schema_cache: boolean;
};

export type User = {
  id: string;
  email: string;
  name: string | null;
  role: string;
  tenant_id: string;
  tenant_name: string;
  plan: string;
  created_at: string;
};

export type AuthResponse = {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  refresh_token: string;
  refresh_expires_in: number;
  user: User;
};

export type ChartSpec = {
  type: "bar" | "line";
  x: string;
  y: string[];
};

export type RunSummary = {
  id: string;
  thread_id: string;
  question: string;
  status: "running" | "done" | "error";
  tool: string | null;
  connection_id: string;
  connection_name: string | null;
  rows_returned: number;
  duration_ms: number;
  created_at: string;
  has_sql: boolean;
  has_answer: boolean;
};

export type RunPage = {
  items: RunSummary[];
  /** Keyset. Null means there is no further page. */
  next_cursor: string | null;
};

export type RunDetail = {
  id: string;
  connection_id: string;
  thread_id: string;
  question: string;
  status: string;
  tool: string | null;
  sql: string | null;
  /** Null means not recorded, which every run predating the column is. */
  answer: string | null;
  error: string | null;
  model: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  rows_returned: number;
  chart: ChartSpec | null;
  duration_ms: number;
  created_at: string;
};

export type Thread = {
  thread_id: string;
  title: string;
  run_count: number;
  last_run_at: string;
  last_status: string;
  connection_id: string;
};
