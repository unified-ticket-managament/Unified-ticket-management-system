import { describe, expect, it } from "vitest";

import { MAX_ATTACHMENT_FILES, MAX_ATTACHMENT_SIZE_BYTES, validateFiles } from "@tw/lib/attachmentMeta";

function file(name: string, size = 10, type = "application/octet-stream"): File {
  const f = new File(["x"], name, { type });
  Object.defineProperty(f, "size", { value: size });
  return f;
}

// Baseline regression tests for the pre-existing validator — every
// attachment input method (picker, drop, paste) funnels through it.
describe("validateFiles (existing behavior)", () => {
  it("accepts allowed documents", () => {
    const names = ["a.pdf", "b.docx", "c.xlsx", "d.csv", "e.txt", "f.zip", "g.png"];
    const { accepted, errors } = validateFiles(names.map((n) => file(n)));
    expect(accepted).toHaveLength(names.length);
    expect(errors).toEqual([]);
  });

  it("rejects an unsupported extension", () => {
    const { accepted, errors } = validateFiles([file("virus.exe")]);
    expect(accepted).toHaveLength(0);
    expect(errors[0]).toContain("unsupported file type");
  });

  it("rejects an oversized file", () => {
    const { accepted, errors } = validateFiles([file("big.pdf", MAX_ATTACHMENT_SIZE_BYTES + 1)]);
    expect(accepted).toHaveLength(0);
    expect(errors[0]).toContain("size limit");
  });

  it("caps the file count", () => {
    const many = Array.from({ length: MAX_ATTACHMENT_FILES + 2 }, (_, i) => file(`f${i}.pdf`));
    const { accepted, errors } = validateFiles(many);
    expect(accepted).toHaveLength(MAX_ATTACHMENT_FILES);
    expect(errors[0]).toContain(`Only ${MAX_ATTACHMENT_FILES} files`);
  });
});
