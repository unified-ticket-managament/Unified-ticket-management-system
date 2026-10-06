import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ReadReceiptCheckbox, READ_RECEIPT_HELP_TEXT } from "@tw/components/mail/ReadReceiptCheckbox";
import { ReadReceiptStatus } from "@tw/components/mail/ReadReceiptStatus";

describe("ReadReceiptStatus", () => {
  it("renders nothing when there is nothing to show", () => {
    const { container } = render(<ReadReceiptStatus receipts={[]} />);
    expect(container.firstChild).toBeNull();
    const none = render(<ReadReceiptStatus receipts={null} />);
    expect(none.container.firstChild).toBeNull();
  });

  it("a confirmed receipt shows the receipt time", () => {
    render(
      <ReadReceiptStatus
        receipts={[{ recipient_email: "a@example.com", status: "CONFIRMED", read_at: "2026-10-06T08:21:37Z" }]}
      />
    );
    const row = screen.getByRole("listitem");
    expect(row.textContent).toContain("a@example.com");
    expect(row.textContent).toMatch(/Read receipt received · .+/);
  });

  it("a confirmed receipt with no timestamp still reads sensibly", () => {
    render(
      <ReadReceiptStatus receipts={[{ recipient_email: "a@example.com", status: "CONFIRMED" }]} />
    );
    expect(screen.getByRole("listitem").textContent).toContain("Read receipt received");
    expect(screen.getByRole("listitem").textContent).not.toContain("·");
  });

  it("a requested row (no receipt yet) says no receipt received — never unread", () => {
    render(<ReadReceiptStatus receipts={[{ recipient_email: "b@example.com", status: "REQUESTED" }]} />);
    expect(screen.getByRole("listitem").textContent).toContain("No receipt received");
    expect(document.body.textContent).not.toMatch(/unread|not read/i);
  });

  it("an unknown status is treated as no receipt (never as read)", () => {
    render(<ReadReceiptStatus receipts={[{ recipient_email: "b@example.com", status: "SOMETHING_NEW" }]} />);
    expect(screen.getByRole("listitem").textContent).toContain("No receipt received");
  });

  it("shows multiple recipients independently", () => {
    render(
      <ReadReceiptStatus
        receipts={[
          { recipient_email: "a@example.com", status: "CONFIRMED", read_at: "2026-10-06T10:00:00Z" },
          { recipient_email: "b@example.com", status: "CONFIRMED", read_at: "2026-10-06T10:15:00Z" },
          { recipient_email: "c@example.com", status: "REQUESTED" },
        ]}
      />
    );
    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    expect(rows[2].textContent).toContain("No receipt received");
  });

  it("with only the request flag, shows a neutral requested line", () => {
    render(<ReadReceiptStatus requested />);
    expect(screen.getByText("Read receipt requested")).toBeInTheDocument();
  });

  it("carries the optional-receipt explanation", () => {
    render(<ReadReceiptStatus receipts={[{ recipient_email: "a@example.com", status: "REQUESTED" }]} />);
    expect(screen.getByRole("list", { name: "Read receipts" })).toHaveAttribute("title", READ_RECEIPT_HELP_TEXT);
  });
});

describe("ReadReceiptCheckbox", () => {
  it("reports ticking and unticking", () => {
    const onChange = vi.fn();
    const { rerender } = render(<ReadReceiptCheckbox checked={false} onCheckedChange={onChange} />);
    fireEvent.click(screen.getByRole("checkbox", { name: /request read receipt/i }));
    expect(onChange).toHaveBeenLastCalledWith(true);

    rerender(<ReadReceiptCheckbox checked onCheckedChange={onChange} />);
    fireEvent.click(screen.getByRole("checkbox", { name: /request read receipt/i }));
    expect(onChange).toHaveBeenLastCalledWith(false);
  });

  it("can be disabled while sending", () => {
    const onChange = vi.fn();
    render(<ReadReceiptCheckbox checked={false} disabled onCheckedChange={onChange} />);
    fireEvent.click(screen.getByRole("checkbox", { name: /request read receipt/i }));
    expect(onChange).not.toHaveBeenCalled();
  });

  it("explains that receipts are optional and recipient-dependent", () => {
    render(<ReadReceiptCheckbox checked={false} onCheckedChange={vi.fn()} />);
    expect(screen.getByText(/depends on the recipient's mail system/i)).toBeInTheDocument();
    expect(screen.getByText("Request read receipt").closest("label")).toHaveAttribute(
      "title",
      READ_RECEIPT_HELP_TEXT
    );
  });
});
