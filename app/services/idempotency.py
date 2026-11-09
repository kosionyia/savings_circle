import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session

from app.models.idempotency import IdempotencyKey

REPLAY_HEADER = "Idempotent-Replayed"


def request_hash(method: str, path: str, body: dict) -> str:
    """Fingerprint a request so a reused Idempotency-Key can be compared.

    The body is serialised as canonical JSON (sorted keys, no spaces) so
    the same request always hashes the same, whatever its key order.
    """
    canonical_body = json.dumps(body, sort_keys=True, separators=(",", ":"))
    fingerprint = "\n".join([method.upper(), path, canonical_body])
    return hashlib.sha256(fingerprint.encode()).hexdigest()


@dataclass(frozen=True)
class Idempotency:
    key: str
    user_id: int
    endpoint: str
    fingerprint: str

    @property
    def primary_key(self) -> dict:
        return {"key": self.key, "user_id": self.user_id, "endpoint": self.endpoint}


def claim(session: Session, idem: Idempotency) -> JSONResponse | None:
    """Claim the key for this request, or return the response to replay.

    Returns None when this request owns the key and should do the work.
    The key row is inserted in the caller's transaction: a concurrent
    request with the same key waits on the primary key until we commit
    (then replays our response) or roll back (then does the work itself).
    """
    inserted = session.execute(
        insert(IdempotencyKey)
        .values(
            **idem.primary_key,
            request_hash=idem.fingerprint,
            created_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_nothing()
        .returning(IdempotencyKey.key)
    ).first()
    if inserted is not None:
        return None

    existing = session.get(IdempotencyKey, idem.primary_key)
    if existing.request_hash != idem.fingerprint:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Idempotency-Key was already used for a different request",
        )
    if existing.response_status is None:
        # Not reachable with the same-transaction design, but never replay
        # an empty response
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A request with this Idempotency-Key is still in progress",
        )

    return JSONResponse(
        status_code=existing.response_status,
        content=existing.response_body,
        headers={REPLAY_HEADER: "true"},
    )


def store_response(
    session: Session,
    idem: Idempotency,
    status_code: int,
    body: dict,
) -> JSONResponse:
    """Save the response with the key; the caller's commit makes both permanent."""
    row = session.get(IdempotencyKey, idem.primary_key)
    row.response_status = status_code
    row.response_body = body
    session.add(row)
    return JSONResponse(status_code=status_code, content=body)


def run_idempotent(
    session: Session,
    idem: Idempotency,
    work: Callable[[], tuple[int, dict]],
) -> JSONResponse:
    """Replay a stored response, or run `work` and store what it returns.

    `work` flushes but never commits; it returns (status_code, body). The
    work, the key and the stored response then commit together.
    """
    replay = claim(session, idem)
    if replay is not None:
        return replay

    try:
        status_code, body = work()
    except HTTPException:
        # Errors are not stored: release the key so a corrected retry can run
        session.rollback()
        raise

    response = store_response(session, idem, status_code, body)
    session.commit()
    return response
