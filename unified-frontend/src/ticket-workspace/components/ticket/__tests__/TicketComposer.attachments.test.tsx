import { createEvent, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TicketComposer } from "@tw/components/ticket/TicketComposer";
import { fakeDataTransfer, makeFile } from "@tw/lib/__tests__/testUtils";

const pushToast = vi.fn();
const ticket = { ticket_id: "t1", current_status: "OPEN", client_id: "c1", client_name: "Acme" };
let permissions = ["ticket:reply", "communication:reply_internal"];
let activeTicket: Record<string, unknown> = ticket;

vi.mock("@tw/context/ToastContext", () => ({ useToast: () => ({ pushToast }) }));
vi.mock("@tw/context/WorkflowContext", () => ({
  useWorkflowContext: () => ({ activeTicket, timeline: [] }),
}));
vi.mock("@tw/context/AuthContext", () => ({
  useAuthContext: () => ({ currentUser: { user_id: "u1", signature_html: null, permissions } }),
}));
vi.mock("@/services", () => ({ authService: { me: vi.fn().mockResolvedValue({}) } }));
vi.mock("@/store/auth-store", () => ({
  useAuthStore: (selector: (s: unknown) => unknown) => selector({ refreshUser: vi.fn() }),
}));
vi.mock("@tw/api/clients", () => ({ listClientContacts: vi.fn().mockResolvedValue([]) }));
vi.mock("@tw/api/interaction", () => ({
  addInternalNote: vi.fn(),
  discardTicketNoteDraft: vi.fn(),
  discardTicketReplyDraft: vi.fn(),
  getTicketNoteDraft: vi.fn().mockRejectedValue(new Error("404")),
  getTicketReplyDraft: vi.fn().mockRejectedValue(new Error("404")),
  listInternalNoteRecipients: vi.fn().mockResolvedValue([]),
  replyToClient: vi.fn(),
  saveTicketNoteDraft: vi.fn(),
  saveTicketReplyDraft: vi.fn(),
  uploadAttachment: vi.fn(),
  uploadTicketInlineImage: vi.fn(),
}));
vi.mock("@tw/lib/undoSend", () => ({ showUndoSendToast: vi.fn() }));
vi.mock("@tw/components/mail/RichTextEditor", () => ({
  RichTextEditor: () => <div className="ProseMirror" data-testid="editor" />,
  isRichTextEmpty: (html: string) => html.replace(/<[^>]*>/g, "").trim().length === 0,
}));
vi.mock("@tw/components/common/EnvelopePreview", () => ({ EnvelopePreview: () => null }));
vi.mock("@tw/components/common/UserMultiSelect", () => ({ UserMultiSelect: () => null }));
vi.mock("@tw/components/common/MultiRecipientCombobox", () => ({ MultiRecipientCombobox: () => null }));
vi.mock("@tw/components/common/DistributionListMultiSelect", () => ({ DistributionListMultiSelect: () => null }));

function paste(target: Element, files: File[]) {
  const event = createEvent.paste(target, { clipboardData: fakeDataTransfer({ files }) });
  fireEvent(target, event);
  return event;
}
function drop(target: Element, files: File[]) {
  const event = createEvent.drop(target, { dataTransfer: fakeDataTransfer({ files }) });
  fireEvent(target, event);
  return event;
}

beforeEach(() => {
  pushToast.mockClear();
  permissions = ["ticket:reply", "communication:reply_internal"];
  activeTicket = ticket;
});

describe("TicketComposer — Reply tab", () => {
  it("a pasted PDF lands in the Reply attachments list", async () => {
    render(<TicketComposer mode="reply" lockMode onClose={vi.fn()} onSent={vi.fn()} />);
    paste(await screen.findByTestId("editor"), [makeFile("invoice.pdf", "application/pdf")]);
    expect(screen.getByText("invoice.pdf")).toBeInTheDocument();
  });

  it("a dropped file can be removed again, existing Remove button intact", async () => {
    render(<TicketComposer mode="reply" lockMode onClose={vi.fn()} onSent={vi.fn()} />);
    drop(await screen.findByTestId("editor"), [makeFile("a.docx"), makeFile("b.csv")]);
    fireEvent.click(screen.getByRole("button", { name: "Remove a.docx" }));
    expect(screen.queryByText("a.docx")).not.toBeInTheDocument();
    expect(screen.getByText("b.csv")).toBeInTheDocument();
  });

  it("reports an unsupported dropped file via the existing toast", async () => {
    render(<TicketComposer mode="reply" lockMode onClose={vi.fn()} onSent={vi.fn()} />);
    drop(await screen.findByTestId("editor"), [makeFile("bad.exe"), makeFile("ok.pdf")]);
    expect(screen.getByText("ok.pdf")).toBeInTheDocument();
    expect(pushToast).toHaveBeenCalledWith(expect.stringContaining("unsupported file type"), "error");
  });

  it("without reply permission a dropped file is swallowed, not attached", () => {
    permissions = [];
    render(<TicketComposer mode="reply" lockMode onClose={vi.fn()} onSent={vi.fn()} />);
    const event = drop(screen.getByRole("alert"), [makeFile("a.pdf")]);
    expect(screen.queryByText("a.pdf")).not.toBeInTheDocument();
    expect(event.defaultPrevented).toBe(true);
  });
});

describe("TicketComposer — Internal Note tab", () => {
  it("a pasted file opens the attachments panel and its existing 'Upload to ticket' button takes over", async () => {
    render(<TicketComposer mode="note" lockMode onClose={vi.fn()} onSent={vi.fn()} />);
    expect(screen.queryByText(/drag files here/i)).not.toBeInTheDocument();
    paste(await screen.findByTestId("editor"), [makeFile("evidence.pdf", "application/pdf")]);
    await waitFor(() => expect(screen.getByText("evidence.pdf")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /upload to ticket/i })).toBeEnabled();
  });
});

describe("TicketComposer — closed ticket", () => {
  it("shows the lock message and accepts no attachments", async () => {
    activeTicket = { ...ticket, current_status: "CLOSED" };
    render(<TicketComposer mode="reply" lockMode onClose={vi.fn()} onSent={vi.fn()} />);
    expect(screen.getByText(/ticket is closed/i)).toBeInTheDocument();
    expect(screen.queryByTestId("editor")).not.toBeInTheDocument();
  });
});

describe("TicketComposer — hook order", () => {
  it("survives activeTicket going from missing to present (hooks run before the early return)", async () => {
    activeTicket = null as unknown as Record<string, unknown>;
    const { rerender, container } = render(<TicketComposer mode="reply" lockMode onClose={vi.fn()} onSent={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
    activeTicket = ticket;
    rerender(<TicketComposer mode="reply" lockMode onClose={vi.fn()} onSent={vi.fn()} />);
    expect(await screen.findByTestId("editor")).toBeInTheDocument();
  });
});
