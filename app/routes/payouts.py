from collections.abc import Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models.circles import Circle
from app.models.ledger import AccountType, JournalEntry, OwnerType
from app.models.payout import Payout
from app.models.user import User
from app.schemas.payouts import PayoutIn, PayoutOut
from app.services.db import get_session
from app.services.dependency import require_admin
from app.services.helpers import (
    assert_circle_admin,
    get_circle_or_404,
    next_recipient,
)
from app.services.idempotency import Idempotency, request_hash, run_idempotent
from app.services.ledger import (
    Line,
    account_balance,
    get_or_create_account,
    post_entry,
    reverse_entry,
)
from app.services.payouts import IllegalTransition, next_status

router = APIRouter(tags=["Payouts"])

IdempotencyKeyHeader = Header(
    alias="Idempotency-Key",
    min_length=1,
    max_length=255,
    description="A unique ID (e.g. a UUID) per action; reuse it on retries",
)

# An effect runs after the status check and posts the action's journal entry
Effect = Callable[[Session, Payout, Circle, User], None]


def _payout_out(payout: Payout) -> dict:
    return PayoutOut.model_validate(payout).model_dump(mode="json")


def _accounts(session: Session, payout: Payout):
    pot = get_or_create_account(
        session, OwnerType.CIRCLE, payout.circle_id, AccountType.CIRCLE_POT
    )
    wallet = get_or_create_account(
        session, OwnerType.USER, payout.user_id, AccountType.MEMBER_WALLET
    )
    bank = get_or_create_account(
        session, OwnerType.SYSTEM, None, AccountType.BANK_CLEARING
    )
    return pot, wallet, bank


@router.post(
    "/circles/{circle_id}/payouts",
    response_model=PayoutOut,
    status_code=status.HTTP_201_CREATED,
)
def schedule_payout(
    circle_id: int,
    body: PayoutIn,
    request: Request,
    idempotency_key: str = IdempotencyKeyHeader,
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    idem = Idempotency(
        key=idempotency_key,
        user_id=current_user.id,
        endpoint="POST /circles/{circle_id}/payouts",
        fingerprint=request_hash(
            request.method, request.url.path, body.model_dump(mode="json")
        ),
    )

    def work() -> tuple[int, dict]:
        circle = get_circle_or_404(session, circle_id)
        assert_circle_admin(current_user, circle)

        expected = next_recipient(session, circle)
        if expected is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This circle has no members to pay",
            )
        if body.user_id != expected.user_id:
            person = session.get(User, expected.user_id)
            name = person.name if person else f"user {expected.user_id}"
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"This week's payout must go to {name} "
                    f"(user {expected.user_id}), not user {body.user_id}"
                ),
            )

        payout = Payout(
            circle_id=circle.id,
            user_id=body.user_id,
            week=circle.current_week,
        )
        session.add(payout)
        try:
            session.flush()
        except IntegrityError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This week already has a payout",
            )
        return status.HTTP_201_CREATED, _payout_out(payout)

    return run_idempotent(session, idem, work)


def _transition(
    action: str,
    payout_id: int,
    request: Request,
    idempotency_key: str,
    current_user: User,
    session: Session,
    effect: Effect | None = None,
):
    """Shared flow for every payout action: auth, state check, effect, save."""
    idem = Idempotency(
        key=idempotency_key,
        user_id=current_user.id,
        endpoint=f"POST /payouts/{{payout_id}}/{action}",
        fingerprint=request_hash(request.method, request.url.path, {}),
    )

    def work() -> tuple[int, dict]:
        payout = session.get(Payout, payout_id)
        if payout is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Payout not found",
            )
        circle = get_circle_or_404(session, payout.circle_id)
        assert_circle_admin(current_user, circle)

        try:
            new_status = next_status(payout.status, action)
        except IllegalTransition as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

        if effect is not None:
            effect(session, payout, circle, current_user)
        payout.status = new_status
        session.add(payout)
        try:
            session.flush()
        except IntegrityError:
            # Another request posted this action's journal entry first
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This payout was changed by another request",
            )
        session.refresh(payout)
        return status.HTTP_200_OK, _payout_out(payout)

    return run_idempotent(session, idem, work)


def _initiate(session: Session, payout: Payout, circle: Circle, user: User) -> None:
    pot, wallet, _ = _accounts(session, payout)
    # The pot is a liability, so its balance is negative; flip it to get naira held
    amount = -account_balance(session, pot.id)
    if amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The pot has no confirmed contributions to pay out",
        )
    payout.amount_kobo = amount
    post_entry(
        session,
        reference=f"PAYOUT-{payout.id}-INITIATE",
        description=f"Payout {payout.id}: circle {circle.id} week {payout.week} to user {payout.user_id}",
        lines=[Line(pot.id, amount), Line(wallet.id, -amount)],
        created_by=user.id,
    )


def _confirm(session: Session, payout: Payout, circle: Circle, user: User) -> None:
    _, wallet, bank = _accounts(session, payout)
    post_entry(
        session,
        reference=f"PAYOUT-{payout.id}-CONFIRM",
        description=f"Payout {payout.id}: bank transfer to user {payout.user_id} confirmed",
        lines=[Line(wallet.id, payout.amount_kobo), Line(bank.id, -payout.amount_kobo)],
        created_by=user.id,
    )
    # The turn is only over once the money has actually left
    circle.current_week += 1
    session.add(circle)


def _reverse(session: Session, payout: Payout, circle: Circle, user: User) -> None:
    initiate = session.exec(
        select(JournalEntry).where(
            JournalEntry.reference == f"PAYOUT-{payout.id}-INITIATE"
        )
    ).one()
    # Moves the money from the member's wallet back into the pot
    reverse_entry(
        session,
        initiate.id,
        created_by=user.id,
        description=f"Payout {payout.id} failed: money returned to circle {circle.id} pot",
    )


def _action_route(action: str, effect: Effect | None, summary: str):
    @router.post(
        f"/payouts/{{payout_id}}/{action}",
        response_model=PayoutOut,
        status_code=status.HTTP_200_OK,
        summary=summary,
        name=f"{action}_payout",
    )
    def endpoint(
        payout_id: int,
        request: Request,
        idempotency_key: str = IdempotencyKeyHeader,
        current_user: User = Depends(require_admin),
        session: Session = Depends(get_session),
    ):
        return _transition(
            action, payout_id, request, idempotency_key, current_user, session, effect
        )

    return endpoint


approve_payout = _action_route("approve", None, "Approve a scheduled payout")
initiate_payout = _action_route(
    "initiate", _initiate, "Start the transfer: move the pot into the member's wallet"
)
confirm_payout = _action_route(
    "confirm", _confirm, "The bank sent the money: close the turn"
)
fail_payout = _action_route("fail", None, "The bank transfer failed")
reverse_payout = _action_route(
    "reverse", _reverse, "Return a failed payout's money to the pot"
)
