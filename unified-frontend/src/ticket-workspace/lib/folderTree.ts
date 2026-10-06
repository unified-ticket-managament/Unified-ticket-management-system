import type { MailFolder } from "@tw/types";

// Pure helpers for the nested-folder model. The API returns a flat list
// (each row has parent_folder_id); every consumer — sidebar, Move To
// menus, rules picker — builds the tree through here so none of them
// re-implements the hierarchy logic.

export interface FolderNode {
  folder: MailFolder;
  depth: number;
  children: FolderNode[];
}

const byName = (a: MailFolder, b: MailFolder) =>
  a.name.trim().localeCompare(b.name.trim(), undefined, { sensitivity: "base" });

// A folder whose parent is not in the list (parent hidden from this
// user, or filtered out) is shown as a root rather than dropped.
export function buildFolderTree(folders: MailFolder[]): FolderNode[] {
  const ids = new Set(folders.map((f) => f.folder_id));
  const childrenOf = new Map<string | null, MailFolder[]>();
  for (const folder of folders) {
    const parent =
      folder.parent_folder_id &&
      folder.parent_folder_id !== folder.folder_id &&
      ids.has(folder.parent_folder_id)
        ? folder.parent_folder_id
        : null;
    const list = childrenOf.get(parent) ?? [];
    list.push(folder);
    childrenOf.set(parent, list);
  }
  const visited = new Set<string>();
  const build = (parent: string | null, depth: number): FolderNode[] =>
    (childrenOf.get(parent) ?? [])
      .slice()
      .sort(byName)
      .filter((f) => !visited.has(f.folder_id))
      .map((folder) => {
        visited.add(folder.folder_id);
        return { folder, depth, children: build(folder.folder_id, depth + 1) };
      });
  return build(null, 0);
}

// The folder's own id plus every descendant id.
export function subtreeIds(folders: MailFolder[], folderId: string): Set<string> {
  const result = new Set<string>([folderId]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const f of folders) {
      if (f.parent_folder_id && result.has(f.parent_folder_id) && !result.has(f.folder_id)) {
        result.add(f.folder_id);
        grew = true;
      }
    }
  }
  return result;
}

// Names from the root down to (and including) the folder.
export function folderPathNames(folders: MailFolder[], folderId: string): string[] {
  const byId = new Map(folders.map((f) => [f.folder_id, f]));
  const names: string[] = [];
  const seen = new Set<string>();
  let cursor = byId.get(folderId);
  while (cursor && !seen.has(cursor.folder_id)) {
    seen.add(cursor.folder_id);
    names.unshift(cursor.name.trim());
    cursor = cursor.parent_folder_id ? byId.get(cursor.parent_folder_id) : undefined;
  }
  return names;
}

export function folderPathLabel(folders: MailFolder[], folderId: string): string {
  return folderPathNames(folders, folderId).join(" / ");
}

// Keep the folders in `keep` plus all of their ancestors (so a nested
// folder with mail never appears without its parent chain).
export function withAncestors(folders: MailFolder[], keep: (f: MailFolder) => boolean): MailFolder[] {
  const byId = new Map(folders.map((f) => [f.folder_id, f]));
  const result = new Set<string>();
  for (const f of folders) {
    if (!keep(f)) continue;
    let cursor: MailFolder | undefined = f;
    while (cursor && !result.has(cursor.folder_id)) {
      result.add(cursor.folder_id);
      cursor = cursor.parent_folder_id ? byId.get(cursor.parent_folder_id) : undefined;
    }
  }
  return folders.filter((f) => result.has(f.folder_id));
}

// Depth-first rows to render, honouring which folders are expanded.
export function flattenVisible(tree: FolderNode[], expanded: ReadonlySet<string>): FolderNode[] {
  const out: FolderNode[] = [];
  const walk = (nodes: FolderNode[]) => {
    for (const node of nodes) {
      out.push(node);
      if (node.children.length > 0 && expanded.has(node.folder.folder_id)) walk(node.children);
    }
  };
  walk(tree);
  return out;
}

// Ancestor ids of a folder (nearest last), used to auto-expand the
// path to the active folder.
export function ancestorIds(folders: MailFolder[], folderId: string): string[] {
  const names = new Map(folders.map((f) => [f.folder_id, f]));
  const out: string[] = [];
  const seen = new Set<string>([folderId]);
  let cursor = names.get(folderId);
  while (cursor?.parent_folder_id && !seen.has(cursor.parent_folder_id)) {
    seen.add(cursor.parent_folder_id);
    out.unshift(cursor.parent_folder_id);
    cursor = names.get(cursor.parent_folder_id);
  }
  return out;
}
