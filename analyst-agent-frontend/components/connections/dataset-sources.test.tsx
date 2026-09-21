import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DatasetSource, DatasetSources as Sources } from "@/lib/api/types";

import { DatasetSources } from "./dataset-sources";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh, push: vi.fn() }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  fetchMock.mockReset();
  refresh.mockReset();
});

const UPLOADS: DatasetSource = {
  id: "up",
  origin: "upload",
  label: "Uploads",
  status: "active",
  combine: false,
  rules: [],
  files: [{ id: "u1", name: "manual.csv", status: "ready", reason: null, tables: ["manual"] }],
};

const FOLDER: DatasetSource = {
  id: "g1",
  origin: "gdrive_folder",
  label: "Sales 2025",
  status: "active",
  combine: true,
  rules: [{ id: "root", kind: "folder", recursive: true }],
  files: [
    { id: "f1", name: "January.xlsx", status: "ready", reason: null, tables: ["sales"] },
    { id: "f2", name: "Scans.xlsx", status: "skipped", reason: "it is over 25 MB", tables: [] },
    { id: "f3", name: "Broken.csv", status: "failed", reason: "could not be read as a spreadsheet", tables: [] },
  ],
};

function sources(over: Partial<Sources> = {}): Sources {
  return {
    sync_status: "ready",
    synced_at: new Date(Date.now() - 5 * 60_000).toISOString(),
    sources: [UPLOADS, FOLDER],
    ...over,
  };
}

function show(initial: Sources) {
  return render(
    <SWRConfig value={{ provider: () => new Map() }}>
      <DatasetSources connectionId="c1" initial={initial} isOwner={false} />
    </SWRConfig>,
  );
}

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status });
}

describe("DatasetSources", () => {
  it("shows each Google file's state, with the reason one was skipped or failed", () => {
    show(sources());

    expect(screen.getByText("Synced 5m ago")).toBeTruthy();
    expect(screen.getByText("Ready").closest("li")?.textContent).toContain("January.xlsx");
    expect(screen.getByText("sales")).toBeTruthy();
    expect(screen.getByText("Skipped").closest("li")?.textContent).toContain("it is over 25 MB");
    expect(screen.getByText("Failed").closest("li")?.textContent).toContain(
      "could not be read as a spreadsheet",
    );
    expect(screen.queryByText("manual.csv")).toBeNull();
    expect(screen.queryByText("Syncing")).toBeNull();
  });

  it("marks each Google source as syncing while a sync runs", () => {
    show(sources({ sync_status: "syncing" }));

    expect(screen.getByText("Syncing")).toBeTruthy();
    expect(screen.getByText("Syncing with Google Drive now")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Refresh" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("queues a sync on Refresh and shows it running", async () => {
    fetchMock.mockResolvedValueOnce(json(202, { status: "queued" }));
    show(sources());

    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));

    expect(await screen.findByText("Syncing")).toBeTruthy();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/connections/c1/sync");
    expect(init.method).toBe("POST");
  });

  it("reloads the page once a running sync has finished", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fetchMock.mockResolvedValue(json(200, sources()));
    show(sources({ sync_status: "syncing" }));

    await vi.advanceTimersByTimeAsync(3000);

    await waitFor(() => expect(refresh).toHaveBeenCalledOnce());
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/connections/c1/sources");
    expect(screen.queryByText("Syncing")).toBeNull();
  });

  it("removes a source only after it is confirmed", async () => {
    fetchMock.mockResolvedValueOnce(json(200, sources({ sources: [UPLOADS] })));
    show(sources());

    fireEvent.click(screen.getByRole("button", { name: "Remove Sales 2025" }));
    expect(fetchMock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));

    await waitFor(() => expect(refresh).toHaveBeenCalledOnce());
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/connections/c1/sources/g1");
    expect(init.method).toBe("DELETE");
    expect(screen.queryByText("Sales 2025")).toBeNull();
  });
});
