// jsdom has no DataTransfer/ClipboardEvent file support, so the intake
// tests drive the helpers with minimal structural fakes.
export function makeFile(name: string, type = "", size = 10): File {
  const file = new File(["x"], name, { type });
  Object.defineProperty(file, "size", { value: size });
  return file;
}

interface FakeDataTransferInit {
  files?: File[];
  // Only exposed through `items` (some browsers do this for screenshots).
  itemFiles?: File[];
  types?: string[];
  data?: Record<string, string>;
}

export function fakeDataTransfer({ files = [], itemFiles = [], types, data = {} }: FakeDataTransferInit = {}): DataTransfer {
  const itemSource = itemFiles.length > 0 ? itemFiles : files;
  const allTypes = types ?? [...(files.length || itemFiles.length ? ["Files"] : []), ...Object.keys(data)];
  return {
    files: files as unknown as FileList,
    types: allTypes,
    items: itemSource.map((file) => ({
      kind: "file",
      type: file.type,
      getAsFile: () => file,
    })) as unknown as DataTransferItemList,
    getData: (format: string) => data[format] ?? "",
  } as unknown as DataTransfer;
}
