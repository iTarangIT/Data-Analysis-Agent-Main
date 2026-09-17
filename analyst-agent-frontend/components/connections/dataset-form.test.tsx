import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DatasetForm } from "./dataset-form";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
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
});

function choose(container: HTMLElement, ...names: string[]) {
  const input = container.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("no file input");
  fireEvent.change(input, { target: { files: names.map((name) => new File(["a,b\n1,2\n"], name)) } });
}

function reply(status: number, body: unknown) {
  fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(body), { status }));
}

describe("DatasetForm", () => {
  it("names the dataset after the first file chosen", () => {
    const { container } = render(<DatasetForm />);

    choose(container, "July dealers.xlsx", "stock.csv");

    expect((screen.getByLabelText("Dataset name") as HTMLInputElement).value).toBe("July dealers");
    expect(screen.getByText("July dealers.xlsx")).toBeTruthy();
    expect(screen.getByText("stock.csv")).toBeTruthy();
  });

  it("does not send without a file", () => {
    render(<DatasetForm />);
    fireEvent.change(screen.getByLabelText("Dataset name"), { target: { value: "July" } });

    fireEvent.click(screen.getByRole("button", { name: "Add dataset" }));

    expect(screen.getByRole("alert").textContent).toBe("Choose at least one file.");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("leaves out a file it cannot read, and says so", () => {
    const { container } = render(<DatasetForm />);

    choose(container, "sales.csv", "notes.pdf");

    expect(screen.queryByText("notes.pdf")).toBeNull();
    expect(screen.getByRole("alert").textContent).toContain("notes.pdf is not a CSV");
  });

  it("uploads every chosen file with the name, then refreshes and closes", async () => {
    const onCancel = vi.fn();
    reply(201, { id: "c1", name: "July dealers", total_tables: 2 });
    const { container } = render(<DatasetForm onCancel={onCancel} />);
    choose(container, "July dealers.xlsx", "stock.csv");

    fireEvent.click(screen.getByRole("button", { name: "Add dataset" }));

    await waitFor(() => expect(onCancel).toHaveBeenCalledOnce());
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const sent = init.body as FormData;
    expect(url).toBe("/api/connections/file");
    expect(sent.get("name")).toBe("July dealers");
    expect((sent.getAll("files") as File[]).map((file) => file.name)).toEqual([
      "July dealers.xlsx",
      "stock.csv",
    ]);
    expect(refresh).toHaveBeenCalledOnce();
  });

  it("shows the agent's reason when the upload is refused, and keeps the files", async () => {
    reply(400, { error: "stock.csv could not be read as a spreadsheet", code: "invalid_request" });
    const { container } = render(<DatasetForm />);
    choose(container, "stock.csv");

    fireEvent.click(screen.getByRole("button", { name: "Add dataset" }));

    expect(await screen.findByText("stock.csv could not be read as a spreadsheet")).toBeTruthy();
    expect(screen.getByText("stock.csv")).toBeTruthy();
    expect(refresh).not.toHaveBeenCalled();
  });
});
