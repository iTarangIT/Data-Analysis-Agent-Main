import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DatasetFiles } from "./dataset-files";

const refresh = vi.fn();
const removeFile = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/actions/connections", () => ({
  removeFile: (...args: unknown[]) => removeFile(...args),
}));

const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  fetchMock.mockReset();
  refresh.mockReset();
  removeFile.mockReset();
});

const TWO_FILES = [
  { file: "book.xlsx", tables: ["book__sales", "book__returns"] },
  { file: "dealers.csv", tables: ["dealers"] },
];

describe("DatasetFiles", () => {
  it("lists each file with the tables it became", () => {
    render(<DatasetFiles connectionId="c1" files={TWO_FILES} />);

    expect(screen.getByText("book__sales, book__returns")).toBeTruthy();
    expect(screen.getByText("dealers")).toBeTruthy();
  });

  it("removes a file only after it is confirmed", async () => {
    removeFile.mockResolvedValue({});
    render(<DatasetFiles connectionId="c1" files={TWO_FILES} />);

    fireEvent.click(screen.getByRole("button", { name: "Remove dealers.csv" }));
    expect(removeFile).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));

    await waitFor(() => expect(refresh).toHaveBeenCalledOnce());
    expect(removeFile).toHaveBeenCalledWith("c1", "dealers.csv");
  });

  it("will not offer to remove the only file", () => {
    render(<DatasetFiles connectionId="c1" files={TWO_FILES.slice(1)} />);

    const button = screen.getByRole("button", {
      name: "dealers.csv is the only file, so it cannot be removed",
    }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });

  it("uploads added files to this connection and refuses one it already holds", async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ tables: [] }), { status: 200 }));
    const { container } = render(<DatasetFiles connectionId="c1" files={TWO_FILES} />);
    fireEvent.click(screen.getByRole("button", { name: "Add files" }));
    const input = container.querySelector<HTMLInputElement>('input[type="file"]');
    if (!input) throw new Error("no file input");

    fireEvent.change(input, {
      target: { files: [new File(["x"], "dealers.csv"), new File(["x"], "stock.csv")] },
    });
    expect(screen.getByRole("alert").textContent).toContain("dealers.csv is already in this dataset.");
    fireEvent.click(screen.getByRole("button", { name: "Upload" }));

    await waitFor(() => expect(refresh).toHaveBeenCalledOnce());
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/connections/c1/files");
    expect(((init.body as FormData).getAll("files") as File[]).map((file) => file.name)).toEqual([
      "stock.csv",
    ]);
  });
});
