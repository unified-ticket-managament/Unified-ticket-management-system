import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ReplyComposer } from "@tw/components/mail/ReplyComposer";
import type { EmailSignatureList } from "@/types";

// Reply / Reply All with multiple saved signatures: the default is
// inserted automatically, the selector swaps only this email's
// signature block, and nothing in the composer ever changes the
// permanent default.

const services = vi.hoisted(() => ({
  signatureService: { setDefault: vi.fn(), update: vi.fn(), list: vi.fn() },
}));
vi.mock("@/services", () => services);

let mockSignatures: EmailSignatureList | undefined;
vi.mock("@/hooks/use-email-signatures", () => ({
  useEmailSignatures: () => ({ data: mockSignatures }),
}));
vi.mock("@tw/context/ToastContext", () => ({ useToast: () => ({ pushToast: vi.fn() }) }));
vi.mock("@tw/components/common/DistributionListMultiSelect", () => ({
  DistributionListMultiSelect: () => null,
}));
// Exposes the composer's body and lets the test "type" above the
// signature, the way a user would.
vi.mock("@tw/components/mail/RichTextEditor", () => ({
  RichTextEditor: ({ value, onChange }: { value: string; onChange: (html: string) => void }) => (
    <div>
      <output data-testid="body">{value}</output>
      <textarea
        aria-label="body"
        onChange={(e) => onChange(`<p>${e.target.value}</p>${value.replace(/^<p><\/p>/, "")}`)}
      />
    </div>
  ),
  isRichTextEmpty: (html: string) => html.replace(/<[^>]*>/g, "").trim().length === 0,
}));
vi.mock("@tw/components/mail/SignatureSelector", () => ({
  SignatureSelector: ({
    options,
    selectedId,
    onSelect,
  }: {
    options: Array<{ id: string; name: string; isDefault: boolean }>;
    selectedId: string | null;
    onSelect: (id: string | null) => void;
  }) => (
    <div>
      <span data-testid="selected">{selectedId ?? "none"}</span>
      {options.map((o) => (
        <button key={o.id} type="button" onClick={() => onSelect(o.id)}>
          pick {o.name}
          {o.isDefault ? " (default)" : ""}
        </button>
      ))}
      <button type="button" onClick={() => onSelect(null)}>
        pick none
      </button>
    </div>
  ),
}));

const PROBE_IMG = "sigimg-" + "a".repeat(32);
const PARTNER_IMG = "sigimg-" + "b".repeat(32);

function list(defaultId = "s1"): EmailSignatureList {
  const mk = (id: string, name: string, html: string) => ({
    signature_id: id,
    name,
    html,
    is_default: id === defaultId,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  });
  return {
    signatures: [
      mk("s1", "Probe Practice", `<p>Regards, Probe</p><p><img src="cid:${PROBE_IMG}"></p>`),
      mk("s2", "Partner Company", `<p>Regards, Partner</p><p><img src="cid:${PARTNER_IMG}"></p>`),
      mk("s3", "Plain", "<p>Thanks, Plain</p>"),
    ],
    default_signature_id: defaultId,
    fallback_signature_html: null,
    image_urls: {
      [PROBE_IMG]: "https://storage.test/probe.png",
      [PARTNER_IMG]: "https://storage.test/partner.png",
    },
  };
}

function setup(overrides: Partial<React.ComponentProps<typeof ReplyComposer>> = {}) {
  const props = {
    mode: "reply" as const,
    toEmail: "client@example.com",
    contacts: [],
    subject: "Claim",
    isSending: false,
    isTicketed: true,
    draftAttachments: [],
    onCancel: vi.fn(),
    onSend: vi.fn(),
    onSaveDraft: vi.fn().mockResolvedValue(true),
    onSendDraft: vi.fn().mockResolvedValue(undefined),
    onDiscardDraft: vi.fn().mockResolvedValue(undefined),
    onUploadDraftAttachment: vi.fn().mockResolvedValue(undefined),
    onRemoveDraftAttachment: vi.fn(),
    ...overrides,
  };
  const utils = render(<ReplyComposer {...props} />);
  return { props, ...utils };
}

const body = () => screen.getByTestId("body").textContent ?? "";
const selected = () => screen.getByTestId("selected").textContent;
const type = (text: string) => fireEvent.change(screen.getByLabelText("body"), { target: { value: text } });

beforeEach(() => {
  mockSignatures = list();
  vi.clearAllMocks();
});
afterEach(() => vi.useRealTimers());

describe.each(["reply", "replyAll"] as const)("%s", (mode) => {
  it("starts with the default signature", () => {
    setup({ mode });
    expect(selected()).toBe("s1");
    expect(body()).toContain("Regards, Probe");
    expect(body()).toContain("https://storage.test/probe.png");
  });
});

