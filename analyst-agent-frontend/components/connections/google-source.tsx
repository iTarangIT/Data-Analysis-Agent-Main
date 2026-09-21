"use client";

import {
  AlertTriangle,
  ChevronRight,
  File as FileIcon,
  FileSpreadsheet,
  FileText,
  Folder,
  Loader2,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState, useTransition } from "react";
import { toast } from "sonner";

import { CodeBlock } from "@/components/code-block";
import { Eyebrow, Panel } from "@/components/panel";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  type LinkEvent,
  type LinkStep,
  ORIGINS,
  fetchJson,
  nextStep,
  rowState,
  ruleFor,
  rulesFor,
  toggleRule,
} from "@/features/connections/google";
import { formatBytes } from "@/features/connections/uploads";
import type {
  Connection,
  DatasetSource,
  DriveListing,
  DriveNode,
  DryRun,
  ResolveResult,
  Rule,
} from "@/lib/api/types";
import { cn } from "@/lib/utils";

const KINDS: Record<DriveNode["kind"], string> = {
  folder: "Folder",
  sheet: "Google Sheet",
  xlsx: "Excel",
  csv: "CSV",
  tsv: "TSV",
  pdf: "PDF",
  other: "Other file",
};

function treePath(connectionId: string, sourceId: string, folderId?: string): string {
  const query = new URLSearchParams({ source_id: sourceId });
  if (folderId) query.set("folder_id", folderId);
  return `/api/connections/${encodeURIComponent(connectionId)}/google/tree?${query}`;
}

function detail(node: DriveNode, listing: DriveListing | undefined): string {
  if (!node.supported) return `${KINDS[node.kind]}, not supported`;
  if (listing) {
    const parts = [
      `${listing.supported} ${listing.supported === 1 ? "item" : "items"}`,
      formatBytes(listing.bytes),
    ];
    if (listing.unsupported) parts.push(`${listing.unsupported} not supported`);
    return parts.join(" · ");
  }
  return node.bytes === null ? KINDS[node.kind] : `${KINDS[node.kind]} · ${formatBytes(node.bytes)}`;
}

function Icon({ kind }: { kind: DriveNode["kind"] }) {
  const className = "size-4 shrink-0 text-ink-muted";
  if (kind === "folder") return <Folder aria-hidden className={className} strokeWidth={1.75} />;
  if (kind === "pdf") return <FileText aria-hidden className={className} strokeWidth={1.75} />;
  if (kind === "other") return <FileIcon aria-hidden className={className} strokeWidth={1.75} />;
  return <FileSpreadsheet aria-hidden className={className} strokeWidth={1.75} />;
}

function Toggle({
  checked,
  onChange,
  disabled,
  children,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled: boolean;
  children: React.ReactNode;
}) {
  return (
    <label
      className={cn(
        "flex items-center gap-2.5 text-[0.8125rem] text-ink",
        disabled ? "cursor-not-allowed" : "cursor-pointer",
      )}
    >
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
        className="size-4 shrink-0 accent-brand"
      />
      {children}
    </label>
  );
}

