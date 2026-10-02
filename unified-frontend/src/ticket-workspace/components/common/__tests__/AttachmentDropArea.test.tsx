import { useEffect, useRef } from "react";
import { createEvent, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AttachmentDropArea } from "@tw/components/common/AttachmentDropArea";
import { fakeDataTransfer, makeFile } from "@tw/lib/__tests__/testUtils";

const pdf = makeFile("invoice.pdf", "application/pdf");
const png = makeFile("shot.png", "image/png");

// A stand-in for TipTap's contenteditable: same `.ProseMirror` class the
// drop area keys on, plus native listeners recording whether the editor's
// own paste/drop handling would have run.
function FakeEditor({ onNativePaste, onNativeDrop }: { onNativePaste: () => void; onNativeDrop: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current!;
    el.addEventListener("paste", onNativePaste);
    el.addEventListener("drop", onNativeDrop);
    return () => {
      el.removeEventListener("paste", onNativePaste);
      el.removeEventListener("drop", onNativeDrop);
    };
  }, [onNativePaste, onNativeDrop]);
  return <div ref={ref} className="ProseMirror" contentEditable data-testid="editor" />;
}

function setup(props: { disabled?: boolean } = {}) {
  const onFiles = vi.fn();
  const onNativePaste = vi.fn();
  const onNativeDrop = vi.fn();
  render(
    <AttachmentDropArea onFiles={onFiles} data-testid="area" {...props}>
      <input aria-label="Cc" />
      <div data-attachment-dropzone data-testid="dropzone">
        box
      </div>
      <FakeEditor onNativePaste={onNativePaste} onNativeDrop={onNativeDrop} />
    </AttachmentDropArea>
  );
  return { onFiles, onNativePaste, onNativeDrop };
}

function drop(target: Element, files: File[], extra: Parameters<typeof fakeDataTransfer>[0] = {}) {
  const event = createEvent.drop(target, { dataTransfer: fakeDataTransfer({ files, ...extra }) });
  fireEvent(target, event);
  return event;
}

function paste(target: Element, init: Parameters<typeof fakeDataTransfer>[0]) {
  const event = createEvent.paste(target, { clipboardData: fakeDataTransfer(init) });
  fireEvent(target, event);
  return event;
}

describe("AttachmentDropArea drag states", () => {
  it("shows the drop overlay on dragenter and hides it on drop", () => {
    setup();
    expect(screen.queryByTestId("attachment-drop-overlay")).not.toBeInTheDocument();
    fireEvent.dragEnter(screen.getByTestId("area"), { dataTransfer: fakeDataTransfer({ files: [pdf] }) });
    expect(screen.getByTestId("attachment-drop-overlay")).toHaveTextContent("Drop files here");
    expect(screen.getByTestId("attachment-drop-overlay")).toHaveTextContent("Release to attach");
    drop(screen.getByTestId("area"), [pdf]);
    expect(screen.queryByTestId("attachment-drop-overlay")).not.toBeInTheDocument();
  });

  it("does not flicker when the drag crosses child elements", () => {
    setup();
    const dt = fakeDataTransfer({ files: [pdf] });
    const area = screen.getByTestId("area");
    const child = screen.getByLabelText("Cc");
    fireEvent.dragEnter(area, { dataTransfer: dt });
    fireEvent.dragEnter(child, { dataTransfer: dt }); // entering a child...
    fireEvent.dragLeave(area, { dataTransfer: dt }); // ...fires leave on the parent
    expect(screen.getByTestId("attachment-drop-overlay")).toBeInTheDocument();
    fireEvent.dragLeave(child, { dataTransfer: dt }); // the drag actually leaves
    expect(screen.queryByTestId("attachment-drop-overlay")).not.toBeInTheDocument();
  });

  it("ignores text/link drags — no overlay, no preventDefault", () => {
    setup();
    const dt = fakeDataTransfer({ types: ["text/plain"], data: { "text/plain": "selected text" } });
    fireEvent.dragEnter(screen.getByTestId("area"), { dataTransfer: dt });
    expect(screen.queryByTestId("attachment-drop-overlay")).not.toBeInTheDocument();
    const over = createEvent.dragOver(screen.getByTestId("area"), { dataTransfer: dt });
    fireEvent(screen.getByTestId("area"), over);
    expect(over.defaultPrevented).toBe(false);
  });

  it("prevents the browser default on dragover for file drags so the drop is allowed", () => {
    setup();
    const over = createEvent.dragOver(screen.getByTestId("area"), { dataTransfer: fakeDataTransfer({ files: [pdf] }) });
    fireEvent(screen.getByTestId("area"), over);
    expect(over.defaultPrevented).toBe(true);
  });

  it("does not promise 'Release to attach' for images dragged over the editor", () => {
    setup();
    fireEvent.dragEnter(screen.getByTestId("editor"), { dataTransfer: fakeDataTransfer({ files: [png] }) });
    expect(screen.queryByTestId("attachment-drop-overlay")).not.toBeInTheDocument();
  });
});

