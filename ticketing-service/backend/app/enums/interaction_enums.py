from enum import Enum

#interaction_enums.py
class InteractionStatus(str, Enum):
    """
    Processing status of an interaction.
    """

    PENDING = "PENDING"
    ASSIGNED = "ASSIGNED"
    IGNORED = "IGNORED"


class InteractionDirection(str, Enum):
    """
    Direction of communication.
    """

    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"
    INTERNAL = "INTERNAL"