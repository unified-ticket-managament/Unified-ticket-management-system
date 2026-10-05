import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ComposeView, type ComposeInitialValues } from "@tw/components/mail/ComposeView";
import { buildForwardHtml } from "@tw/lib/richText";
import type { EmailSignatureList } from "@/types";

// New Email and Forward with multiple saved signatures — same rules as
// Reply (see ReplyComposer.signature.test.tsx), plus Forward's placement:
// the signature sits above the "Forwarded message" banner.

let mockSignatures: EmailSignatureList | undefined;
vi.mock("@/hooks/use-email-signatures", () => ({
  useEmailSignatures: () => ({ data: mockSignatures }),
}));
vi.mock("@tw/context/ToastContext", () => ({ useToast: () => ({ pushToast: vi.fn() }) }));
vi.mock("@tw/context/AuthContext", () => ({
  useAuthContext: () => ({
    currentUser: {
      user_id: "u1",
      role: "Site Lead",
      permissions: ["communication:create", "communication:reply_external"],
    },
  }),
}));
vi.mock("@tw/components/mail/RichTextEditor", () => ({
  RichTextEditor: ({ value }: { value: string }) => <output data-testid="body">{value}</output>,
  isRichTextEmpty: (html: string) => html.replace(/<[^>]*>/g, "").trim().length === 0,
}));
vi.mock("@tw/components/mail/SignatureSelector", () => ({
  SignatureSelector: ({
    options,
    selectedId,
    onSelect,
  }: {
    options: Array<{ id: string; name: string }>;
    selectedId: string | null;
    onSelect: (id: string | null) => void;
  }) => (
    <div>
      <span data-testid="selected">{selectedId ?? "none"}</span>
      {options.map((o) => (
        <button key={o.id} type="button" onClick={() => onSelect(o.id)}>
          pick {o.name}
        </button>
      ))}
    </div>
  ),
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

const body = () => screen.getByTestId("body").textContent ?? "";
const selected = () => screen.getByTestId("selected").textContent;

beforeEach(() => {
  mockSignatures = {
    signatures: [
      {
        signature_id: "s1",
        name: "Probe Practice",
        html: "<p>Regards, Probe</p>",
        is_default: true,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
      {
        signature_id: "s2",
        name: "Carolina Psychiatry",
        html: "<p>Regards, Carolina</p>",
        is_default: false,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
    ],
    default_signature_id: "s1",
    fallback_signature_html: null,
    image_urls: {},
  };
});

describe("New Email", () => {
  it("starts with the default signature", () => {
    renderCompose();
    expect(selected()).toBe("s1");
    expect(body()).toContain("Regards, Probe");
  });

  it("a reopened compose draft keeps its own signature", () => {
    renderCompose({
      draftInteractionId: "d1",
      bodyHtml: '<p>Hi</p><div data-utms-signature="s2"><p>Regards, Carolina</p></div>',
    });
    expect(selected()).toBe("s2");
    expect(body()).not.toContain("Regards, Probe");
  });
});

describe("Forward", () => {
  const forwardValues = (): ComposeInitialValues => ({
    mode: "forward",
    clientId: "c1",
    toEmail: "",
    subject: "Fwd: Claim",
    bodyHtml: buildForwardHtml({
      fromLabel: "John",
      dateLabel: "Mon",
      subject: "Claim",
      body: "Original message",
    }),
    interactionId: "i1",
    originalAttachmentCount: 0,
    originalAttachments: [],
  });

  it("puts the default signature above the forwarded message", () => {
    renderCompose(forwardValues());
    expect(selected()).toBe("s1");
    const html = body();
    expect(html.indexOf("Regards, Probe")).toBeGreaterThan(-1);
    expect(html.indexOf("Regards, Probe")).toBeLessThan(html.indexOf("Forwarded message"));
    expect(html).toContain("Original message");
  });

  it("switching keeps the forwarded content and the placement", () => {
    renderCompose(forwardValues());
    fireEvent.click(screen.getByRole("button", { name: /pick Carolina Psychiatry/ }));
    const html = body();
    expect(selected()).toBe("s2");
    expect(html).not.toContain("Regards, Probe");
    expect(html.indexOf("Regards, Carolina")).toBeLessThan(html.indexOf("Forwarded message"));
    expect(html).toContain("Original message");
  });
});
