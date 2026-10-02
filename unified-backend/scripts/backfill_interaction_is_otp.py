# backfill_interaction_is_otp.py
#
# One-off backfill for Interaction.is_otp (the Mail "OTPs" section).
# Rows created before that column existed default to False, so any OTP
# that arrived earlier still sits in the Inbox. This reruns the SAME
# existing classifier EmailService.receive_email uses
# (otp_classifier.classify_otp_email, at the configured
# otp_nlp_confidence_threshold) over historical inbound EMAIL rows,
# using the subject/body stored in their payload, exactly the inputs
# receive_email passed it.
#
# DRY RUN BY DEFAULT — it only reads and reports counts. Nothing is
# written unless --apply is passed. The dry run only selects columns
# that predate is_otp, so it also works before the migration is applied.
#
# Never prints subjects, bodies or codes — counts only.
#
# Idempotent: --apply only flips False -> True on rows the classifier
# flags, and never touches a row that's already True.
#
# Usage (from unified-backend/, with the venv active):
#   python -m scripts.backfill_interaction_is_otp                # dry run
#   python -m scripts.backfill_interaction_is_otp --apply        # write
#   python -m scripts.backfill_interaction_is_otp --apply --limit 5000

import argparse
import asyncio

from sqlalchemy import select, update

from app.core.config import get_settings
from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import InteractionDirection
from app.ticketing.models.interaction import Interaction
from app.ticketing.services.otp_classifier import classify_otp_email

BATCH_SIZE = 500


async def run(*, apply: bool, limit: int | None) -> None:
    threshold = get_settings().otp_nlp_confidence_threshold

    scanned = 0
    flagged_roots = 0
    flagged_replies = 0
    updated = 0
    last_id = None

    async with AsyncSessionLocal() as session:
        while limit is None or scanned < limit:
            batch_size = BATCH_SIZE if limit is None else min(BATCH_SIZE, limit - scanned)
            query = (
                select(
                    Interaction.interaction_id,
                    Interaction.parent_interaction_id,
                    Interaction.payload,
                )
                .where(
                    Interaction.interaction_type == "EMAIL",
                    Interaction.direction == InteractionDirection.INBOUND,
                    Interaction.is_bounce.is_(False),
                )
                .order_by(Interaction.interaction_id)
                .limit(batch_size)
            )
            if last_id is not None:
                query = query.where(Interaction.interaction_id > last_id)

            rows = (await session.execute(query)).all()
            if not rows:
                break

            otp_ids = []
            for interaction_id, parent_interaction_id, payload in rows:
                payload = payload if isinstance(payload, dict) else {}
                result = classify_otp_email(
                    payload.get("subject"), payload.get("body"), threshold=threshold
                )
                if result.is_otp:
                    otp_ids.append(interaction_id)
                    if parent_interaction_id is None:
                        flagged_roots += 1
                    else:
                        flagged_replies += 1

            if apply and otp_ids:
                result = await session.execute(
                    update(Interaction)
                    .where(
                        Interaction.interaction_id.in_(otp_ids),
                        Interaction.is_otp.is_(False),
                    )
                    .values(is_otp=True)
                )
                await session.commit()
                updated += result.rowcount or 0

            scanned += len(rows)
            last_id = rows[-1][0]

    await engine.dispose()

    print(f"Mode: {'APPLY' if apply else 'DRY RUN (nothing written)'}")
    print(f"Threshold: {threshold}")
    print(f"Inbound EMAIL interactions scanned: {scanned}")
    print(f"Classified as OTP - thread roots (move to OTPs section): {flagged_roots}")
    print(f"Classified as OTP - threaded replies (stay inside their thread): {flagged_replies}")
    if apply:
        print(f"Rows updated to is_otp=true: {updated}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write is_otp=true (default: dry run).")
    parser.add_argument("--limit", type=int, default=None, help="Scan at most this many rows.")
    args = parser.parse_args()
    asyncio.run(run(apply=args.apply, limit=args.limit))


if __name__ == "__main__":
    main()
