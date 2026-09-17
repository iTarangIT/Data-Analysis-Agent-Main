"use client";

import { AlertTriangle, FileSpreadsheet, Loader2, Plus, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { toast } from "sonner";

import { removeFile } from "@/actions/connections";
import { FileDrop } from "@/components/connections/file-drop";
import { Eyebrow, Panel } from "@/components/panel";
import { Button } from "@/components/ui/button";
import { type DatasetFile, upload } from "@/features/connections/uploads";
import type { ConnectionTables } from "@/lib/api/types";

export function DatasetFiles({
  connectionId,
  files,
}: {
  connectionId: string;
  files: DatasetFile[];
}) {
  const router = useRouter();
  const [adding, setAdding] = useState(false);
  const [chosen, setChosen] = useState<File[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [uploading, startUpload] = useTransition();
  const [removing, startRemove] = useTransition();
  const busy = uploading || removing;
  const lastFile = files.length === 1;

  function send() {
    const form = new FormData();
    for (const file of chosen) form.append("files", file);
    startUpload(async () => {
      try {
        await upload<ConnectionTables>(
          `/api/connections/${encodeURIComponent(connectionId)}/files`,
          form,
        );
      } catch (failure) {
        setError((failure as Error).message);
        return;
      }
      toast.success(
        `Added ${chosen.length} ${chosen.length === 1 ? "file" : "files"}. Their tables are listed below, not yet chosen.`,
      );
      setChosen([]);
      setAdding(false);
      router.refresh();
    });
  }

  function remove(file: string) {
    startRemove(async () => {
      const result = await removeFile(connectionId, file);
      setConfirming(null);
      if (result.message) {
        toast.error(result.message);
        return;
      }
      toast.success(`Removed ${file} and its tables`);
      router.refresh();
    });
  }

  function cancel() {
    setAdding(false);
    setChosen([]);
    setError(null);
  }

  return (
    <Panel className="mb-6 flex min-w-0 flex-col">
      <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
        <div>
          <Eyebrow>Files</Eyebrow>
          <p className="mt-1 text-[0.8125rem] text-ink-muted">
            <span className="font-mono text-ink tabular-nums">{files.length}</span>{" "}
            {files.length === 1 ? "file" : "files"} in this dataset
          </p>
        </div>
        {!adding ? (
          <Button
            variant="ghost"
            onClick={() => setAdding(true)}
            disabled={busy}
            className="h-8 px-2.5 text-[0.8125rem] text-ink-muted hover:bg-surface-sunk hover:text-ink"
          >
            <Plus aria-hidden className="size-3.5" strokeWidth={2} />
            Add files
          </Button>
        ) : null}
      </div>

      <ul className="flex flex-col divide-y divide-line">
        {files.map(({ file, tables }) => (
          <li key={file} className="flex min-w-0 items-center gap-3 px-5 py-3">
            <FileSpreadsheet aria-hidden className="size-4 shrink-0 text-ink-muted" strokeWidth={1.75} />
            <div className="min-w-0 flex-1">
              <p className="truncate text-[0.875rem] text-ink">{file}</p>
              <p className="truncate font-mono text-[0.75rem] text-ink-muted">{tables.join(", ")}</p>
            </div>
            {confirming === file ? (
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
                  onClick={() => remove(file)}
                  disabled={busy}
                  className="h-8 bg-fault px-3 text-[0.8125rem] text-white hover:bg-fault/90"
                >
                  {removing ? "Removing" : "Remove"}
                </Button>
              </span>
            ) : (
              <Button
                variant="ghost"
                onClick={() => setConfirming(file)}
                disabled={busy || lastFile}
                aria-label={lastFile ? `${file} is the only file, so it cannot be removed` : `Remove ${file}`}
                title={lastFile ? "A dataset needs at least one file. Remove the connection instead." : undefined}
                className="h-8 shrink-0 px-2 text-ink-muted hover:text-fault"
              >
                <Trash2 className="size-4" strokeWidth={1.75} />
              </Button>
            )}
          </li>
        ))}
      </ul>

      {adding ? (
        <div className="flex flex-col gap-3 border-t border-line px-5 py-4">
          {error ? (
            <p
              role="alert"
              className="flex items-start gap-2.5 rounded-md border border-fault/30 bg-fault-soft px-3 py-2.5 text-[0.8125rem] text-fault"
            >
              <AlertTriangle aria-hidden className="mt-px size-4 shrink-0" strokeWidth={2} />
              <span>{error}</span>
            </p>
          ) : null}
          <FileDrop
            files={chosen}
            onChange={(next) => {
              setChosen(next);
              setError(null);
            }}
            inDataset={files.map((entry) => entry.file)}
            disabled={uploading}
          />
          <div className="flex items-center justify-end gap-2">
            <Button
              variant="ghost"
              onClick={cancel}
              disabled={uploading}
              className="h-8 px-3 text-[0.8125rem]"
            >
              Cancel
            </Button>
            <Button
              onClick={send}
              disabled={busy || chosen.length === 0}
              className="h-8 bg-brand px-3.5 text-[0.8125rem] font-medium text-brand-fg hover:bg-brand-hover"
            >
              {uploading ? (
                <>
                  <Loader2 aria-hidden className="size-3.5 animate-spin" />
                  Reading {chosen.length} {chosen.length === 1 ? "file" : "files"}
                </>
              ) : (
                "Upload"
              )}
            </Button>
          </div>
        </div>
      ) : null}
    </Panel>
  );
}
