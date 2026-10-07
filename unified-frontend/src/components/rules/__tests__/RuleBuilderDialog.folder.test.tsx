import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RuleBuilderDialog } from "../RuleBuilderDialog";
import type { RuleResponse } from "@tw/api/rules";

const createRule = vi.fn();
const updateRule = vi.fn();
const listMailFolders = vi.fn();

vi.mock("@tw/api/rules", () => ({
  createRule: (...a: unknown[]) => createRule(...a),
  updateRule: (...a: unknown[]) => updateRule(...a),
}));
vi.mock("@tw/api/mailFolder", () => ({ listMailFolders: () => listMailFolders() }));
vi.mock("@/hooks/use-toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("../ConditionRow", () => ({ ConditionRow: () => <div data-testid="condition-row" /> }));
vi.mock("../EmployeeMultiSelect", () => ({ EmployeeMultiSelect: () => <div /> }));
vi.mock("@tw/components/common/DistributionListMultiSelect", () => ({
  DistributionListMultiSelect: () => <div />,
}));

const FOLDERS = [
  { folder_id: "1", name: "LEFC Inbox", parent_folder_id: null, created_by: null, created_at: "" },
  { folder_id: "2", name: "LEFC, Cameron, CWH", parent_folder_id: null, created_by: null, created_at: "" },
  { folder_id: "3", name: "Billing", parent_folder_id: null, created_by: null, created_at: "" },
];

function makeRule(actions: RuleResponse["actions"]): RuleResponse {
  return {
    rule_id: "r1",
    name: "Move LEFC mail",
    category: "mail_rule",
    is_enabled: true,
    conditions: {
      combinator: "AND",
      rules: [{ field: "subject", operator: "contains", value: "LEFC" }],
    },
    exceptions: { combinator: "AND", rules: [] },
    actions,
    stop_processing: false,
    priority: 1,
    created_by: "u1",
    shared_user_ids: [],
    shared_distribution_list_ids: [],
    created_at: "",
    updated_at: "",
    can_manage: true,
    active_run: null,
  } as RuleResponse;
}

function renderDialog(rule: RuleResponse | null) {
  const onSaved = vi.fn();
  const onOpenChange = vi.fn();
  render(<RuleBuilderDialog open onOpenChange={onOpenChange} rule={rule} onSaved={onSaved} />);
  return { onSaved, onOpenChange };
}

const saveButton = () => screen.getByRole("button", { name: "Save" });

beforeEach(() => {
  createRule.mockReset().mockResolvedValue({ active_run: null });
  updateRule.mockReset().mockResolvedValue({ active_run: null });
  listMailFolders.mockReset().mockResolvedValue(FOLDERS);
});

describe("RuleBuilderDialog - Move to Folder", () => {
  it("editing preserves the existing folder and saves it unchanged", async () => {
    const user = userEvent.setup();
    const { onSaved } = renderDialog(makeRule([{ type: "move_to_folder", folder_name: "LEFC Inbox" }]));
    expect((screen.getByRole("combobox", { name: "Folder" }) as HTMLInputElement).value).toBe("LEFC Inbox");
    expect(saveButton()).toBeEnabled();

    await user.click(saveButton());
    await waitFor(() => expect(updateRule).toHaveBeenCalledTimes(1));
    expect(updateRule.mock.calls[0][0]).toBe("r1");
    expect(updateRule.mock.calls[0][1].actions).toEqual([
      { type: "move_to_folder", folder_name: "LEFC Inbox" },
    ]);
    expect(onSaved).toHaveBeenCalled();
  });

  it("typing an exact folder name and saving stores that existing folder", async () => {
    const user = userEvent.setup();
    renderDialog(makeRule([{ type: "move_to_folder", folder_name: "LEFC Inbox" }]));
    const input = screen.getByRole("combobox", { name: "Folder" });
    await user.clear(input);
    expect(saveButton()).toBeDisabled();
    await user.type(input, "billing");
    expect(saveButton()).toBeEnabled();

    await user.click(saveButton());
    await waitFor(() => expect(updateRule).toHaveBeenCalled());
    expect(updateRule.mock.calls[0][1].actions).toEqual([{ type: "move_to_folder", folder_name: "Billing" }]);
  });

  it("picking one of two similar folders from the filtered list saves the correct one", async () => {
    const user = userEvent.setup();
    renderDialog(makeRule([{ type: "move_to_folder", folder_name: "Billing" }]));
    const input = screen.getByRole("combobox", { name: "Folder" });
    await user.clear(input);
    await user.type(input, "LEFC");
    await user.click(await screen.findByRole("option", { name: "LEFC, Cameron, CWH" }));
    await user.click(saveButton());
    await waitFor(() => expect(updateRule).toHaveBeenCalled());
    expect(updateRule.mock.calls[0][1].actions).toEqual([
      { type: "move_to_folder", folder_name: "LEFC, Cameron, CWH" },
    ]);
  });

  it("a typed new folder name is saved as-is (the backend creates it on save)", async () => {
    const user = userEvent.setup();
    renderDialog(makeRule([{ type: "move_to_folder", folder_name: "Billing" }]));
    const input = screen.getByRole("combobox", { name: "Folder" });
    await user.clear(input);
    await user.type(input, "taral sharma mails");
    expect(await screen.findByRole("status")).toHaveTextContent("will be created");
    expect(saveButton()).toBeEnabled();
    await user.click(saveButton());
    await waitFor(() => expect(updateRule).toHaveBeenCalled());
    expect(updateRule.mock.calls[0][1].actions).toEqual([
      { type: "move_to_folder", folder_name: "taral sharma mails" },
    ]);
  });

  it("an empty folder still blocks Save", async () => {
    const user = userEvent.setup();
    renderDialog(makeRule([{ type: "move_to_folder", folder_name: "Billing" }]));
    await user.clear(screen.getByRole("combobox", { name: "Folder" }));
    expect(saveButton()).toBeDisabled();
  });

  it("create-folder + move-to-folder with the same new name can be saved together", async () => {
    const user = userEvent.setup();
    renderDialog(
      makeRule([
        { type: "create_folder", folder_name: "taral sharma mails" },
        { type: "move_to_folder", folder_name: "" },
      ])
    );
    await user.type(screen.getByRole("combobox", { name: "Folder" }), "taral sharma mails");
    await user.click(saveButton());
    await waitFor(() => expect(updateRule).toHaveBeenCalled());
    expect(updateRule.mock.calls[0][1].actions).toEqual([
      { type: "create_folder", folder_name: "taral sharma mails" },
      { type: "move_to_folder", folder_name: "taral sharma mails" },
    ]);
  });

  it("the remove (X) button removes the Move to Folder action", async () => {
    const user = userEvent.setup();
    renderDialog(makeRule([{ type: "move_to_folder", folder_name: "Billing" }]));
    await user.click(screen.getByRole("button", { name: "Remove action" }));
    expect(screen.queryByRole("combobox", { name: "Folder" })).toBeNull();
    expect(saveButton()).toBeDisabled(); // a rule needs at least one action
  });

  it("other actions are unaffected: a create_folder rule still saves its free-text name", async () => {
    const user = userEvent.setup();
    renderDialog(makeRule([{ type: "create_folder", folder_name: "Brand New" }]));
    expect(screen.queryByRole("combobox", { name: "Folder" })).toBeNull();
    await user.click(saveButton());
    await waitFor(() => expect(updateRule).toHaveBeenCalled());
    expect(updateRule.mock.calls[0][1].actions).toEqual([{ type: "create_folder", folder_name: "Brand New" }]);
  });
});
