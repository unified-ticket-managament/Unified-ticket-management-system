import { describe, expect, it } from "vitest";

import type { MailFolder } from "@tw/types";
import {
  ancestorIds,
  buildFolderTree,
  flattenVisible,
  folderPathLabel,
  subtreeIds,
  withAncestors,
} from "./folderTree";

const f = (id: string, name: string, parent: string | null = null): MailFolder => ({
  folder_id: id,
  name,
  parent_folder_id: parent,
  created_by: null,
  created_at: "",
});

const FOLDERS = [
  f("1", "Clients"),
  f("2", "Active Clients", "1"),
  f("3", "High Priority", "2"),
  f("4", "Old Clients", "1"),
  f("5", "Projects"),
  f("6", "Orphan", "missing"),
];

describe("folderTree", () => {
  it("builds nested nodes sorted by name; unknown parent becomes root", () => {
    const tree = buildFolderTree(FOLDERS);
    expect(tree.map((n) => n.folder.name)).toEqual(["Clients", "Orphan", "Projects"]);
    const clients = tree[0];
    expect(clients.children.map((n) => n.folder.name)).toEqual(["Active Clients", "Old Clients"]);
    expect(clients.children[0].children[0]).toMatchObject({ depth: 2 });
  });

  it("supports deep nesting", () => {
    const deep = Array.from({ length: 12 }, (_, i) => f(`d${i}`, `L${i}`, i ? `d${i - 1}` : null));
    let node = buildFolderTree(deep)[0];
    for (let i = 1; i < 12; i++) node = node.children[0];
    expect(node.depth).toBe(11);
  });

  it("collapse/expand controls visible rows", () => {
    const tree = buildFolderTree(FOLDERS);
    expect(flattenVisible(tree, new Set()).map((n) => n.folder.folder_id)).toEqual(["1", "6", "5"]);
    expect(flattenVisible(tree, new Set(["1"])).map((n) => n.folder.folder_id)).toEqual([
      "1", "2", "4", "6", "5",
    ]);
  });

  it("computes subtree, path and ancestors", () => {
    expect([...subtreeIds(FOLDERS, "1")].sort()).toEqual(["1", "2", "3", "4"]);
    expect(folderPathLabel(FOLDERS, "3")).toBe("Clients / Active Clients / High Priority");
    expect(ancestorIds(FOLDERS, "3")).toEqual(["1", "2"]);
  });

  it("keeps ancestors of kept folders", () => {
    const kept = withAncestors(FOLDERS, (x) => x.folder_id === "3");
    expect(kept.map((x) => x.folder_id).sort()).toEqual(["1", "2", "3"]);
  });

  it("tolerates a self-parent without looping", () => {
    expect(buildFolderTree([f("x", "Self", "x")])).toHaveLength(1);
  });
});
