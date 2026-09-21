"use client";

import { FileSpreadsheet, Folder, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useTransition } from "react";
import { toast } from "sonner";
import useSWR from "swr";

import { GoogleSource } from "@/components/connections/google-source";
import { Eyebrow, Panel } from "@/components/panel";
import { Button } from "@/components/ui/button";
import { ORIGINS, fetchJson } from "@/features/connections/google";
import type { DatasetSource, DatasetSources as Sources, SourceFile } from "@/lib/api/types";
import { when } from "@/lib/time";
import { cn } from "@/lib/utils";

const POLL_MS = 3000;

const CHIP =
  "shrink-0 rounded-full px-2 py-0.5 text-[0.625rem] font-semibold tracking-[0.06em] uppercase";

const STATUS: Record<SourceFile["status"], { label: string; tone: string }> = {
  ready: { label: "Ready", tone: "bg-success/10 text-success" },
  skipped: { label: "Skipped", tone: "bg-warning/10 text-warning" },
  failed: { label: "Failed", tone: "bg-fault-soft text-fault" },
};

function syncLine(sources: Sources): string {
  if (sources.sync_status === "syncing") return "Syncing with Google Drive now";
  if (sources.sync_status === "failed") return "The last sync failed. Refresh to try again.";
  return sources.synced_at ? `Synced ${when(sources.synced_at)}` : "Not synced yet";
}

