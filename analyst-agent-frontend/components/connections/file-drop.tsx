"use client";

import { AlertTriangle, FileSpreadsheet, Upload, X } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  MAX_UPLOAD_FILES,
  UPLOAD_SUFFIXES,
  formatBytes,
  pick,
} from "@/features/connections/uploads";
import { cn } from "@/lib/utils";

export function FileDrop({
  files,
  onChange,
  inDataset = [],
  disabled = false,
}: {
  files: File[];
  onChange: (files: File[]) => void;
  inDataset?: readonly string[];
  disabled?: boolean;
}) {
  const [over, setOver] = useState(false);
  const [problems, setProblems] = useState<string[]>([]);

  function add(incoming: FileList | null) {
    if (!incoming || disabled) return;
    const picked = pick(files, [...incoming], inDataset);
    setProblems(picked.problems);
    onChange(picked.files);
  }

  return (
    <div className="flex flex-col gap-3">
      <label
        onDragOver={(event) => {
          event.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(event) => {
          event.preventDefault();
          setOver(false);
          add(event.dataTransfer.files);
        }}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border border-dashed px-5 py-7 text-center transition-colors focus-within:border-brand",
          over ? "border-brand bg-brand-soft/40" : "border-line-strong hover:border-brand hover:bg-brand-soft/40",
          disabled && "pointer-events-none opacity-60",
        )}
      >
        <input
          type="file"
          multiple
          accept={UPLOAD_SUFFIXES.join(",")}
          disabled={disabled}
          onChange={(event) => {
            add(event.target.files);
            event.target.value = "";
          }}
          className="sr-only"
        />
        <span className="flex size-9 items-center justify-center rounded-full border border-line-strong text-ink-muted">
          <Upload aria-hidden className="size-4" strokeWidth={2} />
        </span>
        <span className="text-[0.875rem] font-medium text-ink">Drop files here, or choose them</span>
        <span className="text-[0.75rem] text-ink-muted">
          CSV, TSV, Excel, Parquet or PDF. Up to {MAX_UPLOAD_FILES} files, 25 MB each.
        </span>
      </label>

      {problems.length > 0 ? (
        <ul
          role="alert"
          className="flex flex-col gap-1 rounded-md border border-warning/30 bg-warning/5 px-3 py-2.5"
        >
          {problems.map((problem) => (
            <li key={problem} className="flex items-start gap-2 text-[0.75rem] leading-relaxed text-ink">
              <AlertTriangle aria-hidden className="mt-0.5 size-3.5 shrink-0 text-warning" strokeWidth={2} />
              {problem}
            </li>
          ))}
        </ul>
      ) : null}

      {files.length > 0 ? (
        <ul className="flex flex-col divide-y divide-line rounded-md border border-line">
          {files.map((file) => (
            <li key={file.name} className="flex min-w-0 items-center gap-3 px-3 py-2">
              <FileSpreadsheet aria-hidden className="size-4 shrink-0 text-ink-muted" strokeWidth={1.75} />
              <span className="min-w-0 flex-1 truncate text-[0.8125rem] text-ink">{file.name}</span>
              <span className="shrink-0 font-mono text-[0.75rem] text-ink-muted tabular-nums">
                {formatBytes(file.size)}
              </span>
              <Button
                type="button"
                variant="ghost"
                disabled={disabled}
                onClick={() => onChange(files.filter((kept) => kept !== file))}
                aria-label={`Leave out ${file.name}`}
                className="h-7 px-1.5 text-ink-muted hover:text-fault"
              >
                <X className="size-3.5" strokeWidth={2} />
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
