// INVESTIGATION / CHARACTERIZATION tests for the frontend half of a stored
// attachment download (AttachmentList -> downloadAttachmentFile -> axios blob
// -> <a download>), using voice-note (audio) attachments.
//
// These pin CURRENT behavior; no production code was changed. PASS = the
// frontend handles that case correctly. FAIL = reproduces the reported issue.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { getMock } = vi.hoisted(() => ({ getMock: vi.fn() }));
vi.mock("@tw/api/client", () => ({ apiClient: { get: getMock } }));

import { downloadAttachmentFile } from "@tw/api/interaction";
import { AttachmentList } from "@tw/components/common/AttachmentList";
import type { AttachmentMeta } from "@tw/types";

const voiceNote = (over: Partial<AttachmentMeta> = {}): AttachmentMeta => ({
  id: "att-1",
  filename: "Voice_Message.m4a",
  mime_type: "audio/mp4",
  size: 2048,
  download_url: "https://storage.example/signed?download=Voice_Message.m4a",
  preview_url: null,
  is_external_link: false,
  is_inline: false,
  ...over,
});

let events: string[];
let clickedLinks: HTMLAnchorElement[];

beforeEach(() => {
  events = [];
  clickedLinks = [];
  getMock.mockReset();
  window.URL.createObjectURL = vi.fn(() => {
    events.push("createObjectURL");
    return "blob:voice-1";
  });
  window.URL.revokeObjectURL = vi.fn(() => {
    events.push("revokeObjectURL");
  });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    events.push("click");
    clickedLinks.push(this);
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("downloadAttachmentFile with a voice note", () => {
  it("requests the authenticated download endpoint as a blob and saves it under the attachment filename", async () => {
    const audio = new Blob([new Uint8Array([0, 1, 2, 255])], { type: "audio/mp4" });
    getMock.mockResolvedValue({ data: audio });

    await downloadAttachmentFile("att-1", "Voice_Message.m4a");

    expect(getMock).toHaveBeenCalledWith("/attachments/att-1/download", { responseType: "blob" });
    expect(window.URL.createObjectURL).toHaveBeenCalledWith(audio);
    expect(clickedLinks).toHaveLength(1);
    expect(clickedLinks[0].download).toBe("Voice_Message.m4a");
    expect(clickedLinks[0].href).toBe("blob:voice-1");
    expect(document.querySelector("a[download]")).toBeNull(); // temp link removed
  });

  it("CHARACTERIZATION: revokes the object URL synchronously right after click() (no deferral)", async () => {
    getMock.mockResolvedValue({ data: new Blob(["x"], { type: "audio/mp4" }) });

    await downloadAttachmentFile("att-1", "Voice_Message.m4a");

    // Order is create -> click -> revoke with nothing awaited in between.
    // Chrome starts the save synchronously so this normally works; browsers
    // that resolve the blob asynchronously can lose the file. Unverifiable
    // without a real browser.
    expect(events).toEqual(["createObjectURL", "click", "revokeObjectURL"]);
  });

  it("propagates a failed request to the caller (no catch inside downloadAttachmentFile)", async () => {
    getMock.mockRejectedValue(new Error("Request failed with status code 500"));

    await expect(downloadAttachmentFile("att-1", "Voice_Message.m4a")).rejects.toThrow(
      "Request failed with status code 500"
    );
    expect(clickedLinks).toHaveLength(0);
  });
});

describe("AttachmentList with a voice note", () => {
  it("renders the voice note and downloads it via the authenticated blob path (not a plain navigation)", async () => {
    getMock.mockResolvedValue({ data: new Blob(["x"], { type: "audio/mp4" }) });

    render(<AttachmentList attachments={[voiceNote()]} />);
    const row = screen.getByText("Voice_Message.m4a").closest("button");
    expect(row).not.toBeNull(); // a <button>, not an <a href=download_url>

    fireEvent.click(row!);

    await waitFor(() => expect(getMock).toHaveBeenCalledWith("/attachments/att-1/download", { responseType: "blob" }));
    await waitFor(() => expect(clickedLinks[0]?.download).toBe("Voice_Message.m4a"));
  });

  it("treats an audio attachment exactly like a PDF (same button/blob path)", async () => {
    getMock.mockResolvedValue({ data: new Blob(["x"]) });
    const pdf = voiceNote({ id: "att-2", filename: "invoice.pdf", mime_type: "application/pdf" });

    render(<AttachmentList attachments={[voiceNote(), pdf]} />);

    expect(screen.getByText("Voice_Message.m4a").closest("button")).not.toBeNull();
    expect(screen.getByText("invoice.pdf").closest("button")).not.toBeNull();
  });

  it("hides a voice note flagged is_inline (list filters on !is_inline)", () => {
    render(<AttachmentList attachments={[voiceNote({ is_inline: true })]} />);
    expect(screen.queryByText("Voice_Message.m4a")).toBeNull();
  });
});
