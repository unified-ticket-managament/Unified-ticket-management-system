# ADR-003: One `Interaction` Model for Every Communication Type

**Status**: Accepted (implemented, in production use)

## Context

A ticket's history includes many kinds of events: an inbound client email, an agent's reply, an internal note, a forward, a status change record. Each has different fields relevant to it (a note has no "To" recipients in the email sense; a reply has envelope headers a note doesn't).

## Problem

Should each communication type get its own table, or should they share one model?

## Options Considered

1. **A separate table per type** (`emails`, `replies`, `notes`, `forwards`) — type-safe columns, but requires querying/joining N tables to build one unified Timeline.
2. **One `Interaction` table**, differentiated by an `interaction_type` string column and a flexible `payload` JSONB field for type-specific data.

## Decision

One `Interaction` table (option 2).

## Reason

The Timeline, Mail/Inbox view, and System Mail are all fundamentally "one activity, several representations" of the same underlying event stream — a design principle explicitly confirmed in this codebase's own history (the Internal Note Recipients feature, 2026-08-11, was built specifically against this principle: "the same one row that already backs the Timeline, Interaction history, and System Mail"). A single table with a flexible payload lets every one of these views query the same source without N-way joins or type-specific union queries.

## Trade-offs

- **Cost**: `interaction_type` is a plain string, not a Postgres-native enum — chosen deliberately for flexibility (new types don't need a migration), at the cost of losing database-level validation that the value is one of a known set.
- **Cost**: `payload` (JSONB) has no schema enforcement at the database level — a bug writing malformed payload data wouldn't be caught until read time.
- **Benefit**: threading (`parent_interaction_id`), visibility (`is_visible`), and claim tracking (`claimed_by`/`claimed_at`) all apply uniformly across every interaction type, since they're columns on the one shared table rather than duplicated per-type logic.
- **Benefit**: `trim_payload_for_list` (the payload-trimming helper backing the two list endpoints) can apply type-specific trimming logic in one place, keyed on `interaction_type` — a single, findable function rather than N table-specific serializers.

## Consequences

Adding a new interaction-relevant field (e.g. the Internal Note feature's `recipient_user_ids`/`recipient_names`) means adding keys to the JSONB payload and updating every consumer that reads/trims that payload — a real, confirmed source of bugs when one consumer (the list-trimming helper) was missed during that exact feature's rollout.

## Related Components

`app/ticketing/models/interaction.py`, `app/ticketing/services/interaction_summary.py` (`trim_payload_for_list`), `app/ticketing/services/interaction_service.py`.
