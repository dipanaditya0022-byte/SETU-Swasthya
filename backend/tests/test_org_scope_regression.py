"""T18 / Day1.md SS4.2's own regression warning: `/UP/KANPUR` must not
match the prefix of `/UP/KANPUR2`. This is the exact bug
org_unit_is_within_scope's `target_path.startswith(actor_path.rstrip("/")
+ "/")` construction (not a bare startswith) exists to prevent -- see
app/core/authz.py's own docstring for the trailing-slash reasoning.

Tested at two levels: directly against org_unit_is_within_scope (unit
level, no HTTP), and end to end through a real POST /users call (a
Kanpur Nagar BMO must not be able to create staff in a same-named-
prefix "Kanpur Nagar 2" block) -- the second is what actually proves
the app, not just the helper function, is safe.
"""
from sqlmodel import text

from app.core.authz import org_unit_is_within_scope
from tests._fixtures import auth_header, registration_body


def _make_unit(db, unit_type, name, parent_id=None):
    row = db.exec(text(
        "INSERT INTO org_units (unit_type, name, parent_id) VALUES (:t, :n, :p) RETURNING id"
    ), params={"t": unit_type, "n": name, "p": str(parent_id) if parent_id else None}).first()
    return row[0]


def test_prefix_collision_unit_level(db):
    state = _make_unit(db, "STATE", "UP")
    kanpur = _make_unit(db, "DISTRICT", "Kanpur", state)  # path: /up/kanpur
    kanpur2 = _make_unit(db, "DISTRICT", "Kanpur2", state)  # path: /up/kanpur2 -- sibling, NOT a child
    db.commit()

    kanpur_path = db.exec(text("SELECT path FROM org_units WHERE id = :id"), params={"id": str(kanpur)}).first()[0]
    kanpur2_path = db.exec(text("SELECT path FROM org_units WHERE id = :id"), params={"id": str(kanpur2)}).first()[0]
    assert kanpur_path != kanpur2_path
    assert kanpur2_path.startswith(kanpur_path), (
        "fixture sanity: this test only proves anything if the string-prefix collision genuinely exists"
    )

    # An actor scoped to Kanpur must NOT be considered within-scope of Kanpur2.
    assert org_unit_is_within_scope(db, kanpur2, kanpur) is False
    # But Kanpur2 is within its own scope, and Kanpur is within its own scope.
    assert org_unit_is_within_scope(db, kanpur2, kanpur2) is True
    assert org_unit_is_within_scope(db, kanpur, kanpur) is True


def test_prefix_collision_end_to_end(client, db, make_actor):
    state = _make_unit(db, "STATE", "UP")
    kanpur = _make_unit(db, "DISTRICT", "Kanpur", state)
    kanpur2 = _make_unit(db, "DISTRICT", "Kanpur2", state)
    kanpur2_block = _make_unit(db, "BLOCK", "Some Block", kanpur2)
    db.commit()

    # BMO's own posting type is BLOCK per role_creation_grants, but for
    # this regression what matters is DISTRICT-level scope collision --
    # use a COLLECTOR (posted at DISTRICT, per STATE_NHM/SUPERUSER's own
    # grant) attempting to create a BMO inside Kanpur2's block while
    # scoped to (plain) Kanpur.
    _, token = make_actor("COLLECTOR", kanpur)
    body = registration_body("BMO", kanpur2_block)
    resp = client.post("/users", headers=auth_header(token), json=body)
    assert resp.status_code == 403, (
        f"Kanpur-scoped COLLECTOR must not reach into Kanpur2's block -> got {resp.status_code}: {resp.text}"
    )
    assert resp.json()["detail"]["code"] == "OUT_OF_SCOPE"
