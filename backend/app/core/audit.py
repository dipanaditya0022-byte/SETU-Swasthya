"""Tamper-evident hash chain for audit_log, per Day1.md SS12.3.

`compute_row_hash` is copied verbatim (algorithm, field selection, JSON
canonicalisation) from Day1.md SS12.3. It is deliberately pure and
side-effect-free: given an entry dict and the previous row's hash, it
returns the SHA-256 hex digest that must be stored in that row's
`row_hash` column. Whoever writes an audit_log row (a future route or
job -- out of scope for this migration) is responsible for calling this
before INSERT and supplying both `prev_hash` (the immediately preceding
row's `row_hash`, or None for the first row) and the resulting
`row_hash`.

`verify_chain` is NOT from Day1.md -- it's a small utility added here so
that "hash chain verifies for multiple rows" and "tampering creates a
detectable chain break" (this migration's own testing requirements) are
checkable in code, not just by manual re-derivation, and so a future
nightly verifier job (Day1.md SS12.3: "A nightly verifier walks the
chain and alerts the DPO on any break") has something ready to call
rather than reimplementing chain-walking logic itself.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Optional


def compute_row_hash(entry: dict[str, Any], prev_hash: Optional[str]) -> str:
    """Verbatim from Day1.md SS12.3."""
    canonical = json.dumps({
        "occurred_at": entry["occurred_at"].isoformat(),
        "actor_user_id": str(entry.get("actor_user_id") or ""),
        "action": entry["action"],
        "outcome": entry["outcome"],
        "target_type": entry.get("target_type") or "",
        "target_id": str(entry.get("target_id") or ""),
        "metadata": entry.get("metadata", {}),
        "prev_hash": prev_hash or "",
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def verify_chain(rows: Iterable[dict[str, Any]]) -> tuple[bool, Optional[int]]:
    """Walk `rows` (already ordered oldest-to-newest, each a dict with at
    least the fields compute_row_hash reads, plus 'prev_hash' and
    'row_hash') and confirm every row's stored row_hash matches what
    compute_row_hash recomputes from that row's own fields and the
    previous row's row_hash.

    Returns (True, None) if the whole chain verifies, or (False, id)
    where `id` is the first row found to be broken -- either its
    row_hash doesn't match recomputation, or its stored prev_hash
    doesn't match the actual previous row's row_hash (a gap or
    reordering, not just an in-place edit).
    """
    prev_hash: Optional[str] = None
    for row in rows:
        stored_prev = row.get("prev_hash")
        if stored_prev != prev_hash:
            return False, row.get("id")
        recomputed = compute_row_hash(row, prev_hash)
        if recomputed != row["row_hash"]:
            return False, row.get("id")
        prev_hash = row["row_hash"]
    return True, None
