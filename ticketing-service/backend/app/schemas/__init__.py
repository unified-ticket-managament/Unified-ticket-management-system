from .ticket import (
    TicketCreate,
    TicketUpdate,
    TicketResponse,
)

from .interaction import (
    InteractionCreate,
    InteractionUpdate,
    InteractionResponse,
)

from .attachment import (
    AttachmentCreate,
    AttachmentResponse,
)

from .attach_interaction import (
    AttachInteractionRequest,
    AttachInteractionResponse,
)

from .note import (
    InternalNoteCreate,
    InternalNoteResponse,
)

__all__ = [
    # Ticket Schemas
    "TicketCreate",
    "TicketUpdate",
    "TicketResponse",

    # Interaction Schemas
    "InteractionCreate",
    "InteractionUpdate",
    "InteractionResponse",

    # Attachment Schemas
    "AttachmentCreate",
    "AttachmentResponse",

    # Attach Existing Interaction Schemas
    "AttachInteractionRequest",
    "AttachInteractionResponse",

    # Internal Note Schemas
    "InternalNoteCreate",
    "InternalNoteResponse",
]