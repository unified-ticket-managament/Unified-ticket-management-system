# interaction_summary.py

from typing import Any

from app.ticketing.models.interaction import Interaction


def trim_payload_for_list(interaction: Interaction) -> dict[str, Any]:
    """
    Keeps only the handful of payload keys the frontend's
    lib/interactionMeta.ts::summarize() actually reads for this
    interaction_type, dropping everything else (html_body, the full
    outbound envelope, cc/bcc, in_reply_to/references, untruncated
    body text). Used only by the two cross-cutting *list* endpoints
    (GET /tickets/interactions, GET /tickets/{id}/interactions) —
    every single-row/thread-detail endpoint keeps returning the full
    payload unchanged, since that's the one place it's actually
    rendered in full.
    """

    payload = interaction.payload or {}

    match interaction.interaction_type:
        case "EMAIL":
            return {"subject": payload.get("subject")}
        case "REPLY":
            return {"message": (payload.get("message") or "")[:200]}
        case "INTERNAL_NOTE":
            return {"note": (payload.get("note") or "")[:200]}
        case "STATUS_CHANGE" | "PRIORITY_CHANGE":
            return {"from": payload.get("from"), "to": payload.get("to")}
        case "RESOLVED":
            return {"resolution_note": payload.get("resolution_note")}
        case "ATTACHMENT":
            return {"file_count": payload.get("file_count")}
        case "AGENT_TRANSFER":
            return {
                "from_agent_name": payload.get("from_agent_name"),
                "to_agent_name": payload.get("to_agent_name"),
            }
        case "CLAIM":
            return {"agent_name": payload.get("agent_name")}
        case "EDIT_ACCESS_REQUESTED":
            return {"reason": payload.get("reason")}
        case "EDIT_ACCESS_REJECTED":
            return {"review_note": payload.get("review_note")}
        case "EDIT_ACCESS_APPROVED":
            # summarize() renders a fixed "Edit access approved" string
            # regardless of payload — no keys needed.
            return {}
        case _:
            # Genuinely unrecognized type — fall back to the full dict
            # rather than risk silently hiding real data.
            return payload
