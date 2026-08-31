"""
Referral status state machine.

Pure logic module: no DB session, no HTTP, no SQLModel table. This is the
in-memory rulebook for what referral status transitions are permitted, what
fields a transition requires, and the guard function routes will call before
persisting a status change.

D2-S7 (a later step) wires `assert_transition_allowed` and
`TRANSITION_REQUIRED_FIELDS` into `PATCH /referrals/{referral_id}/status`.
This step only creates the module and proves it in isolation with
tests/test_referral_transitions.py -- no route or migration changes here.

Style follows app/models/enums.py: str Enum members, values equal to names.
"""
from enum import Enum


class ReferralState(str, Enum):
    INITIATED = "INITIATED"
    SLOT_BOOKED = "SLOT_BOOKED"
    TRANSPORT_ARRANGED = "TRANSPORT_ARRANGED"
    ARRIVED = "ARRIVED"
    CONSULTED = "CONSULTED"
    BACK_REFERRED = "BACK_REFERRED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    NOT_ARRIVED = "NOT_ARRIVED"
    TRACED = "TRACED"
    RESCHEDULED = "RESCHEDULED"
    REFUSED = "REFUSED"
    LOST = "LOST"


ALLOWED_TRANSITIONS: dict[ReferralState, set[ReferralState]] = {
    ReferralState.INITIATED: {
        ReferralState.SLOT_BOOKED,
        ReferralState.TRANSPORT_ARRANGED,
        ReferralState.NOT_ARRIVED,
        ReferralState.CANCELLED,
    },
    ReferralState.SLOT_BOOKED: {
        ReferralState.TRANSPORT_ARRANGED,
        ReferralState.ARRIVED,
        ReferralState.NOT_ARRIVED,
        ReferralState.CANCELLED,
    },
    ReferralState.TRANSPORT_ARRANGED: {
        ReferralState.ARRIVED,
        ReferralState.NOT_ARRIVED,
        ReferralState.CANCELLED,
    },
    ReferralState.ARRIVED: {
        ReferralState.CONSULTED,
        ReferralState.CANCELLED,
    },
    ReferralState.CONSULTED: {
        ReferralState.BACK_REFERRED,
        ReferralState.CLOSED,
    },
    ReferralState.BACK_REFERRED: {
        ReferralState.CLOSED,
    },
    ReferralState.NOT_ARRIVED: {
        ReferralState.TRACED,
        ReferralState.LOST,
    },
    ReferralState.TRACED: {
        ReferralState.RESCHEDULED,
        ReferralState.REFUSED,
        ReferralState.LOST,
    },
    ReferralState.RESCHEDULED: {
        ReferralState.SLOT_BOOKED,
        ReferralState.TRANSPORT_ARRANGED,
        ReferralState.CANCELLED,
    },
    ReferralState.REFUSED: {
        ReferralState.CLOSED,
    },
    ReferralState.LOST: {
        ReferralState.CLOSED,
    },
    ReferralState.CLOSED: set(),  # terminal
    ReferralState.CANCELLED: set(),  # terminal
}

TERMINAL_STATES: set[ReferralState] = {
    ReferralState.CLOSED,
    ReferralState.CANCELLED,
}

COMPLETED_STATES: set[ReferralState] = {
    ReferralState.ARRIVED,
    ReferralState.CONSULTED,
    ReferralState.BACK_REFERRED,
    ReferralState.CLOSED,
}


class InvalidTransition(Exception):
    """Raised when a requested referral status transition is not permitted.

    Fail-closed: any transition not explicitly present in ALLOWED_TRANSITIONS
    (including any transition out of a terminal state) is rejected.
    """

    def __init__(
        self,
        current: ReferralState,
        requested: ReferralState,
        allowed: set[ReferralState],
    ) -> None:
        self.current = current
        self.requested = requested
        self.allowed = allowed
        super().__init__(
            f"Cannot transition referral from {current} to {requested}; "
            f"allowed next states: {sorted(s.value for s in allowed)}"
        )


def assert_transition_allowed(
    current: ReferralState, requested: ReferralState
) -> None:
    """Raise InvalidTransition unless `requested` is a permitted next state
    from `current`. Terminal states permit no further transition at all."""
    if current in TERMINAL_STATES:
        raise InvalidTransition(current, requested, set())
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if requested not in allowed:
        raise InvalidTransition(current, requested, allowed)


# Required-field map, consumed by the route in D2-S7 (not this step).
# Values are lists of field names the route must have present/non-null before
# allowing the transition into that state. "arrival_confirmed_by OR
# arrival_scan_ref" is a single logical requirement satisfied by either field
# (kept as one string entry per the spec, not two separate field names).
TRANSITION_REQUIRED_FIELDS: dict[ReferralState, list[str]] = {
    ReferralState.SLOT_BOOKED: ["slot_datetime", "destination_org_unit_id"],
    ReferralState.TRANSPORT_ARRANGED: ["transport_mode"],
    ReferralState.ARRIVED: ["arrival_confirmed_by OR arrival_scan_ref"],
    ReferralState.CONSULTED: ["consulted_by_user_id"],
    ReferralState.BACK_REFERRED: ["back_referral_note"],
    ReferralState.NOT_ARRIVED: [],
    ReferralState.TRACED: ["traced_by_user_id"],
    ReferralState.REFUSED: ["refusal_reason"],
    ReferralState.LOST: ["loss_reason"],
    ReferralState.CANCELLED: ["cancellation_reason"],
    ReferralState.RESCHEDULED: [],
    ReferralState.CLOSED: [],
}
# INITIATED is the initial state (never a transition target), so it
# intentionally has no entry in TRANSITION_REQUIRED_FIELDS -- consistent with
# every other key being a possible *destination* state.


class RefusalReason(str, Enum):
    COST = "COST"
    DISTANCE = "DISTANCE"
    FAMILY_DECIDED_AGAINST = "FAMILY_DECIDED_AGAINST"
    ALREADY_RECOVERED = "ALREADY_RECOVERED"
    WENT_PRIVATE = "WENT_PRIVATE"
    COULD_NOT_BE_CONTACTED = "COULD_NOT_BE_CONTACTED"
    OTHER = "OTHER"
