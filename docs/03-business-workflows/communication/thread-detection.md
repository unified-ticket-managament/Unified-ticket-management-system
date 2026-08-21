# Thread Detection Workflow

## 1. Purpose
Correctly associate an inbound (or outbound) email with its conversation history, so SLA clocks, ticket association, and the Timeline all resolve to one continuous thread rather than fragmenting into disconnected messages.

## 2. Trigger
Every inbound email (as part of [email-processing.md](email-processing.md)), and every outbound reply/compose.

## 3. Actors
The system (no human actor).

## 4. Preconditions
The email's headers (`Message-ID`, `In-Reply-To`, `References`) are present and well-formed — Graph exposes these via `internetMessageHeaders`, explicitly selected in `MESSAGE_SELECT_FIELDS`.

## 5. High-Level Flow
Extract headers → look up `in_reply_to_message_id`/`references` against stored `interactions.message_id` → resolve to thread root → attach or start new thread.

## 6. Detailed Workflow
1. `interactions.conversation_id`, `in_reply_to_message_id`, and `references` (JSONB) are populated from the inbound message's headers at Interaction-creation time.
2. If `in_reply_to_message_id` (or any id in `references`) matches an existing `interactions.message_id`, the new Interaction's `parent_interaction_id` is set to that thread's root — **always the thread root, never an intermediate reply** — this is the invariant SLA clocks depend on (a clock always lives on the thread root).
3. If no match is found, this Interaction *is* the thread root — a new `FirstResponseSLA` is created against it.

## 7. Business Rules
- **A reply always resolves to the thread root, never to whichever specific message it was replying to** — this is what lets "first agent reply anywhere in the thread" correctly complete the one clock that matters, rather than each reply needing its own bookkeeping.
- Threading works identically whether the ticket exists yet or not — a pending inbox conversation threads the same way a ticketed one does.

## 8. Decision Points
- Match found on `in_reply_to_message_id`/`references` → attach to existing thread.
- No match → new thread root.

## 9. Database Changes
`interactions.parent_interaction_id`, `.conversation_id`, `.in_reply_to_message_id`, `.references` populated on every row.

## 10. APIs Involved
Surfaced via `GET /interactions/{id}/thread`, `GET /tickets/{id}/interactions`, `GET /inbox/{id}`.

## 11. Services / Components Involved
`EmailService`, `InteractionService` (thread-root resolution helper, reused by SLA completion and pending-item action checks alike).

## 12. External Integrations
Depends on Graph exposing `internetMessageHeaders` — confirmed explicitly selected in the Graph fetch.

## 13. Notifications
N/A — threading itself doesn't notify.

## 14. Audit Events
N/A directly.

## 15. Failure Scenarios
A message missing `In-Reply-To`/`References` (e.g. a client starting a "reply" from a forwarded copy in a different mail client) is treated as a new thread root — **not automatically re-linked** to the human-recognizable prior conversation; this is a structural limitation of header-based threading, not a bug.

## 16. Edge Cases
- `test_interaction_threading.py` (`unified-backend/tests/`) specifically covers thread-root resolution and descendant listing — see [11-testing](../../11-testing/README.md).
- A pytest-asyncio test-isolation issue affects this file when run alongside two specific others in the same process — see [16-known-limitations/technical-limitations.md](../../16-known-limitations/technical-limitations.md).

## 17. Postconditions
Every Interaction in a conversation carries a `parent_interaction_id` chain resolving to exactly one thread root.

## 18. Relevant Source Files
- `unified-backend/app/ticketing/models/interaction.py`
- `unified-backend/app/ticketing/services/{email_service,interaction_service}.py`
- `unified-backend/tests/test_interaction_threading.py`

## 19. Example Scenario
A client replies to an agent's reply, three messages deep. The new message's `In-Reply-To` header matches the second message's `message_id`; the system walks that to the *original* thread root (message 1), not message 2 — so the Timeline, the ticket association, and any SLA clock all resolve consistently to the same root regardless of which message in the thread triggered them.
