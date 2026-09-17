import { z } from "zod";

import type { SourceTable } from "@/lib/api/types";

export const UPLOAD_SUFFIXES = [".csv", ".tsv", ".xlsx", ".parquet"] as const;
export const MAX_UPLOAD_FILES = 20;
export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;

type Named = { name: string; size: number };

export function suffixOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot === -1 ? "" : name.slice(dot).toLowerCase();
}

export function stemOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot <= 0 ? name : name.slice(0, dot);
}

export function uploadProblem(file: Named): string | null {
  if (!(UPLOAD_SUFFIXES as readonly string[]).includes(suffixOf(file.name))) {
    return `${file.name} is not a CSV, TSV, Excel or Parquet file.`;
  }
  if (file.size > MAX_UPLOAD_BYTES) return `${file.name} is over the 25 MB limit.`;
  return null;
}

export function pick<T extends Named>(
  current: readonly T[],
  incoming: readonly T[],
  inDataset: readonly string[] = [],
): { files: T[]; problems: string[] } {
  const files = [...current];
  const problems: string[] = [];
  const existing = new Set(inDataset);
  const chosen = new Set(current.map((file) => file.name));

  for (const file of incoming) {
    let problem = uploadProblem(file);
    if (!problem && existing.has(file.name)) problem = `${file.name} is already in this dataset.`;
    if (!problem && chosen.has(file.name)) problem = `${file.name} is already chosen.`;
    if (!problem && files.length >= MAX_UPLOAD_FILES) {
      problem = `${file.name} was left out. Upload at most ${MAX_UPLOAD_FILES} files at a time.`;
    }
    if (problem) {
      problems.push(problem);
      continue;
    }
    chosen.add(file.name);
    files.push(file);
  }
  return { files, problems };
}

export const UploadedFiles = z
  .array(z.file())
  .min(1, { error: "Choose at least one file." })
  .max(MAX_UPLOAD_FILES, { error: `Upload at most ${MAX_UPLOAD_FILES} files at a time.` })
  .superRefine((files, ctx) => {
    for (const file of files) {
      const problem = uploadProblem(file);
      if (problem) ctx.addIssue({ code: "custom", message: problem });
    }
  });

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export type DatasetFile = { file: string; tables: string[] };

export function filesOf(tables: readonly SourceTable[]): DatasetFile[] {
  const byFile = new Map<string, string[]>();
  for (const table of tables) {
    if (table.file === null) continue;
    const names = byFile.get(table.file);
    if (names) names.push(table.name);
    else byFile.set(table.file, [table.name]);
  }
  return [...byFile]
    .map(([file, names]) => ({ file, tables: names }))
    .sort((a, b) => a.file.localeCompare(b.file));
}

export async function upload<T>(url: string, form: FormData): Promise<T> {
  const response = await fetch(url, { method: "POST", body: form });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const message = (body as { error?: unknown } | null)?.error;
    throw new Error(typeof message === "string" ? message : "The upload did not go through. Try again.");
  }
  return body as T;
}
