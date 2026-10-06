import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MailSidebar } from "@tw/components/mail/MailSidebar";
import type { MailFolder } from "@tw/types";

vi.mock("@tw/context/ToastContext", () => ({ useToast: () => ({ pushToast: vi.fn() }) }));

const f = (id: string, name: string, parent: string | null = null): MailFolder => ({
  folder_id: id,
  name,
  parent_folder_id: parent,
  created_by: null,
  created_at: "",
});

const FOLDERS = [
  f("1", "Clients"),
  f("2", "Active Clients", "1"),
  f("3", "High Priority", "2"),
  f("5", "Projects"),
];

function setup(overrides: Record<string, unknown> = {}) {
  const props = {
    activeView: "pending" as const,
    isComposing: false,
    onSelectView: vi.fn(),
    onCompose: vi.fn(),
    counts: {},
    hideMyClaims: false,
    folders: FOLDERS,
    folderCounts: { "3": 2 },
    activeFolderId: null,
    onSelectFolder: vi.fn(),
    onCreateFolder: vi.fn<(name: string, parent?: string | null) => Promise<MailFolder>>().mockResolvedValue(f("9", "New", "1")),
    onRenameFolder: vi.fn().mockResolvedValue(f("1", "Customers")),
    onMoveFolder: vi.fn().mockResolvedValue(f("2", "Active Clients", null)),
    onDeleteFolder: vi.fn().mockResolvedValue(undefined),
    canManageRules: false,
    rulesActive: false,
    onOpenRules: vi.fn(),
    ...overrides,
  };
  render(<MailSidebar {...props} />);
  return props;
}

describe("MailSidebar folder tree", () => {
  beforeEach(() => localStorage.clear());

  it("renders only root folders until expanded, and collapses again", async () => {
    setup();
    expect(screen.getByText("Clients")).toBeInTheDocument();
    expect(screen.queryByText("Active Clients")).not.toBeInTheDocument();

    await userEvent.click(screen.getByLabelText("Expand Clients"));
    expect(screen.getByText("Active Clients")).toBeInTheDocument();
    expect(screen.queryByText("High Priority")).not.toBeInTheDocument();

    await userEvent.click(screen.getByLabelText("Expand Active Clients"));
    expect(screen.getByText("High Priority")).toBeInTheDocument();

    await userEvent.click(screen.getByLabelText("Collapse Clients"));
    expect(screen.queryByText("Active Clients")).not.toBeInTheDocument();
  });

  it("reveals the path to the active nested folder", () => {
    setup({ activeFolderId: "3" });
    expect(screen.getByText("High Priority")).toBeInTheDocument();
  });

  it("selects a nested folder by id", async () => {
    const props = setup({ activeFolderId: "3" });
    await userEvent.click(screen.getByText("High Priority"));
    expect(props.onSelectFolder).toHaveBeenCalledWith("3");
  });

  it("creates a subfolder under the right-clicked parent", async () => {
    const props = setup();
    fireEvent.contextMenu(screen.getByText("Clients"));
    await userEvent.click(await screen.findByText("Create subfolder"));
    await userEvent.type(screen.getByLabelText("Folder Name"), "Old Clients");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(props.onCreateFolder).toHaveBeenCalledWith("Old Clients", "1"));
  });

  it("creates a root folder with a null parent", async () => {
    const props = setup();
    await userEvent.click(screen.getByLabelText(/create folder|new folder/i));
    await userEvent.type(screen.getByLabelText("Folder Name"), "Personal");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(props.onCreateFolder).toHaveBeenCalledWith("Personal", null));
  });

  it("renames via the context menu", async () => {
    const props = setup();
    fireEvent.contextMenu(screen.getByText("Clients"));
    await userEvent.click(await screen.findByText("Rename"));
    const input = screen.getByLabelText("Folder Name");
    expect(input).toHaveValue("Clients");
    await userEvent.clear(input);
    await userEvent.type(input, "Customers");
    await userEvent.click(screen.getByRole("button", { name: "Rename" }));
    await waitFor(() => expect(props.onRenameFolder).toHaveBeenCalledWith("1", "Customers"));
  });

  it("moves a folder to root, excluding its own subtree from targets", async () => {
    const props = setup({ folders: [...FOLDERS] });
    await userEvent.click(screen.getByLabelText("Expand Clients"));
    fireEvent.contextMenu(screen.getByText("Active Clients"));
    await userEvent.click(await screen.findByText("Move"));
    // Own subtree is not offered as a destination.
    const options = screen.getAllByRole("option").map((o) => o.textContent);
    expect(options).toContain("Projects");
    expect(options).not.toContain("High Priority");
    await userEvent.click(screen.getByText("Root (top level)"));
    await waitFor(() => expect(props.onMoveFolder).toHaveBeenCalledWith("2", null));
  });

  it("shows the empty state", () => {
    setup({ folders: [] });
    expect(screen.getByText(/No folders yet/)).toBeInTheDocument();
  });
});