function SizeMeter({ run }: { run: DryRun }) {
  const percent = run.limit > 0 ? Math.min(100, Math.round((run.bytes / run.limit) * 100)) : 100;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-2 text-[0.75rem]">
        <span className="text-ink">
          <span className="font-mono tabular-nums">{run.files}</span>{" "}
          {run.files === 1 ? "file" : "files"}, about{" "}
          <span className="font-mono tabular-nums">{formatBytes(run.bytes)}</span>
        </span>
        <span className="font-mono text-ink-muted tabular-nums">of {formatBytes(run.limit)}</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-surface-sunk">
        <div
          className={cn("h-full rounded-full transition-all", run.fits ? "bg-brand" : "bg-fault")}
          style={{ width: `${Math.max(percent, 1)}%` }}
        />
      </div>
      {run.fits ? null : (
        <p className="text-[0.75rem] text-fault">
          That is more than a dataset can hold. Files past the limit will be skipped.
        </p>
      )}
      {run.skipped.length > 0 ? (
        <ul className="flex max-h-40 flex-col gap-1 overflow-y-auto rounded-md border border-warning/30 bg-warning/5 px-3 py-2.5">
          {run.skipped.map((skip, index) => (
            <li
              key={`${skip.name}-${index}`}
              className="flex items-start gap-2 text-[0.75rem] leading-relaxed text-ink"
            >
              <AlertTriangle aria-hidden className="mt-0.5 size-3.5 shrink-0 text-warning" strokeWidth={2} />
              <span>
                {skip.name} will be skipped: {skip.reason}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function FolderTree({
  root,
  label,
  list,
  rules,
  recursive,
  disabled,
  onPick,
}: {
  root: DriveListing;
  label: string;
  list: (folderId: string) => Promise<DriveListing>;
  rules: readonly Rule[];
  recursive: boolean;
  disabled: boolean;
  onPick: (node: DriveNode) => void;
}) {
  const [listings, setListings] = useState<Record<string, DriveListing>>(() => ({
    [root.folder_id]: root,
  }));
  const [open, setOpen] = useState<ReadonlySet<string>>(() => new Set([root.folder_id]));
  const [failures, setFailures] = useState<Record<string, string>>({});

  async function toggle(id: string) {
    const opening = !open.has(id);
    setOpen((current) => {
      const next = new Set(current);
      if (opening) next.add(id);
      else next.delete(id);
      return next;
    });
    if (!opening || listings[id]) return;
    setFailures((current) => {
      const next = { ...current };
      delete next[id];
      return next;
    });
    try {
      const listing = await list(id);
      setListings((current) => ({ ...current, [id]: listing }));
    } catch (failure) {
      setFailures((current) => ({ ...current, [id]: (failure as Error).message }));
    }
  }

  function row(node: DriveNode, ancestors: string[]): React.ReactNode {
    const state = rowState(node, ancestors, rules, recursive);
    const folder = node.kind === "folder";
    const expanded = folder && open.has(node.id);
    const listing = listings[node.id];
    const failure = failures[node.id];
    const locked = disabled || state.disabled;

    return (
      <li key={node.id}>
        <div className="flex min-w-0 items-center gap-1">
          {folder ? (
            <button
              type="button"
              onClick={() => void toggle(node.id)}
              aria-expanded={expanded}
              aria-label={`${expanded ? "Close" : "Open"} ${node.name}`}
              className="flex size-7 shrink-0 items-center justify-center rounded-md text-ink-faint transition-colors hover:bg-surface-sunk hover:text-ink"
            >
              <ChevronRight
                aria-hidden
                className={cn("size-3.5", expanded && "rotate-90")}
                strokeWidth={2}
              />
            </button>
          ) : (
            <span aria-hidden className="size-7 shrink-0" />
          )}
          <label
            className={cn(
              "flex min-w-0 flex-1 items-center gap-3 rounded-md px-2 py-1.5 transition-colors",
              locked ? "cursor-not-allowed" : "cursor-pointer hover:bg-surface-sunk",
            )}
          >
            <input
              type="checkbox"
              checked={state.checked}
              disabled={locked}
              onChange={() => onPick(node)}
              className="size-4 shrink-0 accent-brand"
            />
            <Icon kind={node.kind} />
            <span
              className={cn(
                "min-w-0 truncate text-[0.8125rem]",
                node.supported ? "text-ink" : "text-ink-faint",
              )}
            >
              {node.name}
            </span>
            <span className="ml-auto shrink-0 text-[0.75rem] text-ink-faint">
              {detail(node, listing)}
            </span>
          </label>
        </div>

        {expanded ? (
          <ul className="ml-3.5 border-l border-line pl-2">
            {listing ? listing.children.map((child) => row(child, [...ancestors, node.id])) : null}
            {listing && listing.children.length === 0 ? (
              <li className="px-2 py-1.5 text-[0.75rem] text-ink-muted">Nothing in this folder.</li>
            ) : null}
            {!listing && failure ? (
              <li className="px-2 py-1.5 text-[0.75rem] text-fault">{failure}</li>
            ) : null}
            {!listing && !failure ? (
              <li className="flex items-center gap-2 px-2 py-1.5 text-[0.75rem] text-ink-muted">
                <Loader2 aria-hidden className="size-3.5 animate-spin" />
                Listing
              </li>
            ) : null}
          </ul>
        ) : null}
      </li>
    );
  }

  return (
    <ul className="max-h-[26rem] overflow-y-auto rounded-md border border-line p-1">
      {row({ id: root.folder_id, name: label, kind: "folder", supported: true, bytes: null }, [])}
    </ul>
  );
}

export function GoogleSource({
  connectionId,
  isOwner,
  onCancel,
  onDone,
}: {
  connectionId?: string;
  isOwner: boolean;
  onCancel?: () => void;
  onDone?: (source: DatasetSource) => void;
}) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [nameError, setNameError] = useState<string | null>(null);
  const [urlError, setUrlError] = useState<string | null>(null);
  const [datasetId, setDatasetId] = useState<string | null>(connectionId ?? null);
  const [link, setLink] = useState<LinkStep>({ step: "idle" });
  const [root, setRoot] = useState<DriveListing | null>(null);
  const [chosen, setChosen] = useState<Rule[]>([]);
  const [recursive, setRecursive] = useState(true);
  const [combine, setCombine] = useState(true);
  const [estimate, setEstimate] = useState<{
    rules: Rule[];
    run: DryRun | null;
    error: string | null;
  } | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, startSaving] = useTransition();

  const source = link.step === "resolved" ? link.source : null;
  const rules = useMemo(() => rulesFor(chosen, recursive), [chosen, recursive]);
  const checking = link.step === "checking";
  const error = link.step === "failed" ? link.message : saveError;
  const shown = estimate?.rules === rules ? estimate : null;

  useEffect(() => {
    if (!datasetId || source?.origin !== "gdrive_folder" || rules.length === 0) return;
    let live = true;
    const timer = setTimeout(async () => {
      try {
        const run = await fetchJson<DryRun>(
          `/api/connections/${encodeURIComponent(datasetId)}/sources`,
          { method: "POST", body: { source_id: source.id, rules, combine, dry_run: true } },
        );
        if (live) setEstimate({ rules, run, error: null });
      } catch (failure) {
        if (live) setEstimate({ rules, run: null, error: (failure as Error).message });
      }
    }, 500);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [datasetId, source, rules, combine]);

  async function resolve(target: string, confirm: boolean) {
    try {
      let id = datasetId;
      if (!id) {
        id = (
          await fetchJson<Connection>("/api/connections/dataset", {
            method: "POST",
            body: { name: name.trim() },
          })
        ).id;
        setDatasetId(id);
      }
      const result = await fetchJson<ResolveResult>(
        `/api/connections/${encodeURIComponent(id)}/google/resolve`,
        {
          method: "POST",
          body: confirm ? { url: target, confirm_unverified: true } : { url: target },
        },
      );
      const found = result.status === "resolved" ? result.source : null;
      if (found) {
        setRoot(
          found.origin === "gdrive_file"
            ? null
            : await fetchJson<DriveListing>(treePath(id, found.id)),
        );
        setChosen(found.rules);
        setCombine(found.combine);
      }
      setLink((current) => nextStep(current, { type: "reply", result }));
    } catch (failure) {
      setLink((current) => nextStep(current, { type: "fail", message: (failure as Error).message }));
    }
  }

  function start(event: LinkEvent) {
    const next = nextStep(link, event);
    if (next === link) return;
    setLink(next);
    if (next.step === "checking") void resolve(next.url, next.confirm);
  }

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const needsName = datasetId === null && !name.trim();
    const target = url.trim();
    setNameError(needsName ? "Name this dataset." : null);
    setUrlError(target ? null : "Paste a Google Drive or Google Sheets link.");
    if (needsName || !target) return;
    start({ type: "check", url: target });
  }

  function pick(node: DriveNode) {
    if (!source) return;
    const rule = ruleFor(source.origin, node);
    setChosen((current) => toggleRule(current, rule));
  }

  function add() {
    if (!source || !datasetId) return;
    const id = datasetId;
    setSaveError(null);
    startSaving(async () => {
      let saved: DatasetSource;
      try {
        saved = await fetchJson<DatasetSource>(
          `/api/connections/${encodeURIComponent(id)}/sources`,
          { method: "POST", body: { source_id: source.id, rules, combine } },
        );
      } catch (failure) {
        setSaveError((failure as Error).message);
        return;
      }
      toast.success(`Added ${saved.label}. Its files are being read now.`);
      router.refresh();
      if (onDone) onDone(saved);
      else router.push(`/connections/${encodeURIComponent(id)}/tables`);
    });
  }

  return (
    <Panel className="p-5">
      <Eyebrow>Google Drive or Sheets</Eyebrow>

      <div className="mt-4 flex flex-col gap-4">
        {error ? (
          <p
            role="alert"
            className="flex items-start gap-2.5 rounded-md border border-fault/30 bg-fault-soft px-3 py-2.5 text-[0.8125rem] text-fault"
          >
            <AlertTriangle aria-hidden className="mt-px size-4 shrink-0" strokeWidth={2} />
            <span>{error}</span>
          </p>
        ) : null}

        {source && datasetId ? (
          <>
            <div className="flex min-w-0 items-center gap-3 rounded-md border border-line bg-surface-sunk px-3 py-2.5">
              <Icon kind={source.origin === "gdrive_folder" ? "folder" : "sheet"} />
              <div className="min-w-0">
                <p className="truncate text-[0.875rem] font-medium text-ink">{source.label}</p>
                <p className="text-[0.75rem] text-ink-muted">{ORIGINS[source.origin]}</p>
              </div>
            </div>

            {source.origin === "gdrive_folder" && root ? (
              <>
                <p className="text-[0.8125rem] leading-relaxed text-ink-muted">
                  Tick a folder to take everything in it, or tick single files. Files that cannot
                  be read are listed but cannot be chosen.
                </p>
                <div className="flex flex-wrap gap-x-5 gap-y-2">
                  <Toggle checked={recursive} onChange={setRecursive} disabled={saving}>
                    Include subfolders
                  </Toggle>
                  <Toggle checked={combine} onChange={setCombine} disabled={saving}>
                    Combine files with the same columns into one table
                  </Toggle>
                </div>
                <FolderTree
                  key={root.folder_id}
                  root={root}
                  label={source.label}
                  list={(folderId) =>
                    fetchJson<DriveListing>(treePath(datasetId, source.id, folderId))
                  }
                  rules={chosen}
                  recursive={recursive}
                  disabled={saving}
                  onPick={pick}
                />
                {rules.length === 0 ? (
                  <p className="text-[0.75rem] text-ink-muted">Choose at least one folder or file.</p>
                ) : shown?.run ? (
                  <SizeMeter run={shown.run} />
                ) : shown?.error ? (
                  <p className="text-[0.75rem] text-fault">{shown.error}</p>
                ) : (
                  <p className="flex items-center gap-2 text-[0.75rem] text-ink-muted">
                    <Loader2 aria-hidden className="size-3.5 animate-spin" />
                    Working out the size
                  </p>
                )}
              </>
            ) : null}

            {source.origin === "gsheet" && root ? (
              <>
                <p className="text-[0.8125rem] leading-relaxed text-ink-muted">
                  Tick the tabs to read. Each one becomes a table.
                </p>
                <ul className="flex max-h-[22rem] flex-col overflow-y-auto rounded-md border border-line p-1">
                  {root.children.map((tab) => {
                    const state = rowState(tab, [], chosen, false);
                    const locked = saving || state.disabled;
                    return (
                      <li key={tab.id}>
                        <label
                          className={cn(
                            "flex items-center gap-3 rounded-md px-3 py-2 transition-colors",
                            locked ? "cursor-not-allowed" : "cursor-pointer hover:bg-surface-sunk",
                          )}
                        >
                          <input
                            type="checkbox"
                            checked={state.checked}
                            disabled={locked}
                            onChange={() => pick(tab)}
                            className="size-4 shrink-0 accent-brand"
                          />
                          <span
                            className={cn(
                              "min-w-0 truncate text-[0.8125rem]",
                              tab.supported ? "text-ink" : "text-ink-faint",
                            )}
                          >
                            {tab.name}
                          </span>
                          {tab.supported ? null : (
                            <span className="ml-auto shrink-0 text-[0.75rem] text-ink-faint">
                              Not a table
                            </span>
                          )}
                        </label>
                      </li>
                    );
                  })}
                  {root.children.length === 0 ? (
                    <li className="px-3 py-4 text-center text-[0.8125rem] text-ink-muted">
                      This spreadsheet has no tabs to read.
                    </li>
                  ) : null}
                </ul>
                <Toggle checked={combine} onChange={setCombine} disabled={saving}>
                  Combine tabs with the same columns into one table
                </Toggle>
              </>
            ) : null}

            {source.origin === "gdrive_file" ? (
              <p className="text-[0.8125rem] leading-relaxed text-ink-muted">
                This file becomes one or more tables once it is read, and is read again whenever it
                changes in Drive.
              </p>
            ) : null}

            <div className="flex items-center gap-2 pt-1">
              <Button
                type="button"
                onClick={add}
                disabled={saving || rules.length === 0}
                className="h-10 bg-brand px-5 text-[0.875rem] font-medium text-brand-fg hover:bg-brand-hover"
              >
                {saving ? (
                  <>
                    <Loader2 aria-hidden className="size-4 animate-spin" />
                    Adding
                  </>
                ) : (
                  "Add"
                )}
              </Button>
              {onCancel ? (
                <Button
                  type="button"
                  variant="ghost"
                  onClick={onCancel}
                  disabled={saving}
                  className="h-10 px-4 text-[0.875rem] text-ink-muted hover:text-ink"
                >
                  Cancel
                </Button>
              ) : null}
            </div>
          </>
        ) : (
          <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
            {connectionId ? null : (
              <div className="flex flex-col gap-1.5">
                <Label
                  htmlFor="google-dataset-name"
                  className={cn("text-[0.8125rem] font-medium", nameError ? "text-fault" : "text-ink")}
                >
                  Dataset name
                </Label>
                <Input
                  id="google-dataset-name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="Dealer sales"
                  maxLength={200}
                  disabled={checking || datasetId !== null}
                  aria-invalid={nameError ? true : undefined}
                  className={cn(
                    "h-10 rounded-md bg-surface text-sm placeholder:text-ink-faint",
                    nameError ? "border-fault" : "border-line",
                  )}
                />
                {nameError ? (
                  <p className="text-[0.8125rem] text-fault">{nameError}</p>
                ) : (
                  <p className="text-[0.8125rem] text-ink-muted">What you will call it when asking.</p>
                )}
              </div>
            )}

            <div className="flex flex-col gap-1.5">
              <Label
                htmlFor="google-link"
                className={cn("text-[0.8125rem] font-medium", urlError ? "text-fault" : "text-ink")}
              >
                Google Drive or Sheets link
              </Label>
              <Input
                id="google-link"
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                placeholder="https://drive.google.com/drive/folders/..."
                maxLength={2000}
                disabled={checking}
                aria-invalid={urlError ? true : undefined}
                className={cn(
                  "h-10 rounded-md bg-surface font-mono text-[0.8125rem] placeholder:text-ink-faint",
                  urlError ? "border-fault" : "border-line",
                )}
              />
              {urlError ? (
                <p className="text-[0.8125rem] text-fault">{urlError}</p>
              ) : (
                <p className="text-[0.8125rem] leading-relaxed text-ink-muted">
                  A folder, a file or a spreadsheet. It is read, never changed.
                </p>
              )}
            </div>

            {link.step === "needs_share" ? (
              <div className="flex flex-col gap-3 rounded-md border border-line bg-surface-sunk px-4 py-3.5">
                <p className="text-[0.8125rem] leading-relaxed text-ink">
                  This app cannot see that link yet. In Google Drive, share it with this address as
                  a Viewer, then check again.
                </p>
                <CodeBlock code={link.shareWith} label="Share with" copyLabel="email" />
                <div>
                  <Button
                    type="button"
                    onClick={() => start({ type: "check", url: link.url })}
                    className="h-8 bg-brand px-3.5 text-[0.8125rem] font-medium text-brand-fg hover:bg-brand-hover"
                  >
                    Check access
                  </Button>
                </div>
              </div>
            ) : null}

            {link.step === "unverified" ? (
              <div className="flex flex-col gap-3 rounded-md border border-warning/30 bg-warning/5 px-4 py-3.5">
                {isOwner ? (
                  <>
                    <p className="text-[0.8125rem] leading-relaxed text-ink">
                      Nobody in your organisation shared this with the app, so it cannot be tied to
                      you. Add it only if you trust where the link came from.
                    </p>
                    <div>
                      <Button
                        type="button"
                        onClick={() => start({ type: "confirm", owner: isOwner })}
                        className="h-8 bg-brand px-3.5 text-[0.8125rem] font-medium text-brand-fg hover:bg-brand-hover"
                      >
                        Add it anyway
                      </Button>
                    </div>
                  </>
                ) : (
                  <p className="text-[0.8125rem] leading-relaxed text-ink">
                    Nobody in your organisation shared this with the app. Ask an owner of your
                    organisation to add this link.
                  </p>
                )}
              </div>
            ) : null}

            <div className="flex items-center gap-2 pt-1">
              <Button
                type="submit"
                disabled={checking}
                className="h-10 bg-brand px-5 text-[0.875rem] font-medium text-brand-fg hover:bg-brand-hover"
              >
                {checking ? (
                  <>
                    <Loader2 aria-hidden className="size-4 animate-spin" />
                    Checking the link
                  </>
                ) : (
                  "Check link"
                )}
              </Button>
              {onCancel ? (
                <Button
                  type="button"
                  variant="ghost"
                  onClick={onCancel}
                  disabled={checking}
                  className="h-10 px-4 text-[0.875rem] text-ink-muted hover:text-ink"
                >
                  Cancel
                </Button>
              ) : null}
            </div>
          </form>
        )}
      </div>
    </Panel>
  );
}
