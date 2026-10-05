import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SignatureSelector } from "@tw/components/mail/SignatureSelector";

const OPTIONS = [
  { id: "s1", name: "Probe Practice Solutions", html: "", isDefault: true },
  { id: "s2", name: "Carolina Psychiatry", html: "", isDefault: false },
];

describe("SignatureSelector", () => {
  it("shows this email's signature on the trigger and tags the default", async () => {
    const onSelect = vi.fn();
    render(
      <SignatureSelector options={OPTIONS} selectedId="s2" hasSavedSignatures onSelect={onSelect} />
    );
    expect(screen.getByRole("button", { name: "Choose signature" })).toHaveTextContent("Carolina Psychiatry");

    await userEvent.click(screen.getByRole("button", { name: "Choose signature" }));
    const probe = await screen.findByRole("menuitem", { name: /Probe Practice Solutions/ });
    expect(probe).toHaveTextContent("Default");

    await userEvent.click(probe);
    expect(onSelect).toHaveBeenCalledWith("s1");
  });

  it("shows a clear empty state instead of a broken dropdown", async () => {
    const onSelect = vi.fn();
    render(<SignatureSelector options={[]} selectedId={null} hasSavedSignatures={false} onSelect={onSelect} />);
    expect(screen.getByRole("button", { name: "Choose signature" })).toHaveTextContent("None");

    await userEvent.click(screen.getByRole("button", { name: "Choose signature" }));
    expect(await screen.findByText(/No saved signatures/)).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /No signature/ })).toBeInTheDocument();
  });
});
