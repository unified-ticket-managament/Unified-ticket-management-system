from enum import Enum

#sla_enums.py
class SLAClockStatus(str, Enum):
    """
    Lifecycle of an SLA clock. First Response clocks only ever use
    PENDING/COMPLETED; Resolution clocks use all four (RUNNING/PAUSED
    repeat any number of times before a final COMPLETED). Shared
    across both clock tables rather than split into two enums/Postgres
    types, since SQLEnum doesn't restrict a column to a subset of an
    enum's members anyway.
    """

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