describe("changing the signature for one email", () => {
  it("replaces the signature block instead of appending, keeping the typed text", () => {
    setup();
    type("Please find the details below.");
    fireEvent.click(screen.getByRole("button", { name: /pick Partner Company/ }));

    expect(selected()).toBe("s2");
    expect(body()).toContain("Please find the details below.");
    expect(body()).toContain("Regards, Partner");
    expect(body()).not.toContain("Regards, Probe");
    expect((body().match(/data-utms-signature=/g) ?? []).length).toBe(1);
  });

  it("never touches the permanent default, and the next new reply still uses it", () => {
    const first = setup();
    fireEvent.click(screen.getByRole("button", { name: /pick Plain/ }));
    expect(selected()).toBe("s3");
    expect(services.signatureService.setDefault).not.toHaveBeenCalled();
    expect(services.signatureService.update).not.toHaveBeenCalled();
    first.unmount();

    setup();
    expect(selected()).toBe("s1");
  });

  it("a default changed in Settings is what the next new composer uses", () => {
    mockSignatures = list("s2");
    setup();
    expect(selected()).toBe("s2");
    expect(body()).toContain("Regards, Partner");
  });

  it("No signature removes it; the selected signature is what gets sent (as cid:)", () => {
    const { props } = setup();
    type("Hello John");
    fireEvent.click(screen.getByRole("button", { name: /pick Partner Company/ }));
    fireEvent.click(screen.getByRole("button", { name: "Send Reply" }));

    const payload = vi.mocked(props.onSend).mock.calls[0][0];
    expect(payload.bodyHtml).toContain("Regards, Partner");
    expect(payload.bodyHtml).toContain(`src="cid:${PARTNER_IMG}"`);
    expect(payload.bodyHtml).not.toContain("storage.test");
    expect(payload.bodyHtml).not.toContain("Regards, Probe");
  });

  it("an untouched signature-only body still counts as empty, even after switching", () => {
    setup();
    const send = screen.getByRole("button", { name: "Send Reply" });
    expect(send).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /pick Plain/ }));
    expect(send).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "pick none" }));
    expect(selected()).toBe("none");
    expect(send).toBeDisabled();
  });
});

describe("drafts", () => {
  it("a reopened draft keeps the signature it was saved with, not the default", () => {
    const draftHtml =
      `<p>Draft text</p><div data-utms-signature="s2"><p>Regards, Partner</p>` +
      `<p><img src="cid:${PARTNER_IMG}" data-local-id="sig-${PARTNER_IMG}" data-content-id="${PARTNER_IMG}"></p></div>`;
    setup({ hasExistingDraft: true, initialBodyHtml: draftHtml, isTicketed: false });

    expect(selected()).toBe("s2");
    expect(body()).not.toContain("Regards, Probe");
    expect(body()).toContain("https://storage.test/partner.png");
  });

  it("a draft saved without a signature gets no default injected", () => {
    setup({ hasExistingDraft: true, initialBodyHtml: "<p>Just text</p>", isTicketed: false });
    expect(selected()).toBe("none");
    expect(body()).toBe("<p>Just text</p>");
  });

  it("the selected signature is what the auto-saved draft stores", async () => {
    vi.useFakeTimers();
    const { props } = setup({ isTicketed: false });
    type("Draft body");
    fireEvent.click(screen.getByRole("button", { name: /pick Plain/ }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1300);
    });
    const bodyHtml = vi.mocked(props.onSaveDraft).mock.calls.at(-1)?.[3] ?? "";
    expect(bodyHtml).toContain('data-utms-signature="s3"');
    expect(bodyHtml).toContain("Thanks, Plain");
  });
});

describe("no saved signatures", () => {
  it("uses the legacy fallback signature so the composer isn't suddenly empty", () => {
    mockSignatures = {
      signatures: [],
      default_signature_id: null,
      fallback_signature_html: "<div>Regards,<br>Kamal</div>",
      image_urls: {},
    };
    setup();
    expect(body()).toContain("Kamal");
  });

  it("starts empty when there is no fallback either", () => {
    mockSignatures = { signatures: [], default_signature_id: null, fallback_signature_html: null, image_urls: {} };
    setup();
    expect(body()).toBe("");
  });

  it("inserts the default once signatures finish loading after the composer opened", () => {
    mockSignatures = undefined;
    const { rerender, props } = setup();
    expect(body()).toBe("");

    mockSignatures = list();
    rerender(<ReplyComposer {...props} />);
    expect(selected()).toBe("s1");
    expect(screen.getByRole("button", { name: "Send Reply" })).toBeDisabled();
  });
});
