"""
Tests for app/models/referral_state.py -- the referral status state machine.

Pure unit tests: no database, no app startup, no HTTP client. This proves the
transition table in isolation, ahead of D2-S7 wiring it into the
PATCH /referrals/{referral_id}/status route.
"""
import itertools

import pytest

from app.models.referral_state import (
    ALLOWED_TRANSITIONS,
    COMPLETED_STATES,
    TERMINAL_STATES,
    TRANSITION_REQUIRED_FIELDS,
    InvalidTransition,
    ReferralState,
    RefusalReason,
    assert_transition_allowed,
)

ALL_STATES = list(ReferralState)

EXPECTED_ALLOWED_TRANSITIONS = {
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
    ReferralState.CLOSED: set(),
    ReferralState.CANCELLED: set(),
}

EXPECTED_TERMINAL_STATES = {ReferralState.CLOSED, ReferralState.CANCELLED}

EXPECTED_COMPLETED_STATES = {
    ReferralState.ARRIVED,
    ReferralState.CONSULTED,
    ReferralState.BACK_REFERRED,
    ReferralState.CLOSED,
}

EXPECTED_TRANSITION_REQUIRED_FIELDS = {
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


def test_exactly_13_states():
    assert len(ALL_STATES) == 13
    assert len({s.value for s in ALL_STATES}) == 13


def test_allowed_transitions_match_spec_exactly():
    assert ALLOWED_TRANSITIONS == EXPECTED_ALLOWED_TRANSITIONS
    # every state has an entry, no extra/missing keys
    assert set(ALLOWED_TRANSITIONS.keys()) == set(ReferralState)


def test_terminal_states_match_spec_exactly():
    assert TERMINAL_STATES == EXPECTED_TERMINAL_STATES


def test_completed_states_match_spec_exactly():
    assert COMPLETED_STATES == EXPECTED_COMPLETED_STATES


def test_transition_required_fields_match_spec_exactly():
    assert TRANSITION_REQUIRED_FIELDS == EXPECTED_TRANSITION_REQUIRED_FIELDS
    # every state except INITIATED (never a destination) has an entry;
    # no extra/missing keys.
    expected_keys = set(ReferralState) - {ReferralState.INITIATED}
    assert set(TRANSITION_REQUIRED_FIELDS.keys()) == expected_keys


def test_refusal_reason_matches_spec_exactly():
    expected = {
        "COST",
        "DISTANCE",
        "FAMILY_DECIDED_AGAINST",
        "ALREADY_RECOVERED",
        "WENT_PRIVATE",
        "COULD_NOT_BE_CONTACTED",
        "OTHER",
    }
    assert {r.value for r in RefusalReason} == expected


def _build_matrix_cases():
    """All 13 x 13 = 169 (from, to) pairs, with the expected outcome derived
    from ALLOWED_TRANSITIONS/TERMINAL_STATES rather than hand-enumerated."""
    cases = []
    for current, requested in itertools.product(ALL_STATES, ALL_STATES):
        if current in TERMINAL_STATES:
            should_be_allowed = False
        else:
            should_be_allowed = requested in ALLOWED_TRANSITIONS.get(current, set())
        cases.append(
            pytest.param(
                current,
                requested,
                should_be_allowed,
                id=f"{current.value}->{requested.value}",
            )
        )
    return cases


MATRIX_CASES = _build_matrix_cases()


def test_matrix_has_169_cases():
    assert len(MATRIX_CASES) == 13 * 13 == 169


@pytest.mark.parametrize("current,requested,should_be_allowed", MATRIX_CASES)
def test_transition_matrix(current, requested, should_be_allowed):
    if should_be_allowed:
        assert_transition_allowed(current, requested)  # must not raise
    else:
        with pytest.raises(InvalidTransition) as exc_info:
            assert_transition_allowed(current, requested)
        err = exc_info.value
        assert err.current == current
        assert err.requested == requested
        if current in TERMINAL_STATES:
            assert err.allowed == set()
        else:
            assert err.allowed == ALLOWED_TRANSITIONS.get(current, set())


def test_initiated_to_closed_raises_with_correct_allowed_set():
    with pytest.raises(InvalidTransition) as exc_info:
        assert_transition_allowed(ReferralState.INITIATED, ReferralState.CLOSED)
    err = exc_info.value
    assert err.current == ReferralState.INITIATED
    assert err.requested == ReferralState.CLOSED
    assert err.allowed == {
        ReferralState.SLOT_BOOKED,
        ReferralState.TRANSPORT_ARRANGED,
        ReferralState.NOT_ARRIVED,
        ReferralState.CANCELLED,
    }


@pytest.mark.parametrize("requested", ALL_STATES)
def test_terminal_state_closed_permits_no_further_transition(requested):
    with pytest.raises(InvalidTransition) as exc_info:
        assert_transition_allowed(ReferralState.CLOSED, requested)
    assert exc_info.value.allowed == set()


@pytest.mark.parametrize("requested", ALL_STATES)
def test_terminal_state_cancelled_permits_no_further_transition(requested):
    with pytest.raises(InvalidTransition) as exc_info:
        assert_transition_allowed(ReferralState.CANCELLED, requested)
    assert exc_info.value.allowed == set()
