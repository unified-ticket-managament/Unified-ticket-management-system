import { useEffect, useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  EMAIL_WINDOW_MAXIMIZED_CLASS,
  EMAIL_WINDOW_NORMAL_CLASS,
  EmailWindow,
} from "@tw/components/mail/EmailWindow";

// The exact classes the double-click Dialog was rendered with before
// this feature existed (InboxPage.tsx). The normal/restored size is
// defined as these — nothing else.
const ORIGINAL_EMAIL_WINDOW_CLASS = "flex h-[85vh] max-h-[85vh] w-full max-w-5xl flex-col gap-0 overflow-hidden p-0";

const mounts = vi.fn();
const unmounts = vi.fn();

// Stands in for MessageDetailsView + an open Reply composer: local state
// (typed text) that would be lost if the window ever remounted its body.
function EmailBody() {
  const [text, setText] = useState("");
  useEffect(() => {
    mounts();
    return () => unmounts();
  }, []);
  return (
    <div>
      <textarea aria-label="Reply text" value={text} onChange={(e) => setText(e.target.value)} />
      <span data-testid="attachment-chip">invoice.pdf</span>
    </div>
  );
}

function Host({ initiallyOpen = true }: { initiallyOpen?: boolean }) {
  const [open, setOpen] = useState(initiallyOpen);
  return (
    <>
      <button onClick={() => setOpen(true)}>open</button>
      <EmailWindow open={open} onClose={() => setOpen(false)} title="Printer is down">
        <EmailBody />
      </EmailWindow>
    </>
  );
}

const dialog = () => screen.getByRole("dialog");

describe("EmailWindow", () => {
  it("opens at exactly the existing window size, in the normal state, with the window controls", () => {
    mounts.mockClear();
    render(<Host />);
    expect(EMAIL_WINDOW_NORMAL_CLASS).toBe(ORIGINAL_EMAIL_WINDOW_CLASS);
    for (const cls of ORIGINAL_EMAIL_WINDOW_CLASS.split(" ")) expect(dialog()).toHaveClass(cls);
    expect(dialog()).not.toHaveClass("w-[100vw]");
    expect(screen.getByRole("button", { name: "Maximize" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Minimize" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Printer is down" })).toBeInTheDocument();
  });

  it("Minimize is inert while already at the normal size (no docked state exists)", () => {
    render(<Host />);
    expect(screen.getByRole("button", { name: "Minimize" })).toBeDisabled();
  });

  it("Maximize fills the viewport and the control becomes Restore", async () => {
    const user = userEvent.setup();
    render(<Host />);
    await user.click(screen.getByRole("button", { name: "Maximize" }));
    for (const cls of EMAIL_WINDOW_MAXIMIZED_CLASS.split(" ").filter((c) => !c.startsWith("sm:"))) {
      expect(dialog()).toHaveClass(cls);
    }
    expect(dialog()).toHaveClass("w-[100vw]", "h-[100vh]", "max-w-none");
    expect(screen.queryByRole("button", { name: "Maximize" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Restore" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Minimize" })).toBeEnabled();
  });

  it("Restore returns to the exact original window size", async () => {
    const user = userEvent.setup();
    render(<Host />);
    const originalClassName = dialog().className;

    await user.click(screen.getByRole("button", { name: "Maximize" }));
    expect(dialog().className).not.toBe(originalClassName);
    await user.click(screen.getByRole("button", { name: "Restore" }));

    expect(dialog().className).toBe(originalClassName);
    for (const cls of ORIGINAL_EMAIL_WINDOW_CLASS.split(" ")) expect(dialog()).toHaveClass(cls);
    expect(screen.getByRole("button", { name: "Maximize" })).toBeInTheDocument();
  });

  it("Minimize from maximized also returns to the exact original size", async () => {
    const user = userEvent.setup();
    render(<Host />);
    const originalClassName = dialog().className;
    await user.click(screen.getByRole("button", { name: "Maximize" }));
    await user.click(screen.getByRole("button", { name: "Minimize" }));
    expect(dialog().className).toBe(originalClassName);
  });

  it("closes from the normal state", async () => {
    const user = userEvent.setup();
    render(<Host />);
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("closes from the maximized state", async () => {
    const user = userEvent.setup();
    render(<Host />);
    await user.click(screen.getByRole("button", { name: "Maximize" }));
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("a window reopened after being closed while maximized starts at the normal size", async () => {
    const user = userEvent.setup();
    render(<Host />);
    await user.click(screen.getByRole("button", { name: "Maximize" }));
    await user.click(screen.getByRole("button", { name: "Close" }));
    await user.click(screen.getByRole("button", { name: "open" }));
    for (const cls of ORIGINAL_EMAIL_WINDOW_CLASS.split(" ")) expect(dialog()).toHaveClass(cls);
    expect(screen.getByRole("button", { name: "Maximize" })).toBeInTheDocument();
  });

  it("keeps the email body mounted and its state intact across maximize and restore", async () => {
    const user = userEvent.setup();
    mounts.mockClear();
    unmounts.mockClear();
    render(<Host />);

    await user.type(screen.getByLabelText("Reply text"), "Dear client, ");
    await user.click(screen.getByRole("button", { name: "Maximize" }));
    expect(screen.getByLabelText("Reply text")).toHaveValue("Dear client, ");
    expect(screen.getByTestId("attachment-chip")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Restore" }));
    expect(screen.getByLabelText("Reply text")).toHaveValue("Dear client, ");
    expect(screen.getByTestId("attachment-chip")).toBeInTheDocument();

    expect(mounts).toHaveBeenCalledTimes(1);
    expect(unmounts).not.toHaveBeenCalled();
  });

  it("keeps the close-only behavior: Escape does not dismiss the window", async () => {
    const user = userEvent.setup();
    render(<Host />);
    await user.keyboard("{Escape}");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
