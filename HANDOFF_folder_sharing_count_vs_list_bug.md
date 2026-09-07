# Handoff: Folder-sharing count/list discrepancy bug

**Start here.** This is a self-contained handoff for a fresh Claude Code session. Paste this whole file as your first message (or tell Claude to read it) in the new panel, opened at the repo root `C:\Users\vishnu\cloned-project\Unified-ticket-management-system`.

## What this is NOT

This is a **new, separate bug**, unrelated to the larger delegated-access feature work that was just finished in the prior session (Rule-forwarding creating a real Interaction row, folder-share/forward-recipient reply access, `communication:move_to_folder`, `rule:manage_all`, etc.). That work is **fully implemented, tested, and sitting uncommitted in the working tree** — do not revert, redo, or "clean up" it. See "Prior session state" below before touching anything.

## The bug, reproduced live

Screenshot evidence (impersonating **Rajendra Prasad M**, Team Lead): Kamal(esh) created a Rule — when mail arrives from client "MMC," file it into a folder ("faa") and share that folder with Rajendra (Team Lead) and some Staff.

- The **sidebar** shows the "faa" folder with badge count **4** (a real, non-zero number).
- Clicking into the folder shows **"faa (0)"** and **"No Messages — This folder is empty."**

Same folder, same user, two different UI elements disagreeing about whether there's anything in it.

## Why this matters / what it isn't

Confirmed via direct code reading (not guessed): this is **not** a frontend bug. `useMailInbox.ts`'s `fetchFolderRows` hardcodes `view: "all"` whenever a folder is selected — it does NOT send the default `view: "pending"`, so the leading hypothesis going in ("view=pending conflicts with folder_id because of the new folder_id IS NULL exclusion added to the pending-view filter") was checked and **ruled out**.

Confirmed via `git blame`-equivalent reasoning: this is **not** caused by anything in the prior session's changes. None of the 8 modified files or 3 new files touch `InboxService`, `_resolve_scope`, `list_inbox`, `count_by_folder`, `resolve_folder_access`, or any folder-sharing/list code at all. Full list of what *was* touched is in "Prior session state" below, for elimination purposes.

## The actual mechanism — two different code paths that are supposed to agree

**Path 1 — the sidebar badge** (`GET /folder-counts`):
- Route: `unified-backend/app/ticketing/api/inbox.py:242-288` (`get_folder_counts`)
- Computes `shared_folder_ids` directly via `rule_access.has_folder_share_access` (line 279) for every folder, independent of the viewer's normal ownership scope
- Calls `InboxService.get_folder_counts` (`unified-backend/app/ticketing/services/inbox_service.py:601-640`), which calls `self._resolve_scope(current_user)` **with no bypass override at all** (line 628-630 — just the plain call, no `bypass_ownership_scope` kwarg)
- Passes `shared_folder_ids` down to `InteractionRepository.count_by_folder` (need to read this method — not yet reviewed in depth), whose own docstring (per `get_folder_counts`'s docstring, `inbox_service.py:615-625`) says shared folders are counted via "a second, **unscoped** query merged with the first, rather than a single OR'd WHERE clause"

**Path 2 — the folder's actual contents** (`GET /inbox?folder_id=<faa>&view=all`):
- Route: `unified-backend/app/ticketing/api/inbox.py:121-239` (`get_inbox`)
- Computes a single boolean, `bypass_ownership_scope = access.via_sharing` (line 208), via `MailFolderService.resolve_folder_access` (`unified-backend/app/ticketing/services/mail_folder_service.py:110-143`)
- Passes that boolean into `InboxService.get_inbox` (`inbox_service.py:280-353`) → `self._resolve_scope(current_user, bypass_ownership_scope=...)` (line 347-353)
- Inside `_resolve_scope` (`inbox_service.py:101` onward — **read the whole thing, not just the part quoted below**): `tier = resolve_communication_visibility_tier(current_user)` is checked **first** (line 176-184, raises 403 if tier=="none" — ruled out as the cause here since the UI shows an empty state, not an error), **then** `if bypass_ownership_scope: pass` (line 194-199, nulls out all five scope variables) **before** any role-specific branch
- The resulting (all-None) scope tuple feeds `InteractionRepository.list_inbox` (`unified-backend/app/ticketing/repositories/interaction_repository.py:430` onward) along with `folder_id`/`view="all"`

**Both paths ultimately depend on the same underlying rule-sharing check** — `has_folder_share_access`/`can_view_rule` in `unified-backend/app/ticketing/services/rule_access.py`. On paper they should agree. They don't, live.

## Ranked hypotheses (untested — this is where you start)

1. **Most likely**: `resolve_folder_access`'s `via_sharing` (Path 2) comes back `False` for this specific rule/user/folder even though `has_folder_share_access` (Path 1, same underlying rule-membership logic) comes back `True`. Look for a subtle difference in how the two call sites resolve distribution-list membership, rule enablement, or folder-name matching — `resolve_folder_access` (`mail_folder_service.py:110-143`) vs. the route handler's direct `has_folder_share_access` call (`api/inbox.py:279`). Re-read both side by side, character by character.
2. `bypass_ownership_scope` really is `True` in both, `_resolve_scope` really does null out all five variables correctly in both call sites — but `list_inbox`'s actual SQL (`interaction_repository.py:430` onward) has some *other* filter (not one of the five nulled scope variables) that still excludes these rows in `view="all"` mode, which `count_by_folder`'s separate unscoped merge query doesn't apply. Read `list_inbox`'s full WHERE-clause construction for `view=="all"` and compare against `count_by_folder`'s shared-folder branch line by line.
3. Data-level: check what's actually in the `rules` table for this rule's `shared_user_ids` column, and confirm Rajendra's real `user_id` is actually in there (not e.g. only a Distribution List he isn't an active member of, or a stale/wrong id). This is a 2-minute DB check that would immediately confirm or rule out hypothesis 1's root cause vs. a pure code bug.

