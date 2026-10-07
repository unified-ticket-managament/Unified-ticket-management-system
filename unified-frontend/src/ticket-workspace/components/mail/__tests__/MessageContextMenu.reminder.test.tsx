import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ContextMenu, ContextMenuTrigger } from "@/components/ui/context-menu";
import { MessageContextMenuContent } from "@tw/components/mail/MessageContextMenu";
import type { InboxItem } from "@tw/types";

// The right-click menu's "Remind me" entry (R-038). The reminder context is
// mocked here (not the real provider): opening the provider's Dialog from a
// Radix *context menu* makes jsdom's two focus traps fight forever, which is a
// test-environment artefact — the dialog itself is covered via the row ⋮
// menu and toolbar in MailReminders.ui.test.tsx.

const reminderCtx = vi.hoisted(() => ({
  current: null as null | {
    reminderFor: ReturnType<typeof vi.fn>;
    remind: ReturnType<typeof vi.fn>;
    edit: ReturnType<typeof vi.fn>;
  },
}));
vi.mock("@tw/components/mail/MailReminderContext", () => ({
  useMailReminder: () => reminderCtx.current,
}));
vi.mock("@tw/components/mail/MailBulkContext", () => ({
  useMailBulk: () => ({
    isTrash: false,
    perms: {},
    selectedIds: new Set(),
    markMessage: vi.fn(),
    runBulk: vi.fn(),
    clear: vi.fn(),
  }),
}));

const item = (over: Record<string, unknown> = {}) =>
  ({ interaction_id: "i1", ticket_id: null, status: "PENDING", folder_id: null, ...over }) as unknown as InboxItem;

function renderMenu(over: Record<string, unknown> = {}) {
  render(
    <MemoryRouter>
      <ContextMenu>
        <ContextMenuTrigger>
          <div>row</div>
        </ContextMenuTrigger>
        <MessageContextMenuContent
          item={item(over)}
          isUnread={false}
          folders={[]}
          selectedRows={[]}
          onMessageAction={vi.fn()}
          onMarkRead={vi.fn()}
          onMarkUnread={vi.fn()}
          onAssignFolder={vi.fn().mockResolvedValue(true)}
        />
      </ContextMenu>
    </MemoryRouter>
  );
  fireEvent.contextMenu(screen.getByText("row"));
}

beforeEach(() => {
  reminderCtx.current = {
    reminderFor: vi.fn().mockReturnValue(undefined),
    remind: vi.fn(),
    edit: vi.fn(),
  };
});

describe("right-click menu — Remind me", () => {
  it("is offered, alongside the existing actions, and starts a new reminder for the row", async () => {
    renderMenu();

    const entry = await screen.findByRole("menuitem", { name: /Remind me/ });
    expect(screen.getByRole("menuitem", { name: /Mark as unread/ })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /Flag/ })).toBeInTheDocument();

    fireEvent.click(entry);

    expect(reminderCtx.current!.remind).toHaveBeenCalledWith("i1");
  });

  it("uses the thread id for Sent/Draft rows", async () => {
    renderMenu({ interaction_id: "sent-row", open_interaction_id: "thread-root" });

    fireEvent.click(await screen.findByRole("menuitem", { name: /Remind me/ }));

    expect(reminderCtx.current!.remind).toHaveBeenCalledWith("thread-root");
  });

  it("becomes 'Edit reminder' when one is already active", async () => {
    const active = { reminder_id: "r1", interaction_id: "i1", status: "ACTIVE" };
    reminderCtx.current!.reminderFor.mockReturnValue(active);
    renderMenu();

    fireEvent.click(await screen.findByRole("menuitem", { name: /Edit reminder/ }));

    expect(reminderCtx.current!.edit).toHaveBeenCalledWith(active);
    expect(reminderCtx.current!.remind).not.toHaveBeenCalled();
  });

  it("is absent when there is no reminder provider; the rest of the menu is unchanged", async () => {
    reminderCtx.current = null;
    renderMenu();

    await screen.findByRole("menuitem", { name: /Mark as unread/ });
    expect(screen.queryByRole("menuitem", { name: /Remind me/ })).toBeNull();
    expect(screen.getByRole("menuitem", { name: /Pin/ })).toBeInTheDocument();
  });
});

describe("existing right-click behaviour is untouched", () => {
  it("still renders Reply-less menus without crashing when the user has no reply permission", async () => {
    renderMenu();
    await screen.findByRole("menu");
    expect(screen.queryByRole("menuitem", { name: /^Reply$/ })).toBeNull(); // perms = {} → hidden, as before
  });
});