describe("AttachmentDropArea drop", () => {
  it("attaches a file dropped outside the editor and stops the browser opening it", () => {
    const { onFiles } = setup();
    const event = drop(screen.getByLabelText("Cc"), [pdf]);
    expect(onFiles).toHaveBeenCalledWith([pdf]);
    expect(event.defaultPrevented).toBe(true);
  });

  it("attaches multiple dropped files together", () => {
    const { onFiles } = setup();
    drop(screen.getByTestId("area"), [pdf, makeFile("b.docx"), png]);
    expect(onFiles).toHaveBeenCalledTimes(1);
    expect(onFiles.mock.calls[0][0]).toHaveLength(3);
  });

  it("attaches an image dropped outside the editor", () => {
    const { onFiles } = setup();
    drop(screen.getByTestId("area"), [png]);
    expect(onFiles).toHaveBeenCalledWith([png]);
  });

  it("attaches a non-image dropped inside the editor and hides the drop from the editor", () => {
    const { onFiles, onNativeDrop } = setup();
    const event = drop(screen.getByTestId("editor"), [pdf]);
    expect(onFiles).toHaveBeenCalledWith([pdf]);
    expect(event.defaultPrevented).toBe(true);
    expect(onNativeDrop).not.toHaveBeenCalled();
  });

  it("leaves an image dropped inside the editor entirely to the editor (inline image)", () => {
    const { onFiles, onNativeDrop } = setup();
    const event = drop(screen.getByTestId("editor"), [png]);
    expect(onFiles).not.toHaveBeenCalled();
    expect(onNativeDrop).toHaveBeenCalledTimes(1);
    expect(event.defaultPrevented).toBe(false);
  });

  it("splits a mixed drop inside the editor: PDF attached, image still reaches the editor", () => {
    const { onFiles, onNativeDrop } = setup();
    drop(screen.getByTestId("editor"), [pdf, png]);
    expect(onFiles).toHaveBeenCalledWith([pdf]);
    expect(onNativeDrop).toHaveBeenCalledTimes(1);
  });

  it("does not process a file twice when it lands on the composer's own dropzone box", () => {
    const { onFiles } = setup();
    drop(screen.getByTestId("dropzone"), [pdf]);
    expect(onFiles).not.toHaveBeenCalled();
  });

  it("ignores a text drag", () => {
    const { onFiles } = setup();
    const event = createEvent.drop(screen.getByTestId("area"), {
      dataTransfer: fakeDataTransfer({ types: ["text/plain"], data: { "text/plain": "x" } }),
    });
    fireEvent(screen.getByTestId("area"), event);
    expect(onFiles).not.toHaveBeenCalled();
    expect(event.defaultPrevented).toBe(false);
  });

  it("when disabled, swallows the drop (no navigation) but attaches nothing and shows no overlay", () => {
    const { onFiles } = setup({ disabled: true });
    fireEvent.dragEnter(screen.getByTestId("area"), { dataTransfer: fakeDataTransfer({ files: [pdf] }) });
    expect(screen.queryByTestId("attachment-drop-overlay")).not.toBeInTheDocument();
    const event = drop(screen.getByTestId("area"), [pdf]);
    expect(onFiles).not.toHaveBeenCalled();
    expect(event.defaultPrevented).toBe(true);
  });
});

describe("AttachmentDropArea paste", () => {
  it("attaches a pasted PDF inside the editor and keeps it from the editor", () => {
    const { onFiles, onNativePaste } = setup();
    const event = paste(screen.getByTestId("editor"), { files: [pdf] });
    expect(onFiles).toHaveBeenCalledWith([pdf]);
    expect(event.defaultPrevented).toBe(true);
    expect(onNativePaste).not.toHaveBeenCalled();
  });

  it("leaves a pasted image inside the editor to the editor (inline image)", () => {
    const { onFiles, onNativePaste } = setup();
    const event = paste(screen.getByTestId("editor"), { files: [png] });
    expect(onFiles).not.toHaveBeenCalled();
    expect(onNativePaste).toHaveBeenCalledTimes(1);
    expect(event.defaultPrevented).toBe(false);
  });

  it("attaches a pasted image when focus is outside the editor", () => {
    const { onFiles } = setup();
    paste(screen.getByLabelText("Cc"), { files: [png] });
    expect(onFiles).toHaveBeenCalledWith([png]);
  });

  it("mixed image + PDF inside the editor: PDF attached, image still reaches the editor", () => {
    const { onFiles, onNativePaste } = setup();
    paste(screen.getByTestId("editor"), { files: [png, pdf] });
    expect(onFiles).toHaveBeenCalledWith([pdf]);
    expect(onNativePaste).toHaveBeenCalledTimes(1);
  });

  it.each(["editor", "input"])("never touches a plain-text paste (%s)", (where) => {
    const { onFiles, onNativePaste } = setup();
    const target = where === "editor" ? screen.getByTestId("editor") : screen.getByLabelText("Cc");
    const event = paste(target, { data: { "text/plain": "Please review this ticket." } });
    expect(onFiles).not.toHaveBeenCalled();
    expect(event.defaultPrevented).toBe(false);
    if (where === "editor") expect(onNativePaste).toHaveBeenCalledTimes(1);
  });

  it("never touches unsupported clipboard data", () => {
    const { onFiles } = setup();
    const event = paste(screen.getByTestId("editor"), { types: ["application/x-custom"] });
    expect(onFiles).not.toHaveBeenCalled();
    expect(event.defaultPrevented).toBe(false);
  });

  it("does nothing when disabled", () => {
    const { onFiles, onNativePaste } = setup({ disabled: true });
    paste(screen.getByTestId("editor"), { files: [pdf] });
    expect(onFiles).not.toHaveBeenCalled();
    expect(onNativePaste).toHaveBeenCalledTimes(1);
  });
});
