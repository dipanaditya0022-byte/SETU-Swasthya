"""GET /facilities/ -- lists org_units at facility tiers (PHC/CHC/SDH/
HWC/DISTRICT_HOSPITAL/TELE_HUB).

Frontend-integration gap, found live: the Flutter client's registration/
referral/reports screens all call GET /facilities/ expecting facility
name+type lookups, but no such route existed anywhere in this codebase
(confirmed live as a 404). A standalone `Facility` SQLModel already
exists (app/models/facility.py -- id/name/facility_type/village/
district) but is unrouted, never seeded, and no FK from `patient` or
`referral` points at it. org_units IS what patient.facility_id and
referral.from_facility_id/destination_facility_id actually hold in
every seeded row (see app/api/routes/referrals.py's own docstring:
"destination_org_unit_id ... is mapped onto the existing
destination_facility_id column"), and IS populated by seed_demo.py --
so it's the real backing store here, not that dead table. Confirmed
this choice with the user directly (2026-09-22) rather than guessing
between the two.

Unscoped by design, not by oversight: a referral's destination is often
OUTSIDE the actor's own org_unit subtree (referring a patient UP the
hierarchy to a bigger facility they don't work at) -- restricting this
list to the actor's own scope would make it impossible to ever pick a
valid out-of-scope destination. Facility name/type is reference data,
not PHI, so no per-row scope check applies here (contrast
app/api/routes/patients.py's GET /{id}, which DOES scope-check because
patient records are PHI) -- any authenticated active user may list it.
"""
from fastapi import APIRouter, Depends
from sqlmodel import Session, text

from app.core.authz import get_current_active_user
from app.db.database import get_session

router = APIRouter(prefix="/facilities", tags=["Facilities"])

# Mirrors app/api/routes/referrals.py's own _FACILITY_ORG_UNIT_TYPES
# (module-private there) -- same "private constant mirrored, not reached
# across a module boundary" precedent already established in that file
# (see its own comment on _VALID_ESCALATION_STAGES).
_FACILITY_ORG_UNIT_TYPES = ("PHC", "CHC", "SDH", "HWC", "DISTRICT_HOSPITAL", "TELE_HUB")


@router.get("/")
def list_facilities(
    current_user=Depends(get_current_active_user),
    session: Session = Depends(get_session),
):
    placeholders = ", ".join(f":t{i}" for i in range(len(_FACILITY_ORG_UNIT_TYPES)))
    params = {f"t{i}": t for i, t in enumerate(_FACILITY_ORG_UNIT_TYPES)}
    rows = session.exec(text(
        f"SELECT id, name, unit_type FROM org_units WHERE unit_type IN ({placeholders}) ORDER BY name"
    ), params=params).all()
    return [{"id": str(r[0]), "name": r[1], "facility_type": r[2]} for r in rows]
