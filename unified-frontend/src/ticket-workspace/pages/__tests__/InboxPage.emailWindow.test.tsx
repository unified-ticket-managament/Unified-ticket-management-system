import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { InboxPage } from "@tw/pages/InboxPage";
import type { OpenEmailResponse } from "@tw/types";

const ORIGINAL_EMAIL_WINDOW_CLASS = "flex h-[85vh] max-h-[85vh] w-full max-w-5xl flex-col gap-0 overflow-hidden p-0";

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

function renderPage() {
  return render(
    <MemoryRouter>
      <InboxPage />
    </MemoryRouter>
  );
}

async function openWindow(user: ReturnType<typeof userEvent.setup>) {
  await user.dblClick(screen.getByRole("button", { name: "email row" }));
  return screen.findByRole("dialog");
}

describe("InboxPage — double-click email window", () => {
  it("opens in the existing window size, in the normal state", async () => {
    const user = userEvent.setup();
    renderPage();
    const dialog = await openWindow(user);
    for (const cls of ORIGINAL_EMAIL_WINDOW_CLASS.split(" ")) expect(dialog).toHaveClass(cls);
    expect(within(dialog).getByRole("button", { name: "Maximize" })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Close" })).toBeInTheDocument();
    expect(within(dialog).getByRole("heading", { name: "Printer is down" })).toBeInTheDocument();
  });

  it("before the window opens, exactly one composer host exists (the panel)", () => {
    renderPage();
    expect(screen.getAllByTestId("reply-composer")).toHaveLength(1);
    expect(screen.getByTestId("message-details")).toHaveAttribute("data-variant", "panel");
  });

  it("while the window is open, only the window owns a composer — the panel behind it has none", async () => {
    const user = userEvent.setup();
    renderPage();
    await openWindow(user);

    const composers = screen.getAllByTestId("reply-composer");
    expect(composers).toHaveLength(1);
    expect(screen.getAllByTestId("message-details")).toHaveLength(1);
    expect(screen.getByTestId("message-details")).toHaveAttribute("data-variant", "fullscreen");
    expect(screen.getByTestId("email-open-in-window-notice")).toBeInTheDocument();
    expect(within(screen.getByTestId("detail-panel")).queryByTestId("reply-composer")).not.toBeInTheDocument();
  });

  it("maximize and restore keep the very same single composer mounted", async () => {
    const user = userEvent.setup();
    renderPage();
    await openWindow(user);
    const composer = screen.getByTestId("reply-composer");

    await user.click(screen.getByRole("button", { name: "Maximize" }));
    expect(screen.getAllByTestId("reply-composer")).toHaveLength(1);
    expect(screen.getByTestId("reply-composer")).toBe(composer);

    await user.click(screen.getByRole("button", { name: "Restore" }));
    expect(screen.getAllByTestId("reply-composer")).toHaveLength(1);
    expect(screen.getByTestId("reply-composer")).toBe(composer);
  });

  it("closing the window hands the composer back to the panel — still exactly one", async () => {
    const user = userEvent.setup();
    renderPage();
    await openWindow(user);
    await user.click(screen.getByRole("button", { name: "Close" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByTestId("email-open-in-window-notice")).not.toBeInTheDocument();
    expect(screen.getAllByTestId("reply-composer")).toHaveLength(1);
    expect(screen.getByTestId("message-details")).toHaveAttribute("data-variant", "panel");
  });

  it("closing while maximized also closes and hands back to the panel", async () => {
    const user = userEvent.setup();
    renderPage();
    await openWindow(user);
    await user.click(screen.getByRole("button", { name: "Maximize" }));
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByTestId("message-details")).toHaveAttribute("data-variant", "panel");
  });
});
