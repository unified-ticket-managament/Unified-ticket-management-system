import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ActionRow } from "../ActionRow";

const listMailFolders = vi.fn();
vi.mock("@tw/api/mailFolder", () => ({ listMailFolders: () => listMailFolders() }));
vi.mock("../EmployeeMultiSelect", () => ({ EmployeeMultiSelect: () => <div data-testid="employees" /> }));
vi.mock("@tw/components/common/DistributionListMultiSelect", () => ({
  DistributionListMultiSelect: () => <div data-testid="dls" />,
}));

const FOLDERS = [
  { folder_id: "1", name: "LEFC Inbox", parent_folder_id: null, created_by: null, created_at: "" },
  { folder_id: "2", name: "Billing", parent_folder_id: null, created_by: null, created_at: "" },
];

beforeEach(() => {
  listMailFolders.mockReset();
  listMailFolders.mockResolvedValue(FOLDERS);
});

describe("ActionRow", () => {
  it("renders the folder combobox for move_to_folder, preserving the saved folder", async () => {
    render(
      <ActionRow
        category="mail_rule"
        action={{ type: "move_to_folder", folder_name: "LEFC Inbox" }}
        onChange={vi.fn()}
        onRemove={vi.fn()}
      />
    );
    await waitFor(() => expect(listMailFolders).toHaveBeenCalled());
    expect((screen.getByRole("combobox", { name: "Folder" }) as HTMLInputElement).value).toBe("LEFC Inbox");
  });

  it("propagates a picked folder as folder_name on the action", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <ActionRow
        category="mail_rule"
        action={{ type: "move_to_folder", folder_name: "" }}
        onChange={onChange}
        onRemove={vi.fn()}
      />
    );
    await user.click(screen.getByRole("combobox", { name: "Folder" }));
    await user.click(await screen.findByRole("option", { name: "Billing" }));
    expect(onChange).toHaveBeenLastCalledWith({ type: "move_to_folder", folder_name: "Billing" });
  });

  it("the remove (X) button still removes the action", async () => {
    const onRemove = vi.fn();
    render(
      <ActionRow
        category="mail_rule"
        action={{ type: "move_to_folder", folder_name: "Billing" }}
        onChange={vi.fn()}
        onRemove={onRemove}
      />
    );
    await userEvent.setup().click(screen.getByRole("button", { name: "Remove action" }));
    expect(onRemove).toHaveBeenCalledTimes(1);
  });

  it("create_folder still uses its free-text input with datalist suggestions (unchanged)", async () => {
    render(
      <ActionRow
        category="mail_rule"
        action={{ type: "create_folder", folder_name: "New" }}
        onChange={vi.fn()}
        onRemove={vi.fn()}
      />
    );
    expect(screen.getByPlaceholderText("Folder name…")).toHaveValue("New");
    expect(screen.queryByRole("combobox", { name: "Folder" })).toBeNull();
    await waitFor(() => expect(document.querySelectorAll("#existing-mail-folders option")).toHaveLength(2));
  });

  it("forward_to still renders its recipient pickers (no folder combobox)", () => {
    render(
      <ActionRow
        category="mail_rule"
        action={{ type: "forward_to", employee_user_ids: [], distribution_list_ids: [] }}
        onChange={vi.fn()}
        onRemove={vi.fn()}
      />
    );
    expect(screen.getByTestId("employees")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Folder" })).toBeNull();
    expect(listMailFolders).not.toHaveBeenCalled();
  });
});
