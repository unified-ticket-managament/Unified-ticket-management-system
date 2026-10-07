// Display order for the Mail reading pane: newest reply first. The API
// (InteractionRepository.list_thread) returns replies oldest-first by
// created_at and other consumers depend on that, so the reversal happens
// here, for this one view, without mutating the response.
//
// Sorts by created_at — the field the backend orders by and the pane shows
// for each reply. Ties keep the API's order reversed (later row = newer).
// The root message is not part of `replies`; the caller renders it last.
export function newestFirst<T extends { created_at: string }>(replies: readonly T[]): T[] {
  return replies
    .map((reply, index) => ({ reply, index, time: Date.parse(reply.created_at) }))
    .sort((a, b) => {
      const diff = (Number.isNaN(b.time) ? 0 : b.time) - (Number.isNaN(a.time) ? 0 : a.time);
      return diff !== 0 ? diff : b.index - a.index;
    })
    .map(({ reply }) => reply);
}
