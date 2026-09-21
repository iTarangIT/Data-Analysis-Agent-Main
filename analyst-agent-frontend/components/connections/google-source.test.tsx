import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DatasetSource, DriveNode } from "@/lib/api/types";

import { GoogleSource } from "./google-source";

const refresh = vi.fn();
const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh, push }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  fetchMock.mockReset();
  refresh.mockReset();
  push.mockReset();
});

const LINK = "https://drive.google.com/drive/folders/abc";
const EMAIL = "reader@analyst.iam.gserviceaccount.com";

function source(over: Partial<DatasetSource> = {}): DatasetSource {
  return {
    id: "s1",
    origin: "gdrive_file",
    label: "July.xlsx",
    status: "pending",
    combine: true,
    rules: [{ id: "f1", kind: "file", recursive: false }],
    files: [],
    ...over,
  };
}

function node(id: string, name: string, kind: DriveNode["kind"], supported = true): DriveNode {
  return { id, name, kind, supported, bytes: kind === "folder" ? null : 2048 };
}

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status });
}

function sent(index: number): { url: string; body: unknown } {
  const [url, init] = fetchMock.mock.calls[index] as [string, RequestInit | undefined];
  return { url, body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined };
}

function paste(link: string) {
  fireEvent.change(screen.getByLabelText("Google Drive or Sheets link"), {
    target: { value: link },
  });
  fireEvent.click(screen.getByRole("button", { name: "Check link" }));
}

