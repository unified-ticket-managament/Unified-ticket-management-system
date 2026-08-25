import type { CategoryResponse, ClientResponse } from "@tw/types";

// Shared by every "Clients" filter in the app (the Mail Inbox inline
// dropdown and the common ClientFilterSelect component) so the option
// set and the selected-value resolution stay identical everywhere:
// active clients, plus categories that have a configured inbox
// mailbox — a category with no real mailbox has nothing for a caller
// to filter by, so it's excluded rather than shown as a dead option.

export function mergedClientFilterOptions(
  clients: ClientResponse[],
  categories: CategoryResponse[]
): { activeClients: ClientResponse[]; categoryOptions: CategoryResponse[] } {
  const activeClients = clients.filter((c) => c.is_active);
  const seenNames = new Set(activeClients.map((c) => c.name.trim().toLowerCase()));
  const categoryOptions = categories.filter((c) => {
    const email = c.inbox_email?.trim();
    return !!email && !seenNames.has(c.category_name.trim().toLowerCase());
  });
  return { activeClients, categoryOptions };
}

// Resolves a Clients-dropdown selection into whichever of the two
// underlying identifiers it actually is — a real client id, or a
// category name (the same identifier the backend's category filters
// already match against). Safe against `mergedClientFilterOptions`'s
// own dedupe: a category dropped there for colliding with an active
// client's display name can never be the selected value in the first
// place, since no such option is ever rendered.
export function resolveClientFilterValue(
  value: string,
  categories: CategoryResponse[]
): { clientId: string | undefined; categoryName: string | undefined } {
  if (value === "ALL") return { clientId: undefined, categoryName: undefined };
  const isCategory = categories.some(
    (c) => c.category_name === value && !!c.inbox_email?.trim()
  );
  return isCategory
    ? { clientId: undefined, categoryName: value }
    : { clientId: value, categoryName: undefined };
}
