import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReadReceiptsSettingCard } from "@/components/settings/ReadReceiptsSettingCard";
import { getReadReceiptSetting, updateReadReceiptSetting } from "@tw/api/appSettings";
import { setMailFeatures } from "@tw/hooks/useMailFeatures";

// Settings > Email & Communication > Read Receipts: shows the backend
// value, lets only an authorized administrator change it, explains ON and
// OFF, and tells the composers about a change immediately.

vi.mock("@tw/api/appSettings", () => ({
  getReadReceiptSetting: vi.fn(),
  updateReadReceiptSetting: vi.fn(),
}));
vi.mock("@tw/hooks/useMailFeatures", () => ({ setMailFeatures: vi.fn() }));
const toast = vi.fn();
vi.mock("@/hooks/use-toast", () => ({ useToast: () => ({ toast }) }));

function renderCard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ReadReceiptsSettingCard />
    </QueryClientProvider>
  );
}

const toggle = () => screen.getByRole("switch", { name: "Read Receipts" });
const isOn = () => toggle().getAttribute("data-state") === "checked";

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getReadReceiptSetting).mockResolvedValue({
    read_receipts_enabled: false,
    can_manage: true,
  });
});

describe("what the setting looks like", () => {
  it("appears under Email & Communication with its description", async () => {
    renderCard();

    expect(await screen.findByText("Email & Communication")).toBeInTheDocument();
    expect(screen.getByText("Read Receipts")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Allow users to request read receipts when sending emails. Recipients may choose whether to send a receipt."
      )
    ).toBeInTheDocument();
  });

  it("shows a loading indicator, not a guessed value, until the backend answers", async () => {
    let resolve!: (value: { read_receipts_enabled: boolean; can_manage: boolean }) => void;
    vi.mocked(getReadReceiptSetting).mockReturnValue(new Promise((r) => (resolve = r)));
    renderCard();

    expect(screen.queryByRole("switch")).toBeNull();
    expect(screen.getByLabelText("Loading")).toBeInTheDocument();

    resolve({ read_receipts_enabled: true, can_manage: true });
    expect(await screen.findByRole("switch", { name: "Read Receipts" })).toBeInTheDocument();
  });

  it("OFF (the default): switch off and explains the option is unavailable to agents", async () => {
    renderCard();
    await screen.findByRole("switch");

    expect(isOn()).toBe(false);
    expect(
      screen.getByText("OFF: The Request read receipt option is unavailable to agents.")
    ).toBeInTheDocument();
    expect(screen.queryByText(/^ON:/)).toBeNull();
  });

  it("ON: switch on and explains agents can request receipts", async () => {
    vi.mocked(getReadReceiptSetting).mockResolvedValue({
      read_receipts_enabled: true,
      can_manage: true,
    });
    renderCard();
    await screen.findByRole("switch");

    expect(isOn()).toBe(true);
    expect(
      screen.getByText("ON: Agents can request read receipts when sending emails.")
    ).toBeInTheDocument();
  });
});

describe("changing it (authorized administrator)", () => {
  it("turns ON: saves, updates the display, tells the composers, and confirms", async () => {
    vi.mocked(updateReadReceiptSetting).mockResolvedValue({
      read_receipts_enabled: true,
      can_manage: true,
    });
    renderCard();
    await screen.findByRole("switch");

    fireEvent.click(toggle());

    await waitFor(() => expect(isOn()).toBe(true));
    expect(updateReadReceiptSetting).toHaveBeenCalledWith(true);
    expect(setMailFeatures).toHaveBeenCalledWith({ read_receipts_enabled: true });
    expect(toast).toHaveBeenCalledWith({ title: "Read Receipts enabled." });
    expect(
      screen.getByText("ON: Agents can request read receipts when sending emails.")
    ).toBeInTheDocument();
  });

  it("turns OFF: saves, updates the display and tells the composers", async () => {
    vi.mocked(getReadReceiptSetting).mockResolvedValue({
      read_receipts_enabled: true,
      can_manage: true,
    });
    vi.mocked(updateReadReceiptSetting).mockResolvedValue({
      read_receipts_enabled: false,
      can_manage: true,
    });
    renderCard();
    await screen.findByRole("switch");

    fireEvent.click(toggle());

    await waitFor(() => expect(isOn()).toBe(false));
    expect(updateReadReceiptSetting).toHaveBeenCalledWith(false);
    expect(setMailFeatures).toHaveBeenCalledWith({ read_receipts_enabled: false });
    expect(toast).toHaveBeenCalledWith({ title: "Read Receipts disabled." });
  });

  it("a failed save leaves the displayed value unchanged and says so", async () => {
    vi.mocked(updateReadReceiptSetting).mockRejectedValue(new Error("403"));
    renderCard();
    await screen.findByRole("switch");

    fireEvent.click(toggle());

    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith({
        title: "Couldn't update the Read Receipts setting.",
        variant: "destructive",
      })
    );
    expect(isOn()).toBe(false);
    expect(setMailFeatures).not.toHaveBeenCalled();
  });

  it("the switch is disabled while a save is in flight (no double-submit)", async () => {
    let resolve!: (value: { read_receipts_enabled: boolean; can_manage: boolean }) => void;
    vi.mocked(updateReadReceiptSetting).mockReturnValue(new Promise((r) => (resolve = r)));
    renderCard();
    await screen.findByRole("switch");

    fireEvent.click(toggle());
    await waitFor(() => expect(toggle()).toBeDisabled());

    resolve({ read_receipts_enabled: true, can_manage: true });
    await waitFor(() => expect(toggle()).not.toBeDisabled());
    expect(updateReadReceiptSetting).toHaveBeenCalledTimes(1);
  });
});

describe("everyone else", () => {
  beforeEach(() => {
    vi.mocked(getReadReceiptSetting).mockResolvedValue({
      read_receipts_enabled: true,
      can_manage: false,
    });
  });

  it("can see the current value but cannot change it", async () => {
    renderCard();
    await screen.findByRole("switch");

    expect(isOn()).toBe(true);
    expect(toggle()).toBeDisabled();
    expect(screen.getByText("Only administrators can change this setting.")).toBeInTheDocument();
  });

  it("clicking the disabled switch never calls the API", async () => {
    renderCard();
    await screen.findByRole("switch");

    fireEvent.click(toggle());

    expect(updateReadReceiptSetting).not.toHaveBeenCalled();
    expect(isOn()).toBe(true);
  });
});

describe("when the setting cannot be loaded", () => {
  it("shows an error, offers no usable control, and never invents a value", async () => {
    vi.mocked(getReadReceiptSetting).mockRejectedValue(new Error("network"));
    renderCard();

    expect(await screen.findByText("Couldn't load the Read Receipts setting.")).toBeInTheDocument();
    expect(toggle()).toBeDisabled();
    expect(isOn()).toBe(false);
  });
});