export function DatasetSources({
  connectionId,
  initial,
  isOwner,
}: {
  connectionId: string;
  initial: Sources;
  isOwner: boolean;
}) {
  const router = useRouter();
  const base = `/api/connections/${encodeURIComponent(connectionId)}`;
  const { data: current = initial, mutate } = useSWR(
    `${base}/sources`,
    (url: string) => fetchJson<Sources>(url),
    {
      fallbackData: initial,
      revalidateOnMount: false,
      refreshInterval: (latest) =>
        (latest ?? initial).sync_status === "syncing" ? POLL_MS : 0,
    },
  );
  const [adding, setAdding] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [queueing, startQueue] = useTransition();
  const [removing, startRemove] = useTransition();
  const busy = queueing || removing;
  const syncing = current.sync_status === "syncing";
  const wasSyncing = useRef(syncing);
  const google = current.sources.filter((source) => source.origin !== "upload");

  useEffect(() => {
    if (wasSyncing.current && !syncing) router.refresh();
    wasSyncing.current = syncing;
  }, [syncing, router]);

  function sync() {
    startQueue(async () => {
      try {
        await fetchJson<unknown>(`${base}/sync`, { method: "POST" });
      } catch (failure) {
        toast.error((failure as Error).message);
        return;
      }
      await mutate({ ...current, sync_status: "syncing" }, { revalidate: false });
    });
  }

  function remove(source: DatasetSource) {
    startRemove(async () => {
      let next: Sources;
      try {
        next = await fetchJson<Sources>(`${base}/sources/${encodeURIComponent(source.id)}`, {
          method: "DELETE",
        });
      } catch (failure) {
        setConfirming(null);
        toast.error((failure as Error).message);
        return;
      }
      setConfirming(null);
      await mutate(next, { revalidate: false });
      toast.success(`Removed ${source.label} and its tables`);
      router.refresh();
    });
  }

  function added(source: DatasetSource) {
    setAdding(false);
    void mutate(
      {
        ...current,
        sync_status: "syncing",
        sources: [...current.sources.filter((kept) => kept.id !== source.id), source],
      },
      { revalidate: false },
    );
  }

  return (
    <section className="mb-6 flex flex-col gap-3">
      <Panel className="flex min-w-0 flex-col">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-4">
          <div>
            <Eyebrow>Google Drive and Sheets</Eyebrow>
            <p
              className={cn(
                "mt-1 text-[0.8125rem]",
                current.sync_status === "failed" && google.length > 0 ? "text-fault" : "text-ink-muted",
              )}
            >
              {google.length > 0 ? syncLine(current) : "Nothing from Google Drive yet."}
            </p>
          </div>
          <div className="flex items-center gap-1">
            {google.length > 0 ? (
              <Button
                variant="ghost"
                onClick={sync}
                disabled={busy || syncing}
                className="h-8 px-2.5 text-[0.8125rem] text-ink-muted hover:bg-surface-sunk hover:text-ink"
              >
                <RefreshCw
                  aria-hidden
                  className={cn("size-3.5", syncing && "animate-spin")}
                  strokeWidth={2}
                />
                Refresh
              </Button>
            ) : null}
            {!adding ? (
              <Button
                variant="ghost"
                onClick={() => setAdding(true)}
                disabled={busy}
                className="h-8 px-2.5 text-[0.8125rem] text-ink-muted hover:bg-surface-sunk hover:text-ink"
              >
                <Plus aria-hidden className="size-3.5" strokeWidth={2} />
                Add from Google Drive
              </Button>
            ) : null}
          </div>
        </div>

        {google.length === 0 ? (
          <p className="px-5 py-4 text-[0.8125rem] leading-relaxed text-ink-muted">
            Add a shared folder, file or spreadsheet, and its files are read again whenever they
            change in Drive.
          </p>
        ) : (
          <ul className="flex flex-col divide-y divide-line">
            {google.map((source) => (
              <li key={source.id} className="flex min-w-0 flex-col gap-2 px-5 py-3">
                <div className="flex min-w-0 items-center gap-3">
                  {source.origin === "gdrive_folder" ? (
                    <Folder aria-hidden className="size-4 shrink-0 text-ink-muted" strokeWidth={1.75} />
                  ) : (
                    <FileSpreadsheet
                      aria-hidden
                      className="size-4 shrink-0 text-ink-muted"
                      strokeWidth={1.75}
                    />
                  )}
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[0.875rem] text-ink">{source.label}</p>
                    <p className="text-[0.75rem] text-ink-muted">
                      {ORIGINS[source.origin]}, {source.files.length}{" "}
                      {source.files.length === 1 ? "file" : "files"}
                    </p>
                  </div>
                  {source.status === "pending" ? (
                    <span className={cn(CHIP, "bg-surface-sunk text-ink-muted")}>Not added</span>
                  ) : syncing ? (
                    <span className={cn(CHIP, "bg-brand-soft text-brand")}>Syncing</span>
                  ) : null}
                  {confirming === source.id ? (
                    <span className="flex shrink-0 items-center gap-2">
                      <span className="text-[0.8125rem] text-ink-muted">Remove it and its tables?</span>
                      <Button
                        variant="ghost"
                        onClick={() => setConfirming(null)}
                        className="h-8 px-2 text-[0.8125rem]"
                      >
                        Keep
                      </Button>
                      <Button
                        onClick={() => remove(source)}
                        disabled={busy}
                        className="h-8 bg-fault px-3 text-[0.8125rem] text-white hover:bg-fault/90"
                      >
                        {removing ? "Removing" : "Remove"}
                      </Button>
                    </span>
                  ) : (
                    <Button
                      variant="ghost"
                      onClick={() => setConfirming(source.id)}
                      disabled={busy}
                      aria-label={`Remove ${source.label}`}
                      className="h-8 shrink-0 px-2 text-ink-muted hover:text-fault"
                    >
                      <Trash2 className="size-4" strokeWidth={1.75} />
                    </Button>
                  )}
                </div>

                {source.files.length > 0 ? (
                  <ul className="ml-7 flex max-h-80 flex-col gap-2 overflow-y-auto">
                    {source.files.map((file) => (
                      <li key={file.id} className="flex min-w-0 items-start gap-3">
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-[0.8125rem] text-ink">{file.name}</p>
                          {file.reason ? (
                            <p
                              className={cn(
                                "text-[0.75rem]",
                                file.status === "failed" ? "text-fault" : "text-ink-muted",
                              )}
                            >
                              {file.reason}
                            </p>
                          ) : file.tables.length > 0 ? (
                            <p className="truncate font-mono text-[0.75rem] text-ink-muted">
                              {file.tables.join(", ")}
                            </p>
                          ) : null}
                        </div>
                        <span
                          title={file.reason ?? undefined}
                          className={cn(CHIP, STATUS[file.status].tone)}
                        >
                          {STATUS[file.status].label}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Panel>

      {adding ? (
        <GoogleSource
          connectionId={connectionId}
          isOwner={isOwner}
          onCancel={() => setAdding(false)}
          onDone={added}
        />
      ) : null}
    </section>
  );
}
