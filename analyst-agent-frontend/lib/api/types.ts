/** Mirrors the agent's `app/api/schemas.py`. Kept narrow: only what the UI actually reads. */

export type ConnectionKind = "postgres" | "file";

export type Connection = {
  id: string;
  name: string;
  kind: ConnectionKind;
  selected_tables: number;
  total_tables: number;
  file_count: number;
  catalog_refreshed_at: string | null;
  sync_status: "syncing" | "ready" | "failed" | null;
  synced_at: string | null;
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

/** What a table holds, measured from the catalog. */
export type TableStats = {
  rows: "empty" | "few" | "thousands" | "millions" | "nonempty" | "unknown";
  rows_approx?: number;
  rows_at_least?: boolean;
  covered_to?: string;
};

export type SourceTable = {
  name: string;
  files: string[];
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

export type Rule = {
  id: string;
  kind: "folder" | "file" | "sheet";
  recursive: boolean;
};

export type SourceFile = {
  id: string;
  name: string;
  status: "ready" | "skipped" | "failed";
  reason: string | null;
  tables: string[];
};

export type DatasetSource = {
  id: string;
  origin: "upload" | "gdrive_folder" | "gdrive_file" | "gsheet";
  label: string;
  status: "pending" | "active";
  combine: boolean;
  rules: Rule[];
  files: SourceFile[];
};

export type DatasetSources = {
  sync_status: Connection["sync_status"];
  synced_at: string | null;
  sources: DatasetSource[];
};

export type ResolveResult = {
  status: "needs_share" | "unverified" | "resolved";
  share_with: string | null;
  source: DatasetSource | null;
};

export type DriveNode = {
  id: string;
  name: string;
  kind: "folder" | "sheet" | "xlsx" | "csv" | "tsv" | "pdf" | "other";
  supported: boolean;
  bytes: number | null;
};

export type DriveListing = {
  folder_id: string;
  children: DriveNode[];
  supported: number;
  unsupported: number;
  bytes: number;
};

export type DryRun = {
  files: number;
  bytes: number;
  skipped: { name: string; reason: string }[];
  fits: boolean;
  limit: number;
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

export type ChartSpec = {
  type: "bar" | "line";
  x: string;
  y: string[];
};

/**
 * The agent's five contract stages.
 *
 * These are not a ladder. With bounded SQL retries the agent can go
 * `sql_gen -> sql_guard -> sql_gen` when the guard rejects a query and the model tries again,
 * so anything that renders them as a fixed five-step progress bar will lie on exactly the
 * runs worth looking at.
 */
export type Stage = "router" | "sql_gen" | "sql_guard" | "db_exec" | "answer";

/**
 * One pass at writing SQL. `rejected` means the guard or the database refused it and the model
 * could go again. Everything after those two arrives as the query is checked and run, so any of
 * it can be missing while a run is live. A saved run sends the missing ones as null.
 */
export type Attempt = {
  sql: string | null;
  rejected: boolean;
  /** The model's own plain-English account of the query. Empty when it gave none. */
  what?: string;
  why?: string;
  reason?: string | null;
  at?: "guard" | "database" | null;
  rows?: number | null;
  truncated?: boolean | null;
  ms?: number | null;
};

/** How a saved run went, recorded exactly as its stream reported it. Row counts, never rows. */
export type RunTrace = {
  stages: Stage[];
  attempts: Attempt[];
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
  /** Null for every run saved before steps were recorded. */
  trace: RunTrace | null;
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