## Concrete next steps, in order

1. Read `InteractionRepository.count_by_folder` and `InteractionRepository.list_inbox` in full — neither was read in depth in the prior session; this is very likely where the actual divergence lives given hypothesis 2.
2. Add temporary debug logging (or a quick isolated pytest against a real seeded rule/user) comparing `MailFolderService.resolve_folder_access(...).via_sharing` vs `rule_access.has_folder_share_access(...)` for the exact same folder + the exact same user object, in the same process — they should be trivially provably equal or not.
3. If they disagree, the bug is in `resolve_folder_access`/its inputs. If they agree (both True), the bug is downstream in `list_inbox` vs `count_by_folder`'s actual SQL.
4. Note in the code: `get_folder_counts`'s own docstring (`inbox_service.py:251-263`, verbatim: *"otherwise a shared folder would show a real folder in the sidebar... but a misleading 0 count here, the exact bug this whole fix addresses"*) proves **this exact symptom (shared-but-shows-0) was already found and fixed once before, for the count endpoint specifically**. This strongly suggests the same class of bug now exists in the *list* endpoint instead, and was never fixed there, or regressed since. Worth searching git log/blame for that prior fix's commit to see exactly what it changed and whether the same fix needs mirroring into `get_inbox`/`list_inbox`.
5. Write a regression test once the root cause is found, in the style of `unified-backend/tests/test_rule_access_folder_sharing.py` (pure-logic, no DB) or `unified-backend/tests/test_inbox_ticket_service.py` (real DB, rolled back) — whichever matches where the fix lands.

## Prior session state — do not disturb without reason

**Nothing has been committed.** All of this is uncommitted in the working tree (confirmed via `git status` just before writing this handoff):

Modified: `unified-backend/app/ticketing/services/access_control.py`, `inbox_ticket_service.py`, `interaction_service.py`, `open_email_service.py`, `rule_access.py`, `rule_engine_service.py`, `unified-backend/scripts/rbac_seed/seed.py`, and 4 test files.
New: `unified-backend/app/ticketing/services/forward_access.py`, `unified-backend/tests/test_move_to_folder_permission.py`, `unified-backend/tests/test_view_only_forwarded_recipient_access.py`.

All of it passes its own test suite (64 passed, 0 failed, 4 skipped for an unrelated pre-existing environment reason — see the full plan file for exact numbers). None of it touches the files this new bug lives in.

**Full background**, if you need it (the entire investigation → decisions → implementation history for the delegated-access feature, ~1500 lines, sections A-S plus 6 numbered Decisions plus an Implementation Checklist plus the final report): `C:\Users\vishnu\.claude\plans\agile-wiggling-quasar.md`. You should not need to read all of it to fix this specific bug — the file:line references above should be sufficient — but it's there if you want the "why" behind any of the surrounding code.

**Explicitly deferred, not part of this bug**: Phase 3 (folder-sharing widening *actions* like Reply/Archive once you can already see a shared folder's contents) was investigated and deliberately NOT implemented last session — two real blockers were found (Archive's "permission alone, ownership aside" design conflicts with adding folder-share as an access source; Reply's widening needs a new `rule_repository` dependency threaded into `InteractionService`'s constructor). That's a different, already-scoped piece of separate work — don't conflate it with this visibility bug.
