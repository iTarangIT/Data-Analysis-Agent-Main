"use client";

import { AlertTriangle, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { toast } from "sonner";

import { FileDrop } from "@/components/connections/file-drop";
import { Eyebrow, Panel } from "@/components/panel";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { stemOf, upload } from "@/features/connections/uploads";
import type { Connection } from "@/lib/api/types";
import { cn } from "@/lib/utils";

export function DatasetForm({ onCancel }: { onCancel?: () => void }) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [nameError, setNameError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [sending, startSending] = useTransition();

  function choose(next: File[]) {
    setFiles(next);
    setFormError(null);
    if (!name && next[0]) setName(stemOf(next[0].name));
  }

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = name.trim();
    setNameError(trimmed ? null : "Name this dataset.");
    setFormError(files.length ? null : "Choose at least one file.");
    if (!trimmed || !files.length) return;

    const form = new FormData();
    form.set("name", trimmed);
    for (const file of files) form.append("files", file);

    startSending(async () => {
      let connection: Connection;
      try {
        connection = await upload<Connection>("/api/connections/file", form);
      } catch (error) {
        setFormError((error as Error).message);
        return;
      }
      toast.success(
        `${connection.name} added with ${connection.total_tables} ${connection.total_tables === 1 ? "table" : "tables"}`,
      );
      setName("");
      setFiles([]);
      router.refresh();
      onCancel?.();
    });
  }

  return (
    <Panel className="p-5">
      <Eyebrow>Spreadsheet dataset</Eyebrow>

      <form onSubmit={submit} className="mt-4 flex flex-col gap-4" noValidate>
        {formError ? (
          <p
            role="alert"
            className="flex items-start gap-2.5 rounded-md border border-fault/30 bg-fault-soft px-3 py-2.5 text-[0.8125rem] text-fault"
          >
            <AlertTriangle aria-hidden className="mt-px size-4 shrink-0" strokeWidth={2} />
            <span>{formError}</span>
          </p>
        ) : null}

        <div className="flex flex-col gap-1.5">
          <Label
            htmlFor="dataset-name"
            className={cn("text-[0.8125rem] font-medium", nameError ? "text-fault" : "text-ink")}
          >
            Dataset name
          </Label>
          <Input
            id="dataset-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="July dealer sales"
            maxLength={200}
            disabled={sending}
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

        <div className="flex flex-col gap-1.5">
          <p className="text-[0.8125rem] font-medium text-ink">Files</p>
          <FileDrop files={files} onChange={choose} disabled={sending} />
          <p className="text-[0.8125rem] leading-relaxed text-ink-muted">
            Every file, and every sheet of a workbook, becomes a table. Title rows above the header,
            empty columns and Grand Total rows are left out. You can add or remove files later.
          </p>
        </div>

        <div className="flex items-center gap-2 pt-1">
          <Button
            type="submit"
            disabled={sending}
            className="h-10 bg-brand px-5 text-[0.875rem] font-medium text-brand-fg hover:bg-brand-hover"
          >
            {sending ? (
              <>
                <Loader2 aria-hidden className="size-4 animate-spin" />
                Reading {files.length} {files.length === 1 ? "file" : "files"}
              </>
            ) : (
              "Add dataset"
            )}
          </Button>
          {onCancel ? (
            <Button
              type="button"
              variant="ghost"
              onClick={onCancel}
              disabled={sending}
              className="h-10 px-4 text-[0.875rem] text-ink-muted hover:text-ink"
            >
              Cancel
            </Button>
          ) : null}
        </div>
      </form>
    </Panel>
  );
}
