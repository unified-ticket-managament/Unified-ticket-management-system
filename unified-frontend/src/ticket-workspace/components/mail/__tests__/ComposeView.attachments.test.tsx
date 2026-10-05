import { createEvent, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ComposeView, type ComposeInitialValues } from "@tw/components/mail/ComposeView";
import { MAX_ATTACHMENT_FILES } from "@tw/lib/attachmentMeta";
import { fakeDataTransfer, makeFile } from "@tw/lib/__tests__/testUtils";

const pushToast = vi.fn();
vi.mock("@tw/context/ToastContext", () => ({ useToast: () => ({ pushToast }) }));
vi.mock("@/hooks/use-email-signatures", () => ({ useEmailSignatures: () => ({ data: undefined }) }));
vi.mock("@tw/context/AuthContext", () => ({
  useAuthContext: () => ({
    currentUser: {
      user_id: "u1",
      role: "Site Lead",
      signature_html: null,
      permissions: ["communication:create", "communication:reply_external"],
    },
  }),
}));
vi.mock("@tw/components/mail/RichTextEditor", () => ({
  RichTextEditor: () => <div className="ProseMirror" data-testid="editor" />,
  isRichTextEmpty: (html: string) => html.replace(/<[^>]*>/g, "").trim().length === 0,
}));
vi.mock("@tw/components/common/DistributionListMultiSelect", () => ({ DistributionListMultiSelect: () => null }));
vi.mock("@tw/components/common/MultiRecipientCombobox", () => ({ MultiRecipientCombobox: () => null }));
vi.mock("@tw/api/inbox", () => ({
  createComposeDraft: vi.fn(),
  discardComposeDraft: vi.fn(),
  saveComposeDraft: vi.fn(),
  uploadComposeInlineImage: vi.fn(),
}));
vi.mock("@tw/api/interaction", () => ({ listInternalNoteRecipients: vi.fn().mockResolvedValue([]) }));
vi.mock("@tw/api/clients", () => ({ listClientContacts: vi.fn().mockResolvedValue([]) }));

const client = {
  client_id: "c1",
  name: "Acme Clinic",
  company_name: "Acme",
  is_active: true,
  inbox_email: "acme@example.com",
  account_manager_id: "u1",
} as unknown as Parameters<typeof ComposeView>[0]["clients"][number];

function renderCompose(initialValues?: ComposeInitialValues) {
  return render(
    <ComposeView
      variant="panel"
      clients={[client]}
      categories={[]}
      clientsLoading={false}
      clientsError={false}
      initialValues={initialValues}
      isSending={false}
      onSend={vi.fn()}
      onForwardSend={vi.fn()}
      onDiscard={vi.fn()}
      onBack={vi.fn()}
    />
  );
}

function paste(target: Element, files: File[]) {
  fireEvent(target, createEvent.paste(target, { clipboardData: fakeDataTransfer({ files }) }));
}
function drop(target: Element, files: File[]) {
  fireEvent(target, createEvent.drop(target, { dataTransfer: fakeDataTransfer({ files }) }));
}

beforeEach(() => pushToast.mockClear());

describe("ComposeView attachment intake (Compose)", () => {
  it("a pasted PDF becomes an attachment chip", () => {
    renderCompose();
    paste(screen.getByTestId("editor"), [makeFile("invoice.pdf", "application/pdf")]);
    expect(screen.getByText("invoice.pdf")).toBeInTheDocument();
  });

  it("a dropped DOCX and XLSX both become chips, removable independently", () => {
    renderCompose();
    drop(screen.getByTestId("editor"), [makeFile("a.docx"), makeFile("b.xlsx")]);
    expect(screen.getByText("a.docx")).toBeInTheDocument();
    expect(screen.getByText("b.xlsx")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Remove a.docx" }));
    expect(screen.queryByText("a.docx")).not.toBeInTheDocument();
    expect(screen.getByText("b.xlsx")).toBeInTheDocument();
  });

  it("rejects an unsupported file through the existing toast, keeping valid ones", () => {
    renderCompose();
    drop(screen.getByTestId("editor"), [makeFile("bad.exe"), makeFile("ok.csv")]);
    expect(screen.getByText("ok.csv")).toBeInTheDocument();
    expect(pushToast).toHaveBeenCalledWith(expect.stringContaining("unsupported file type"), "error");
  });
});

describe("ComposeView attachment intake (Forward keeps its reduced cap)", () => {
  const forward: ComposeInitialValues = {
    mode: "forward",
    interactionId: "i1",
    clientId: "c1",
    subject: "Fwd: Hello",
    bodyHtml: "<p>fwd</p>",
    originalAttachmentCount: MAX_ATTACHMENT_FILES - 2,
    originalAttachments: [],
  };

  it("accepts only as many dropped files as slots remain after the original attachments", () => {
    renderCompose(forward);
    drop(screen.getByTestId("editor"), [makeFile("a.pdf"), makeFile("b.pdf"), makeFile("c.pdf")]);
    expect(screen.getByText("a.pdf")).toBeInTheDocument();
    expect(screen.getByText("b.pdf")).toBeInTheDocument();
    expect(screen.queryByText("c.pdf")).not.toBeInTheDocument();
    expect(pushToast).toHaveBeenCalledWith(expect.stringContaining("Only 2 files"), "error");
  });
});
