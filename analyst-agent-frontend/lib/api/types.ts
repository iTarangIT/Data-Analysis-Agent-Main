/** Mirrors the agent's `app/api/schemas.py`. Kept narrow: only what the UI actually reads. */

export type ConnectionKind = "postgres" | "file";

export type Connection = {
  id: string;
  name: string;
  kind: ConnectionKind;
  selected_tables: number;
  total_tables: number;
  catalog_refreshed_at: string | null;
};

export type ColumnDefinition = {
  name: string;
  type: string;
  nullable: boolean;
  comment: string | null;
};

export type ForeignKey = {
  columns: string[];
  ref_table: string;
  ref_columns: string[];
};

/** A table's structure as the agent reads it: columns and keys, never rows. */
export type TableDefinition = {
  name: string;
  comment: string | null;
  columns: ColumnDefinition[];
  primary_key: string[];
  uniques: string[][];
  foreign_keys: ForeignKey[];
  checks: string[];
};

/** What a table holds, measured from the catalog. Postgres only; a spreadsheet reports none. */
export type TableStats = {
  rows: "empty" | "few" | "thousands" | "millions" | "nonempty" | "unknown";
  rows_approx?: number;
  rows_at_least?: boolean;
  covered_to?: string;
};

export type SourceTable = {
  name: string;
  selected: boolean;
  /** Both null unless the table is chosen: the agent keeps no structure it may not use. */
  definition: TableDefinition | null;
  stats: TableStats | null;
};

export type Relationship = {
  from_table: string;
  from_columns: string[];
  to_table: string;
  to_columns: string[];
  /** `inferred` is a match of column names with no key declared behind it. */
  origin: "declared" | "inferred";
  cardinality: "many_to_one" | "one_to_one";
};

export type ConnectionTables = {
  max_selected: number;
  refreshed_at: string | null;
  tables: SourceTable[];
  /** Between chosen tables only. */
  relationships: Relationship[];
};

export type TablesRefresh = ConnectionTables & {
  added: string[];
  removed: string[];
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

/** One calendar day of the tenant's activity, as the agent buckets it. */
export type UsageDay = {
  /** `YYYY-MM-DD`, UTC. */
  day: string;
  runs: number;
  prompt_tokens: number;
  completion_tokens: number;
  rows_returned: number;
  errors: number;
};

export type Usage = {
  daily_token_budget: number;
  /**
   * A rolling window, not a calendar day. This is the figure the agent compares against
   * the budget when it refuses a run, so it is the only one a capacity bar may use --
   * summing the last `UsageDay` instead would disagree with the error people actually hit.
   */
  tokens_last_24h: number;
  runs_last_24h: number;
  days: UsageDay[];
};
