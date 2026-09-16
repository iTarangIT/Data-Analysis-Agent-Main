import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ResultTable } from "./result-table";

afterEach(cleanup);

describe("ResultTable", () => {
  it("shows a jsonb column's values as JSON, never as [object Object]", () => {
    // The rows event for `SELECT info -> 'assignedgroups' FROM vehicles ...` on the IoT database.
    const { container } = render(
      <ResultTable
        result={{
          columns: ["?column?"],
          rows: [
            [[{ groupname: "Triwheels_Fintech_Services" }, { groupname: "The_iTarang_Technologies" }]],
            [[{ groupname: "Ayansh_Engineering" }]],
          ],
          truncated: false,
        }}
      />,
    );

    expect(container.textContent).not.toContain("[object Object]");
    expect(
      screen.getByRole("cell", {
        name: '[{"groupname":"Triwheels_Fintech_Services"},{"groupname":"The_iTarang_Technologies"}]',
      }),
    ).toBeTruthy();
    expect(screen.getByRole("cell", { name: '[{"groupname":"Ayansh_Engineering"}]' })).toBeTruthy();
  });
});
