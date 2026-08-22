# recipient_merge.py
#
# Shared, pure recipient-merging/deduplication helpers reused by every
# service method that resolves a Distribution List into real
# recipients — forward_to_internal_user, add_reply,
# add_interaction_reply, compose_email, add_internal_note. Kept in one
# small module rather than duplicated per call site, and unit-testable
# independent of the DB.

from uuid import UUID

from app.ticketing.repositories.distribution_list_repository import (
    DistributionListRepository,
)


def dedupe_emails_case_insensitive(*groups: list[str]) -> list[str]:
    """
    Flat, order-preserving, case-insensitive-by-address dedup across
    any number of address lists. The first-seen casing of a given
    address wins.
    """

    seen: set[str] = set()
    result: list[str] = []
    for group in groups:
        for address in group:
            key = address.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            result.append(address)
    return result


def remove_addresses_case_insensitive(candidates: list[str], exclude: list[str]) -> list[str]:
    """Case-insensitive set-difference, order-preserving on `candidates`."""

    exclude_keys = {a.strip().lower() for a in exclude}
    return [a for a in candidates if a.strip().lower() not in exclude_keys]


def merge_recipients_with_priority(
    *, to: list[str], cc: list[str], bcc: list[str]
) -> tuple[list[str], list[str], list[str]]:
    """
    Cross-bucket, case-insensitive dedup for the To/Cc/Bcc shape Reply/
    Ticket Reply/Compose all share. Each bucket is first self-deduped,
    then priority To > Cc > Bcc is applied: an address already in `to`
    is dropped from `cc`/`bcc`; one already in the (already-deduped)
    `cc` is dropped from `bcc`. Nothing is ever added *into* Bcc — this
    only ever removes a lower-priority duplicate, so a Distribution
    List member who is also deliberately Bcc'd never gets silently
    promoted into the visible Cc header (a real confidentiality break,
    not just a redundant send).
    """

    effective_to = dedupe_emails_case_insensitive(to)
    effective_cc = remove_addresses_case_insensitive(
        dedupe_emails_case_insensitive(cc), effective_to
    )
    effective_bcc = remove_addresses_case_insensitive(
        dedupe_emails_case_insensitive(bcc), effective_to + effective_cc
    )
    return effective_to, effective_cc, effective_bcc


async def resolve_distribution_list_emails(
    repository: DistributionListRepository | None,
    distribution_list_ids: list[UUID],
) -> list[str]:
    """
    Flattens every active member's active email across the given
    Distribution Lists into one not-yet-deduped list. Returns `[]` for
    an empty/stale/deactivated list, or if `repository` wasn't wired —
    never raises, matching the existing "fewer/zero recipients,
    warn-don't-crash" precedent already established for Rules'
    employee_user_ids. Callers are responsible for their own final
    dedup (dedupe_emails_case_insensitive / merge_recipients_with_priority).
    """

    if repository is None or not distribution_list_ids:
        return []

    by_list = await repository.get_active_member_emails_by_list_ids(distribution_list_ids)
    return [email for members in by_list.values() for email in members.values()]


async def resolve_distribution_list_members(
    repository: DistributionListRepository | None,
    distribution_list_ids: list[UUID],
) -> dict[UUID, str]:
    """
    Same resolution as resolve_distribution_list_emails, but keyed by
    user_id (email as the value) instead of flattened to a bare email
    list — used where the caller needs the real user_id too (Internal
    Note's recipient_user_ids union, Rules' employee_user_ids union).
    """

    if repository is None or not distribution_list_ids:
        return {}

    by_list = await repository.get_active_member_emails_by_list_ids(distribution_list_ids)
    merged: dict[UUID, str] = {}
    for members in by_list.values():
        merged.update(members)
    return merged
