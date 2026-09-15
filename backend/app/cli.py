"""Operational CLI, per Day1.md SS9 (superuser and bootstrap).

Not a web route. Never imported by app/main.py, never mounted on the
FastAPI app, never reachable over HTTP. Run manually on the server by a
human with shell access, exactly as SS9.1/SS9.2 describe: "This is
resolved outside the API."

WHAT IS VERBATIM VS ADAPTED -- read before reviewing:

- The refusal rule ("a SUPERUSER already exists -> refuse"), the justification
  length floor (>= 50 characters), the fields collected (email, mobile,
  full_name, justification, expires_days), the audit action name
  ("SUPERUSER_BOOTSTRAP"), and the exact one-time terminal banner text
  ("BOOTSTRAP INVITE TOKEN (valid 24 hours, single use, shown once)" /
  "Complete setup at POST /auth/invite/accept, then rotate immediately.")
  are all copied from SS9.2's own code block as closely as this repo's
  real schema allows.

- SS9.2's own `bootstrap_superuser` function is `async def`, queries via
  `select(func.count()).select_from(User).where(User.role == ...)` against
  an ORM class named `User`, and calls bare `encrypt(...)`, `blind_index(...)`,
  and `await audit(...)` helpers. None of that matches this repository:

    * The app is synchronous throughout (app/db/database.py uses SQLModel's
      plain `Session`, not an async session) -- established since S1.
    * `app/models/user.py`'s `User` class maps to the pre-existing singular
      `user` table (id, name, email, phone, password_hash) that backs
      Aditya's nine contract-frozen endpoints (C1) -- a completely different
      table from the RBAC-core `users` table this step writes to. Using it
      here would silently write a SUPERUSER row into the wrong table.
    * The real `users` table (migration c3a9f7d21e56, S6) has no mapped
      SQLModel/ORM class at all -- every route file that touches it
      (app/api/routes/auth.py, app/api/routes/users.py) writes to it via
      raw parameterised SQL through `session.exec(text(...))`, a pattern
      established since S7 and unbroken through S17. This file follows
      that same convention rather than inventing a new ORM mapping.
    * `encrypt()` -> `encrypt_field()` (app/core/crypto.py, S12).
      `blind_index()` -> same name, same module.
      `await audit(session, actor=None, action=..., ...)` -> there is no
      such free function anywhere in this codebase; every route file
      instead defines its own local `_write_audit(session, *, ...)` raw-SQL
      helper (see app/api/routes/auth.py:183, app/api/routes/users.py) that
      calls `app.core.audit.compute_row_hash` and inserts directly into
      `audit_log`. This file defines the same local helper rather than a
      new shared one, matching the existing (already twice-duplicated,
      not newly introduced here) per-file convention.

  This is pseudocode-to-real-code adaptation, the same category of change
  already made for every other Day1.md code block since S9 -- not a new
  gap requiring a fresh stop-and-ask.

- SS9.3's own table adds two constraints SS9.2's code block doesn't show
  inline, both applied here: "MFA: Hardware key mandatory" ->
  `hardware_mfa_required = TRUE` (a real column on `users`, S6/S17) in
  addition to `mfa_required = TRUE` (needed anyway to satisfy
  `chk_privileged_mfa`, since SUPERUSER's role_level is 0); and "Expiry:
  Maximum 365 days" -> `--expires-days` is bounded to [1, 365] by the CLI
  itself (SS9.2's own example passes 90, well inside that range).

- "Prompt securely for credentials rather than accepting secrets in shell
  history" (this step's own instruction) does not apply here: SS9.2's
  bootstrap flow sets no password at all. It creates an INVITED account
  and a `user_invitations` row exactly like every other staff invite
  (SS7), and the printed token is completed later via the already-built
  `POST /auth/invite/accept` (S16) -- which itself prompts for a new
  password at that later step, not here. This is the same "nobody types
  another account's password" design SS7 states outright ("If a BMO
  types a password for a new MO ... the invitation flow removes all
  three problems"). Inventing a direct password-set flag here would
  reintroduce the exact problem SS7 exists to remove, so none was added.

- Not in Day1.md's code block, added here as a plain CLI safety rail with
  no persisted effect and no new business rule: an interactive
  confirmation prompt before creating the account (`--yes` skips it for
  scripted/non-interactive deployment). SS9.3 itself calls this "the
  single most dangerous credential in the system" -- given there is no
  CLI undo, a confirm-before-create step is ordinary operational caution,
  not a spec addition.

- GENUINE GAP, found by testing against a real freshly-migrated database
  and confirmed with the user directly in this session (not silently
  resolved): Day1.md SS9.2's refusal check is unconditional --
  `role = 'SUPERUSER'` with no status filter, meaning "already exists"
  covers any row at all. But migration 9d5f6b3e0a71 (S10, already
  confirmed with the user) itself inserts exactly one bootstrap
  system-attribution `SUPERUSER` row on every migration chain, purely so
  other system-level rows have a valid `created_by_user_id` to point at
  -- id `00000000-0000-0000-0000-000000000001`, `full_name = 'System
  (pre-RBAC migration)'`, `status = 'DEACTIVATED'` (no usable
  credentials -- `chk_deactivated_no_creds` requires `password_hash IS
  NULL` for any DEACTIVATED row). Taken literally, SS9.2's check would
  refuse on every system, including a genuinely fresh one, forever --
  no reachable state would ever let a real superuser be bootstrapped,
  contradicting SS9.1's own premise ("the first account has no higher
  official... resolved outside the API"). The user was asked directly
  and chose: ignore DEACTIVATED rows when checking for an existing
  SUPERUSER (`status <> 'DEACTIVATED'`) -- a deactivated account cannot
  log in, approve, or do anything, so it does not count as "a
  SUPERUSER" in the operational sense SS9.1/SS9.2 mean. This also means
  a *real* superuser that is later fully deactivated no longer blocks a
  fresh bootstrap, which is consistent with SS9.1's disaster-recovery
  framing rather than a weakening of it.

- Pre-flight uniqueness checks on mobile/email (mirroring the
  MOBILE_IN_USE / HPR_IN_USE pattern already used in
  app/api/routes/users.py's create_user) turn what would otherwise be an
  unhandled `psycopg.errors.UniqueViolation` traceback into a clean,
  same-shape refusal message. This does not relax or add any constraint
  -- `idx_users_mobile_bi` / `idx_users_email_bi` (S6) already enforce
  this at the database level; the check only makes the CLI's failure mode
  match the rest of the app's.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import click
from dotenv import load_dotenv
from sqlmodel import Session, text

# Unlike the FastAPI app (app/main.py), which loads .env as a side effect
# of importing app.db.database early in its own router-import chain, this
# module is a standalone entrypoint (`python -m app.cli`) with no
# guaranteed import order relative to anything else -- it must load its
# own environment before importing app.core.crypto below, whose module-
# level key loading (_DEK = _load_key("FIELD_ENCRYPTION_KEY")) would
# otherwise run before any .env file has been read.
load_dotenv()

from app.core.audit import compute_row_hash
from app.core.crypto import blind_index, encrypt_field, mask_mobile
from app.db.database import engine
from app.models.enums import ROLE_LEVEL, RoleCode


def _write_audit(session: Session, *, actor_user_id: Optional[str], action: str,
                  outcome: str, target_type: Optional[str] = None,
                  target_id: Optional[str] = None, metadata: Optional[dict] = None) -> None:
    # Duplicated from app/api/routes/auth.py's/_write_audit's own pattern
    # (S16/S17) rather than imported, since that helper is a route-module
    # private function, not a shared library export. Same audit_log
    # hash-chain shape either way.
    prev = session.exec(text("SELECT row_hash FROM audit_log ORDER BY id DESC LIMIT 1")).first()
    prev_hash = prev[0] if prev else None
    occurred_at = datetime.now(timezone.utc)
    entry = {"occurred_at": occurred_at, "actor_user_id": actor_user_id, "action": action,
              "outcome": outcome, "target_type": target_type, "target_id": target_id,
              "metadata": metadata or {}}
    row_hash = compute_row_hash(entry, prev_hash)
    session.exec(text(
        "INSERT INTO audit_log (occurred_at, actor_user_id, action, outcome, target_type, "
        "target_id, metadata, prev_hash, row_hash) VALUES "
        "(:occurred_at, :actor_user_id, :action, :outcome, :target_type, :target_id, "
        ":metadata, :prev_hash, :row_hash)"
    ), params={"occurred_at": occurred_at, "actor_user_id": actor_user_id, "action": action,
               "outcome": outcome, "target_type": target_type, "target_id": target_id,
               "metadata": json.dumps(metadata or {}), "prev_hash": prev_hash, "row_hash": row_hash})


@click.group()
def cli() -> None:
    """SETU-Swasthya operational CLI.

    Shell-only. Never exposed over HTTP, never imported by app/main.py.
    """


@cli.command("bootstrap-superuser")
@click.option("--email", required=True, help="SUPERUSER's login email (dev/test only -- use a fake address).")
@click.option("--mobile", required=True, help="SUPERUSER's mobile, E.164 format (dev/test only -- use a fake number).")
@click.option("--full-name", required=True, help="Full name as it will appear in the audit trail.")
@click.option("--justification", required=True,
              help="Why this bootstrap is happening. Must be >= 50 characters (Day1.md SS9.2).")
@click.option("--expires-days", required=True, type=click.IntRange(1, 365),
              help="Account expiry in days from now. Maximum 365 (Day1.md SS9.3).")
@click.option("--yes", "-y", is_flag=True, default=False,
              help="Skip the interactive confirmation prompt (for scripted deployment).")
def bootstrap_superuser(email: str, mobile: str, full_name: str, justification: str,
                         expires_days: int, yes: bool) -> None:
    """Create the very first SUPERUSER on an empty system (Day1.md SS9.2).

    Refuses if any non-deactivated SUPERUSER row already exists (see this
    file's module docstring for why DEACTIVATED rows -- specifically S10's
    own bootstrap system-attribution row -- are excluded from that check;
    confirmed with the user directly in this session). To add a second (or
    third, or fourth -- SS9.3 caps it at 4) superuser on a live system, use
    POST /users with an existing superuser's session and a second superuser
    approving, per SS9.3's own "Creation" row. This command is a one-shot
    escape hatch for Rule 2's chicken-and-egg problem (SS9.1), not a
    general-purpose account creator.
    """
    if len(justification) < 50:
        raise SystemExit("Justification must be at least 50 characters.")

    with Session(engine) as session:
        existing = session.exec(
            text("SELECT count(*) FROM users WHERE role = 'SUPERUSER' AND status <> 'DEACTIVATED'")
        ).first()
        if existing[0] > 0:
            raise SystemExit(
                "A SUPERUSER already exists. Bootstrap may only run on an empty system.\n"
                "To add another superuser, use POST /users with an existing superuser "
                "session and a second approver."
            )

        mobile_bi = blind_index(mobile)
        if session.exec(text("SELECT id FROM users WHERE mobile_blind_index = :m AND status <> 'DEACTIVATED'"),
                         params={"m": mobile_bi}).first() is not None:
            raise SystemExit("That mobile number is already registered to another account.")

        email_bi = blind_index(email)
        if session.exec(text("SELECT id FROM users WHERE email_blind_index = :e AND status <> 'DEACTIVATED'"),
                         params={"e": email_bi}).first() is not None:
            raise SystemExit("That email is already registered to another account.")

        if not yes:
            click.echo("\nAbout to bootstrap the FIRST SUPERUSER on this system:")
            click.echo(f"  full_name : {full_name}")
            click.echo(f"  email     : {email}")
            click.echo(f"  mobile    : {mask_mobile(mobile)}")
            click.echo(f"  expires   : {expires_days} days from now")
            click.echo("This is irreversible from this CLI and cannot be undone once created.")
            click.confirm("Proceed?", abort=True)

        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_days)

        row = session.exec(text(
            "INSERT INTO users (role, role_level, full_name, mobile_encrypted, mobile_blind_index, "
            "mobile_masked, email_encrypted, email_blind_index, status, mfa_required, "
            "hardware_mfa_required, expires_at) "
            "VALUES (:role, :lvl, :fn, :menc, :mbi, :mmask, :eenc, :ebi, :status, :mfareq, "
            ":hwmfa, :exp) RETURNING id, created_at"
        ), params={
            "role": RoleCode.SUPERUSER.value, "lvl": ROLE_LEVEL[RoleCode.SUPERUSER], "fn": full_name,
            "menc": encrypt_field(mobile), "mbi": mobile_bi, "mmask": mask_mobile(mobile),
            "eenc": encrypt_field(email), "ebi": email_bi,
            # created_by_user_id, scope_org_unit_id, scope_path, reports_to_user_id all
            # omitted -> NULL. chk_creator_required and chk_scope_required both explicitly
            # exempt role = 'SUPERUSER' (migration c3a9f7d21e56).
            "status": "INVITED",
            # chk_privileged_mfa requires role_level > 5 OR mfa_required = TRUE; SUPERUSER's
            # role_level is 0, so this must be TRUE regardless. hardware_mfa_required = TRUE
            # is SS9.3's own "Hardware key mandatory. TOTP alone is rejected at login."
            "mfareq": True, "hwmfa": True,
            "exp": expires_at,
        }).first()
        new_id, created_at = row

        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        invite_expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
        session.exec(text(
            "INSERT INTO user_invitations (user_id, token_hash, accept_mode, issued_by, expires_at) "
            "VALUES (:uid, :th, :am, :ib, :exp)"
        ), params={"uid": new_id, "th": token_hash, "am": "PASSWORD", "ib": None, "exp": invite_expires_at})

        _write_audit(session, actor_user_id=None, action="SUPERUSER_BOOTSTRAP", outcome="SUCCESS",
                     target_type="USER", target_id=str(new_id),
                     metadata={"justification": justification, "via": "CLI"})

        session.commit()

    # Printed ONCE to the operator's terminal. Never logged, never emailed.
    # (Day1.md SS9.2's own banner text, verbatim.)
    click.echo("\n" + "=" * 72)
    click.echo("BOOTSTRAP INVITE TOKEN (valid 24 hours, single use, shown once):")
    click.echo(f"  {token}")
    click.echo("Complete setup at POST /auth/invite/accept, then rotate immediately.")
    click.echo("=" * 72 + "\n")
    click.echo(f"SUPERUSER created: id={new_id} created_at={created_at.isoformat()} "
               f"expires_at={expires_at.isoformat()}")


if __name__ == "__main__":
    cli()
