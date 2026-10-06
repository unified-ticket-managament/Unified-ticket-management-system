import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReadReceiptsSettingCard } from "@/components/settings/ReadReceiptsSettingCard";
import { SettingsPanel } from "@/components/settings/SettingsPanel";
import { getMailFeatures } from "@tw/api/inbox";
import { getReadReceiptSetting, updateReadReceiptSetting } from "@tw/api/appSettings";
import { ReadReceiptCheckbox } from "@tw/components/mail/ReadReceiptCheckbox";
import { resetMailFeaturesCacheForTests, useMailFeatures } from "@tw/hooks/useMailFeatures";

// The REAL hook and card wired together (only the network is mocked):
// switching the setting in Settings shows / hides the composer's
// "Request read receipt" checkbox without a reload. Also proves the card
// is part of the existing Settings panel.

vi.mock("@tw/api/appSettings", () => ({
  getReadReceiptSetting: vi.fn(),
  updateReadReceiptSetting: vi.fn(),
}));
vi.mock("@tw/api/inbox", () => ({ getMailFeatures: vi.fn() }));
vi.mock("@/hooks/use-toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("@/services", () => ({
  authService: { updateProfile: vi.fn(), changePassword: vi.fn() },
}));
vi.mock("@/components/settings/EmailSignaturesCard", () => ({ EmailSignaturesCard: () => null }));
vi.mock("@/components/settings/change-password-dialog", () => ({ ChangePasswordDialog: () => null }));

function Wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

// Stands in for a composer: shows the checkbox only when the feature is on.
function ComposerHarness() {
  const { read_receipts_enabled } = useMailFeatures();
  return read_receipts_enabled ? (
    <ReadReceiptCheckbox checked={false} onCheckedChange={() => {}} />
  ) : (
    <p>no receipt option</p>
  );
}

const checkbox = () => screen.queryByRole("checkbox", { name: /request read receipt/i });

beforeEach(() => {
  vi.clearAllMocks();
  resetMailFeaturesCacheForTests();
  vi.mocked(getMailFeatures).mockResolvedValue({ read_receipts_enabled: false });
  vi.mocked(getReadReceiptSetting).mockResolvedValue({
    read_receipts_enabled: false,
    can_manage: true,
  });
});

describe("the existing Settings panel", () => {
  it("includes Email & Communication > Read Receipts alongside the other settings", async () => {
    render(
      <Wrapper>
        <SettingsPanel open />
      </Wrapper>
    );

    expect(await screen.findByText("Email & Communication")).toBeInTheDocument();
    expect(await screen.findByRole("switch", { name: "Read Receipts" })).toBeInTheDocument();
    // Existing sections are still there.
    expect(screen.getByText("Security")).toBeInTheDocument();
  });
});

describe("setting -> composer", () => {
  it("OFF: the composer has no Request read receipt option", async () => {
    render(
      <Wrapper>
        <ComposerHarness />
      </Wrapper>
    );

    expect(await screen.findByText("no receipt option")).toBeInTheDocument();
    expect(checkbox()).toBeNull();
  });

  it("turning it ON in Settings makes the option appear (and OFF removes it)", async () => {
    vi.mocked(updateReadReceiptSetting)
      .mockResolvedValueOnce({ read_receipts_enabled: true, can_manage: true })
      .mockResolvedValueOnce({ read_receipts_enabled: false, can_manage: true });
    render(
      <Wrapper>
        <ReadReceiptsSettingCard />
        <ComposerHarness />
      </Wrapper>
    );
    const toggle = await screen.findByRole("switch", { name: "Read Receipts" });
    expect(checkbox()).toBeNull();

    fireEvent.click(toggle);
    await waitFor(() => expect(checkbox()).not.toBeNull());

    fireEvent.click(screen.getByRole("switch", { name: "Read Receipts" }));
    await waitFor(() => expect(checkbox()).toBeNull());
    expect(updateReadReceiptSetting).toHaveBeenNthCalledWith(1, true);
    expect(updateReadReceiptSetting).toHaveBeenNthCalledWith(2, false);
  });

  it("a backend that already has it ON shows the option on first load", async () => {
    vi.mocked(getMailFeatures).mockResolvedValue({ read_receipts_enabled: true });
    render(
      <Wrapper>
        <ComposerHarness />
      </Wrapper>
    );

    await waitFor(() => expect(checkbox()).not.toBeNull());
  });
});
