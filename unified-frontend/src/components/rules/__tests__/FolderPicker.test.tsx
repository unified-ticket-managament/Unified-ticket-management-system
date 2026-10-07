import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FolderPicker } from "../FolderPicker";
import type { MailFolder } from "@tw/types";

const listMailFolders = vi.fn();
vi.mock("@tw/api/mailFolder", () => ({ listMailFolders: () => listMailFolders() }));

const folder = (id: string, name: string, parent: string | null = null): MailFolder => ({
  folder_id: id,
  name,
  parent_folder_id: parent,
  created_by: null,
  created_at: "2026-01-01T00:00:00Z",
});

const FOLDERS = [
  folder("1", "LEFC Inbox"),
  folder("2", "LEFC, Cameron, CWH"),
  folder("3", "Billing"),
  folder("4", "LEFC"),
  folder("5", "Archive", "3"),
];

function Harness({ initial = "", spy }: { initial?: string; spy: (v: string) => void }) {
  const [value, setValue] = useState(initial);
  return (
    <FolderPicker
      value={value}
      onChange={(v) => {
        spy(v);
        setValue(v);
      }}
    />
  );
}

async function setup(initial = "", folders: MailFolder[] = FOLDERS) {
  listMailFolders.mockResolvedValue(folders);
  const spy = vi.fn();
  const user = userEvent.setup();
  render(<Harness initial={initial} spy={spy} />);
  await waitFor(() => expect(listMailFolders).toHaveBeenCalled());
  return { spy, user, input: screen.getByRole("combobox") as HTMLInputElement };
}

const optionNames = () => screen.queryAllByRole("option").map((o) => o.textContent);

beforeEach(() => {
  listMailFolders.mockReset();
});

