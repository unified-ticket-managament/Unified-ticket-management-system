import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  AdditionalAssignmentRows,
  type AdditionalAssignmentRow,
} from "@tw/components/mail/AdditionalAssignmentRows";
import type { AssignableAgentsResponse } from "@tw/types";

const listAssignableAgents = vi.fn();
vi.mock("@tw/api/agent", () => ({ listAssignableAgents: (c?: string) => listAssignableAgents(c) }));

const u = (id: string, name: string) => ({ user_id: id, name, employee_number: null, is_on_leave: false });

const BY_CATEGORY: Record<string, AssignableAgentsResponse> = {
  AR: { me: u("tl", "Team Lead One"), groups: [{ role: "Staff", users: [u("a", "Staff A"), u("b", "Staff B")] }] },
  Denials: { me: u("tl", "Team Lead One"), groups: [{ role: "Staff", users: [u("d", "Staff D")] }] },
  Empty: { me: u("tl", "Team Lead One"), groups: [{ role: "Staff", users: [] }] },
};

const CATEGORIES = ["AR", "Denials", "Empty"].map((n, i) => ({
  category_id: `c${i}`,
  category_name: n,
  inbox_email: null,
}));

function Harness({ initial }: { initial: AdditionalAssignmentRow[] }) {
  const [rows, setRows] = useState(initial);
  return (
    <>
      <AdditionalAssignmentRows categories={CATEGORIES as never} rows={rows} onChange={setRows} defaultCategory="AR" />
      <output data-testid="rows">{JSON.stringify(rows.map((r) => [r.category_name, r.user_id]))}</output>
    </>
  );
}

const rowsState = () => JSON.parse(screen.getByTestId("rows").textContent ?? "[]");

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
  Element.prototype.scrollIntoView = () => {};
  listAssignableAgents.mockReset().mockImplementation(async (c: string) => BY_CATEGORY[c]);
});

async function optionsOf(user: ReturnType<typeof userEvent.setup>, label: RegExp) {
  await user.click(screen.getByRole("combobox", { name: label }));
  const names = (await screen.findAllByRole("option")).map((o) => o.textContent);
  await user.keyboard("{Escape}");
  return names;
}

describe("AdditionalAssignmentRows", () => {
  it("loads each row's people with that row's own category and lists only that scoped set", async () => {
    const user = userEvent.setup();
    render(<Harness initial={[{ key: "r1", category_name: "AR", user_id: "" }]} />);
    await waitFor(() => expect(listAssignableAgents).toHaveBeenCalledWith("AR"));
    await waitFor(() => expect(screen.getByRole("combobox", { name: /Person for additional assignee 1/ })).not.toBeDisabled());
    const names = await optionsOf(user, /Person for additional assignee 1/);
    expect(names.join("|")).toContain("Staff A");
    expect(names.join("|")).toContain("Staff B");
    expect(names.join("|")).not.toContain("Staff D");
  });

  it("changing the row's category refreshes the options and clears the previous person", async () => {
    const user = userEvent.setup();
    render(<Harness initial={[{ key: "r1", category_name: "AR", user_id: "a" }]} />);
    await waitFor(() => expect(listAssignableAgents).toHaveBeenCalledWith("AR"));

    await user.click(screen.getByRole("combobox", { name: /Category for additional assignee 1/ }));
    await user.click(await screen.findByRole("option", { name: "Denials" }));

    expect(rowsState()).toEqual([["Denials", ""]]); // AR assignee dropped
    await waitFor(() => expect(listAssignableAgents).toHaveBeenCalledWith("Denials"));
    await waitFor(() => expect(screen.getByRole("combobox", { name: /Person for additional assignee 1/ })).not.toBeDisabled());
    const names = (await optionsOf(user, /Person for additional assignee 1/)).join("|");
    expect(names).toContain("Staff D");
    expect(names).not.toContain("Staff A");
  });

  it("a category with no Staff offers only the caller (no stale options from another category)", async () => {
    const user = userEvent.setup();
    render(<Harness initial={[{ key: "r1", category_name: "Empty", user_id: "" }]} />);
    await waitFor(() => expect(listAssignableAgents).toHaveBeenCalledWith("Empty"));
    await waitFor(() => expect(screen.getByRole("combobox", { name: /Person for additional assignee 1/ })).not.toBeDisabled());
    const names = (await optionsOf(user, /Person for additional assignee 1/)).join("|");
    expect(names).toContain("Team Lead One");
    expect(names).not.toContain("Staff");
  });

  it("shows a load error for a failed category instead of stale people", async () => {
    listAssignableAgents.mockRejectedValue(new Error("boom"));
    render(<Harness initial={[{ key: "r1", category_name: "AR", user_id: "" }]} />);
    expect(await screen.findByText("Couldn't load people")).toBeInTheDocument();
  });
});
