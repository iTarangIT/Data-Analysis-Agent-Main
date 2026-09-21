import { z } from "zod";

import type {
  DatasetSource,
  DatasetSources,
  DriveListing,
  DriveNode,
  DryRun,
  ResolveResult,
  Rule,
} from "@/lib/api/types";

const RuleSchema = z.object({
  id: z.string(),
  kind: z.enum(["folder", "file", "sheet"]),
  recursive: z.boolean(),
});

export const DatasetSourceSchema: z.ZodType<DatasetSource> = z.object({
  id: z.string(),
  origin: z.enum(["upload", "gdrive_folder", "gdrive_file", "gsheet"]),
  label: z.string(),
  status: z.enum(["pending", "active"]),
  combine: z.boolean(),
  rules: z.array(RuleSchema),
  files: z.array(
    z.object({
      id: z.string(),
      name: z.string(),
      status: z.enum(["ready", "skipped", "failed"]),
      reason: z.string().nullable(),
      tables: z.array(z.string()),
    }),
  ),
});

export const DatasetSourcesSchema: z.ZodType<DatasetSources> = z.object({
  sync_status: z.enum(["syncing", "ready", "failed"]).nullable(),
  synced_at: z.string().nullable(),
  sources: z.array(DatasetSourceSchema),
});

export const ResolveResultSchema: z.ZodType<ResolveResult> = z.object({
  status: z.enum(["needs_share", "unverified", "resolved"]),
  share_with: z.string().nullable(),
  source: DatasetSourceSchema.nullable(),
});

export const DriveListingSchema: z.ZodType<DriveListing> = z.object({
  folder_id: z.string(),
  children: z.array(
    z.object({
      id: z.string(),
      name: z.string(),
      kind: z.enum(["folder", "sheet", "xlsx", "csv", "tsv", "pdf", "other"]),
      supported: z.boolean(),
      bytes: z.number().nullable(),
    }),
  ),
  supported: z.number(),
  unsupported: z.number(),
  bytes: z.number(),
});

export const DryRunSchema: z.ZodType<DryRun> = z.object({
  files: z.number(),
  bytes: z.number(),
  skipped: z.array(z.object({ name: z.string(), reason: z.string() })),
  fits: z.boolean(),
  limit: z.number(),
});

export const ORIGINS: Record<DatasetSource["origin"], string> = {
  upload: "Uploaded files",
  gdrive_folder: "Drive folder",
  gdrive_file: "Drive file",
  gsheet: "Google Sheet",
};

export type LinkStep =
  | { step: "idle" }
  | { step: "checking"; url: string; confirm: boolean }
  | { step: "needs_share"; url: string; shareWith: string }
  | { step: "unverified"; url: string }
  | { step: "resolved"; url: string; source: DatasetSource }
  | { step: "failed"; url: string; message: string };

export type LinkEvent =
  | { type: "check"; url: string }
  | { type: "confirm"; owner: boolean }
  | { type: "reply"; result: ResolveResult }
  | { type: "fail"; message: string };

export function nextStep(state: LinkStep, event: LinkEvent): LinkStep {
  if (event.type === "check") {
    return state.step === "checking" ? state : { step: "checking", url: event.url, confirm: false };
  }
  if (event.type === "confirm") {
    return state.step === "unverified" && event.owner
      ? { step: "checking", url: state.url, confirm: true }
      : state;
  }
  if (state.step !== "checking") return state;
  if (event.type === "fail") return { step: "failed", url: state.url, message: event.message };

  const { status, share_with, source } = event.result;
  if (status === "needs_share" && share_with) {
    return { step: "needs_share", url: state.url, shareWith: share_with };
  }
  if (status === "unverified") return { step: "unverified", url: state.url };
  if (status === "resolved" && source) return { step: "resolved", url: state.url, source };
  return { step: "failed", url: state.url, message: "That link could not be checked. Try again." };
}

export function ruleFor(origin: DatasetSource["origin"], node: DriveNode): Rule {
  if (origin === "gsheet") return { id: node.id, kind: "sheet", recursive: false };
  return { id: node.id, kind: node.kind === "folder" ? "folder" : "file", recursive: false };
}

export function toggleRule(rules: readonly Rule[], rule: Rule): Rule[] {
  return rules.some((kept) => kept.id === rule.id)
    ? rules.filter((kept) => kept.id !== rule.id)
    : [...rules, rule];
}

export function rulesFor(rules: readonly Rule[], recursive: boolean): Rule[] {
  return rules.map((rule) => ({ ...rule, recursive: rule.kind === "folder" && recursive }));
}

export function isCovered(
  node: Pick<DriveNode, "kind">,
  ancestors: readonly string[],
  rules: readonly Rule[],
  recursive: boolean,
): boolean {
  const folders = new Set(rules.filter((rule) => rule.kind === "folder").map((rule) => rule.id));
  if (recursive) return ancestors.some((id) => folders.has(id));
  const parent = ancestors.at(-1);
  return node.kind !== "folder" && parent !== undefined && folders.has(parent);
}

export function rowState(
  node: DriveNode,
  ancestors: readonly string[],
  rules: readonly Rule[],
  recursive: boolean,
): { checked: boolean; disabled: boolean } {
  if (!node.supported) return { checked: false, disabled: true };
  if (isCovered(node, ancestors, rules, recursive)) return { checked: true, disabled: true };
  return { checked: rules.some((rule) => rule.id === node.id), disabled: false };
}

export async function fetchJson<T>(
  url: string,
  init: { method?: "POST" | "DELETE"; body?: unknown } = {},
): Promise<T> {
  const response = await fetch(url, {
    method: init.method ?? "GET",
    headers: init.body === undefined ? undefined : { "content-type": "application/json" },
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const message = (body as { error?: unknown } | null)?.error;
    throw new Error(typeof message === "string" ? message : "That did not go through. Try again.");
  }
  return body as T;
}