describe("FolderPicker", () => {
  it("renders a combobox and still lists every folder when opened via the toggle (existing dropdown)", async () => {
    const { user } = await setup();
    await user.click(screen.getByRole("button", { name: "Toggle folder list" }));
    await waitFor(() => expect(optionNames()).toHaveLength(FOLDERS.length));
    expect(optionNames()).toContain("LEFC Inbox");
    expect(optionNames()).toContain("Billing / Archive"); // hierarchy path preserved
  });

  it("selects a folder by clicking it, reporting its name and closing the list", async () => {
    const { user, spy, input } = await setup();
    await user.click(input);
    await user.click(await screen.findByRole("option", { name: "Billing" }));
    expect(spy).toHaveBeenLastCalledWith("Billing");
    expect(input.value).toBe("Billing");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("typing filters the folder list", async () => {
    const { user, input } = await setup();
    await user.type(input, "lefc");
    await waitFor(() =>
      expect(optionNames().sort()).toEqual(["LEFC", "LEFC Inbox", "LEFC, Cameron, CWH"].sort())
    );
  });

  it("a partial match is not mistaken for an existing folder - it is a NEW name, flagged as such", async () => {
    const { user, spy, input } = await setup();
    await user.type(input, "LEFC I");
    expect(spy).not.toHaveBeenCalledWith("LEFC Inbox");
    expect(spy).toHaveBeenLastCalledWith("LEFC I");
    expect(await screen.findByRole("status")).toHaveTextContent("New folder “LEFC I” will be created");
  });

  it("typing an exact existing name resolves to that folder (case-insensitive), not a prefix sibling", async () => {
    const { user, spy, input } = await setup();
    await user.type(input, "lefc");
    // "LEFC" is both an exact folder and a prefix of two others.
    expect(spy).toHaveBeenLastCalledWith("LEFC");
    await user.type(input, " inbox");
    expect(spy).toHaveBeenLastCalledWith("LEFC Inbox");
  });

  it("selects the right one of two similar names from the filtered list", async () => {
    const { user, spy, input } = await setup();
    await user.type(input, "LEFC,");
    await user.click(await screen.findByRole("option", { name: "LEFC, Cameron, CWH" }));
    expect(spy).toHaveBeenLastCalledWith("LEFC, Cameron, CWH");
  });

  it("a new folder name can be typed and is reported as the value, with a 'will be created' note", async () => {
    const { user, spy, input } = await setup();
    await user.type(input, "taral sharma mails");
    await user.tab();
    expect(spy).toHaveBeenLastCalledWith("taral sharma mails");
    expect(await screen.findByRole("status")).toHaveTextContent(
      "New folder “taral sharma mails” will be created when this rule is saved."
    );
    expect(input).not.toHaveAttribute("aria-invalid");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("an existing folder (any casing) is NOT shown as new and resolves to its real name", async () => {
    const { user, spy, input } = await setup();
    await user.type(input, "BILLING");
    await user.tab();
    expect(spy).toHaveBeenLastCalledWith("Billing");
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("surrounding whitespace is trimmed from a new name", async () => {
    const { user, spy, input } = await setup();
    await user.type(input, "  Fresh Folder  ");
    expect(spy).toHaveBeenLastCalledWith("Fresh Folder");
  });

  it("editing a previously chosen folder into a different name reports the new name", async () => {
    const { user, spy, input } = await setup("Billing");
    expect(input.value).toBe("Billing");
    await user.type(input, "x");
    expect(spy).toHaveBeenLastCalledWith("Billingx");
  });

  it("shows the existing value untouched when editing (no spurious onChange)", async () => {
    const { spy, input } = await setup("LEFC Inbox");
    expect(input.value).toBe("LEFC Inbox");
    expect(spy).not.toHaveBeenCalled();
  });

  it("clearing the field reports an empty value and shows no error", async () => {
    const { user, spy, input } = await setup("Billing");
    await user.clear(input);
    expect(spy).toHaveBeenLastCalledWith("");
    await user.tab();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("supports keyboard: ArrowDown/ArrowUp to move, Enter to select, Escape to close", async () => {
    const { user, spy, input } = await setup();
    await user.type(input, "lefc ");
    const names = optionNames();
    expect(names).toHaveLength(3);

    await user.keyboard("{ArrowDown}{ArrowDown}");
    expect(document.getElementById(input.getAttribute("aria-activedescendant")!)).toHaveTextContent(
      names[1]!
    );
    await user.keyboard("{ArrowUp}{ArrowUp}"); // wraps around to the last option
    expect(document.getElementById(input.getAttribute("aria-activedescendant")!)).toHaveTextContent(
      names[2]!
    );
    await user.keyboard("{Enter}");
    expect(spy).toHaveBeenLastCalledWith(names[2]);
    expect(input).toHaveAttribute("aria-expanded", "false");

    await user.click(input);
    expect(input).toHaveAttribute("aria-expanded", "true");
    await user.keyboard("{Escape}");
    expect(input).toHaveAttribute("aria-expanded", "false");
  });

  it("Enter in the field does not submit an enclosing form", async () => {
    listMailFolders.mockResolvedValue(FOLDERS);
    const onSubmit = vi.fn((e) => e.preventDefault());
    const user = userEvent.setup();
    render(
      <form onSubmit={onSubmit}>
        <FolderPicker value="" onChange={() => {}} />
      </form>
    );
    await waitFor(() => expect(listMailFolders).toHaveBeenCalled());
    await user.type(screen.getByRole("combobox"), "Billing{Enter}");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("shows the empty state when no folders exist", async () => {
    listMailFolders.mockResolvedValue([]);
    render(<FolderPicker value="" onChange={() => {}} />);
    await userEvent.setup().click(screen.getByRole("combobox"));
    expect(await screen.findByText("No folders exist yet.")).toBeInTheDocument();
  });

  it("shows a load-error state when folders fail to load", async () => {
    listMailFolders.mockImplementation(async () => {
      throw new Error("boom");
    });
    render(<FolderPicker value="" onChange={() => {}} />);
    await userEvent.setup().click(screen.getByRole("combobox"));
    expect(await screen.findByText("Couldn't load folders. Please try again.")).toBeInTheDocument();
  });
});
