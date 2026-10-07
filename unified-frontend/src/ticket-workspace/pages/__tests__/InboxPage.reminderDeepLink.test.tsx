import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { InboxPage } from "@tw/pages/InboxPage";
import type { OpenEmailResponse } from "@tw/types";

// Clicking a due-reminder notification lands on /inbox?interaction_id=<id>
// (R-006 R-045). InboxPage's EXISTING deep-link effect opens that thread —
// this pins that contract for reminder links, and that mounting the reminder
// provider inside the page doesn't change what opens or when.

const reminderApi = vi.hoisted(() => ({
  getReminders: vi.fn().mockResolvedValue([]),
  createReminder: vi.fn(),
  updateReminder: vi.fn(),
  cancelReminder: vi.fn(),
  snoozeReminder: vi.fn(),
  dismissReminder: vi.fn(),
}));
vi.mock("@tw/api/mailReminders", () => reminderApi);

const email = { interaction_id: "i1", subject: "Printer is down", ticket_id: null } as unknown as OpenEmailResponse;
const openThread = vi.fn().mockResolvedValue(undefined);

// Stub of the mail hook: just enough surface for InboxPage to render.
vi.mock("@tw/hooks/useMailInbox", () => ({
  useMailInbox: () => ({
    activeView: "pending",
    activeFolderId: null,
    viewCounts: {},
    filteredItems: [],
    categories: [],
    clients: [],
    folders: [],
    visibleFolders: [],
    folderCounts: {},
    folderRows: [],
    folderRowsTotal: 0,
    folderRowsHasMore: false,
    systemNotifications: [],
    selectedSystemNotification: null,
    openedIds: new Set(),
    openingId: null,
    openThread,
    refresh: vi.fn(),
    refreshFolders: vi.fn(),
  }),
}));
vi.mock("@tw/hooks/useIsDesktopViewport", () => ({ useIsDesktopViewport: () => true }));
vi.mock("@tw/context/WorkflowContext", () => ({
  useWorkflowContext: () => ({ selectedEmail: email, setSelectedEmail: vi.fn(), categories: [], allCategories: [], allCategoriesLoading: false, allCategoriesError: false }),
}));
vi.mock("@tw/context/AuthContext", () => ({ useAuthContext: () => ({ currentUser: null }) }));
vi.mock("@tw/context/ToastContext", () => ({ useToast: () => ({ pushToast: vi.fn() }) }));
vi.mock("@tw/api/inbox", () => ({ getComposeDraft: vi.fn() }));
vi.mock("@/components/shared/stats", () => ({ AccessDenied: () => null }));
vi.mock("@/components/rules/RulesPanel", () => ({ RulesPanel: () => null }));
vi.mock("@tw/components/layout/AppLayout", () => ({ AppLayout: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
vi.mock("@tw/components/mail/MailSidebar", () => ({ MailSidebar: () => null }));
vi.mock("@tw/components/mail/ComposeView", () => ({ ComposeView: () => null }));
vi.mock("@tw/components/mail/SystemMailList", () => ({ SystemMailList: () => null }));
vi.mock("@tw/components/mail/SystemMailDetailsView", () => ({ SystemMailDetailsView: () => null }));
vi.mock("@tw/components/mail/MailReadingPaneEmptyState", () => ({ MailReadingPaneEmptyState: () => null }));
vi.mock("@tw/components/mail/MailWorkspaceLayout", () => ({
  MailWorkspaceLayout: ({ listPanel, detailPanel }: { listPanel: React.ReactNode; detailPanel: React.ReactNode }) => (
    <div>
      <div data-testid="list-panel">{listPanel}</div>
      <div data-testid="detail-panel">{detailPanel}</div>
    </div>
  ),
}));
vi.mock("@tw/components/mail/MessageList", () => ({
  MessageList: ({ onOpenFullScreen }: { onOpenFullScreen?: (id: string) => void }) => (
    <button onDoubleClick={() => onOpenFullScreen?.("i1")}>email row</button>
  ),
}));
// One stand-in per MessageDetailsView instance, each owning one stand-in
// composer — so counting composers counts independent draft writers.
vi.mock("@tw/components/mail/MessageDetailsView", () => ({
  MessageDetailsView: ({ variant }: { variant: string }) => (
    <div data-testid="message-details" data-variant={variant}>
      <div data-testid="reply-composer" />
    </div>
  ),
}));


const ID = "3f2b8c1e-0000-4000-8000-00000000abcd";

function renderAt(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <InboxPage />
    </MemoryRouter>
  );
}

beforeEach(() => {
  openThread.mockClear();
  reminderApi.getReminders.mockClear();
});

describe("InboxPage — reminder notification deep link", () => {
  it("opens the email named by ?interaction_id", async () => {
    renderAt(`/inbox?interaction_id=${ID}`);

    await waitFor(() => expect(openThread).toHaveBeenCalled());
    expect(openThread.mock.calls[0][0]).toBe(ID);
  });

  it("opens exactly once (the param is consumed, so re-renders don't reopen it)", async () => {
    const { rerender } = renderAt(`/inbox?interaction_id=${ID}`);
    await waitFor(() => expect(openThread).toHaveBeenCalledTimes(1));

    rerender(
      <MemoryRouter initialEntries={[`/inbox?interaction_id=${ID}`]}>
        <InboxPage />
      </MemoryRouter>
    );

    expect(openThread).toHaveBeenCalledTimes(1);
  });

  it("opens nothing without the param", async () => {
    renderAt("/inbox");

    await waitFor(() => expect(reminderApi.getReminders).toHaveBeenCalled());
    expect(openThread).not.toHaveBeenCalled();
  });

  it("the page loads the user's reminders once at mount and opens no reminder dialog by itself", async () => {
    renderAt("/inbox");

    await waitFor(() => expect(reminderApi.getReminders).toHaveBeenCalledTimes(2)); // ACTIVE + FIRED
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