describe("GoogleSource", () => {
  it("wants a name for the new dataset and a link before it checks anything", () => {
    render(<GoogleSource isOwner={false} />);

    fireEvent.click(screen.getByRole("button", { name: "Check link" }));

    expect(screen.getByText("Name this dataset.")).toBeTruthy();
    expect(screen.getByText("Paste a Google Drive or Google Sheets link.")).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("creates the dataset once, asks for the link to be shared, checks it again, then adds it", async () => {
    fetchMock
      .mockResolvedValueOnce(json(201, { id: "c9", name: "July" }))
      .mockResolvedValueOnce(json(200, { status: "needs_share", share_with: EMAIL, source: null }))
      .mockResolvedValueOnce(json(200, { status: "resolved", share_with: null, source: source() }))
      .mockResolvedValueOnce(json(200, source({ status: "active" })));
    render(<GoogleSource isOwner={false} />);
    fireEvent.change(screen.getByLabelText("Dataset name"), { target: { value: " July " } });
    paste(LINK);

    expect(await screen.findByText(EMAIL)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Check access" }));
    fireEvent.click(await screen.findByRole("button", { name: "Add" }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/connections/c9/tables"));
    expect(sent(0)).toEqual({ url: "/api/connections/dataset", body: { name: "July" } });
    expect(sent(1)).toEqual({ url: "/api/connections/c9/google/resolve", body: { url: LINK } });
    expect(sent(2)).toEqual({ url: "/api/connections/c9/google/resolve", body: { url: LINK } });
    expect(sent(3)).toEqual({
      url: "/api/connections/c9/sources",
      body: { source_id: "s1", rules: [{ id: "f1", kind: "file", recursive: false }], combine: true },
    });
    expect(refresh).toHaveBeenCalledOnce();
  });

  it("lets an owner add a link nobody in the organisation shared", async () => {
    fetchMock
      .mockResolvedValueOnce(json(200, { status: "unverified", share_with: null, source: null }))
      .mockResolvedValueOnce(json(200, { status: "resolved", share_with: null, source: source() }));
    render(<GoogleSource connectionId="c1" isOwner />);
    paste(LINK);

    fireEvent.click(await screen.findByRole("button", { name: "Add it anyway" }));

    expect(await screen.findByRole("button", { name: "Add" })).toBeTruthy();
    expect(sent(1)).toEqual({
      url: "/api/connections/c1/google/resolve",
      body: { url: LINK, confirm_unverified: true },
    });
    expect(screen.queryByLabelText("Dataset name")).toBeNull();
  });

  it("asks someone who is not an owner to have an owner add that link", async () => {
    fetchMock.mockResolvedValueOnce(json(200, { status: "unverified", share_with: null, source: null }));
    render(<GoogleSource connectionId="c1" isOwner={false} />);
    paste(LINK);

    expect(await screen.findByText(/Ask an owner of your organisation to add this link\./)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Add it anyway" })).toBeNull();
  });

  it("shows the agent's reason when a link is refused", async () => {
    fetchMock.mockResolvedValueOnce(
      json(400, { error: "paste a Google Drive or Google Sheets link", code: "invalid_request" }),
    );
    render(<GoogleSource connectionId="c1" isOwner={false} />);
    paste("https://example.com/sheet");

    expect((await screen.findByRole("alert")).textContent).toBe(
      "paste a Google Drive or Google Sheets link",
    );
  });

  it("lists a spreadsheet's tabs with the linked one chosen, and adds the tabs chosen", async () => {
    const onDone = vi.fn();
    const sheet = source({
      id: "s2",
      origin: "gsheet",
      label: "Budget",
      rules: [{ id: "0", kind: "sheet", recursive: false }],
    });
    fetchMock
      .mockResolvedValueOnce(json(200, { status: "resolved", share_with: null, source: sheet }))
      .mockResolvedValueOnce(
        json(200, {
          folder_id: "budget",
          children: [node("0", "Jan", "sheet"), node("1", "Feb", "sheet"), node("2", "Chart", "sheet", false)],
          supported: 2,
          unsupported: 1,
          bytes: 0,
        }),
      )
      .mockResolvedValueOnce(json(200, { ...sheet, status: "active" }));
    render(<GoogleSource connectionId="c1" isOwner={false} onDone={onDone} />);
    paste("https://docs.google.com/spreadsheets/d/budget/edit#gid=0");

    const jan = (await screen.findByRole("checkbox", { name: "Jan" })) as HTMLInputElement;
    const feb = screen.getByRole("checkbox", { name: "Feb" }) as HTMLInputElement;
    const chart = screen.getByRole("checkbox", { name: /Chart/ }) as HTMLInputElement;
    expect([jan.checked, feb.checked, chart.disabled]).toEqual([true, false, true]);
    expect(sent(1).url).toBe("/api/connections/c1/google/tree?source_id=s2");

    fireEvent.click(feb);
    fireEvent.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() => expect(onDone).toHaveBeenCalledOnce());
    expect(sent(2)).toEqual({
      url: "/api/connections/c1/sources",
      body: {
        source_id: "s2",
        rules: [
          { id: "0", kind: "sheet", recursive: false },
          { id: "1", kind: "sheet", recursive: false },
        ],
        combine: true,
      },
    });
    expect(push).not.toHaveBeenCalled();
  });

  it("covers what is inside a chosen folder, sizes the choice, and adds it with its subfolders", async () => {
    const onDone = vi.fn();
    const folder = source({ id: "s3", origin: "gdrive_folder", label: "Sales", rules: [] });
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      const body = typeof init?.body === "string" ? JSON.parse(init.body) : null;
      if (url.includes("/google/resolve")) {
        return json(200, { status: "resolved", share_with: null, source: folder });
      }
      if (url.includes("folder_id=sub")) {
        return json(200, {
          folder_id: "sub",
          children: [node("b", "feb.csv", "csv")],
          supported: 1,
          unsupported: 0,
          bytes: 2048,
        });
      }
      if (url.includes("/google/tree")) {
        return json(200, {
          folder_id: "root",
          children: [
            node("sub", "2025", "folder"),
            node("a", "jan.csv", "csv"),
            node("n", "notes.docx", "other", false),
          ],
          supported: 2,
          unsupported: 1,
          bytes: 2048,
        });
      }
      if (body?.dry_run) {
        return json(200, {
          files: 2,
          bytes: 4096,
          skipped: [{ name: "huge.xlsx", reason: "it is over 25 MB" }],
          fits: true,
          limit: 50 * 1024 * 1024,
        });
      }
      return json(200, { ...folder, status: "active" });
    });
    render(<GoogleSource connectionId="c1" isOwner={false} onDone={onDone} />);
    paste(LINK);

    fireEvent.click(await screen.findByRole("checkbox", { name: /^Sales/ }));
    fireEvent.click(screen.getByRole("button", { name: "Open 2025" }));

    const feb = (await screen.findByRole("checkbox", { name: /feb\.csv/ })) as HTMLInputElement;
    const jan = screen.getByRole("checkbox", { name: /jan\.csv/ }) as HTMLInputElement;
    const notes = screen.getByRole("checkbox", { name: /notes\.docx/ }) as HTMLInputElement;
    expect([feb.checked, feb.disabled, jan.checked, jan.disabled]).toEqual([true, true, true, true]);
    expect([notes.checked, notes.disabled]).toEqual([false, true]);

    expect(await screen.findByText(/huge\.xlsx will be skipped/, undefined, { timeout: 2000 })).toBeTruthy();
    expect(screen.getByText("of 50.0 MB")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() => expect(onDone).toHaveBeenCalledOnce());
    const saved = fetchMock.mock.calls.length - 1;
    expect(sent(saved)).toEqual({
      url: "/api/connections/c1/sources",
      body: { source_id: "s3", rules: [{ id: "root", kind: "folder", recursive: true }], combine: true },
    });
  });
});
