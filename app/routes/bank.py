from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlmodel import Session, select

from app.models.contribution import Contribution
from app.models.ledger import LedgerEntry
from app.schemas.bank import BankConfirmIn, LedgerOut
from app.schemas.contributions import ContributionOut
from app.services.db import get_session
from app.services.dependency import require_bank_robot
from app.services.ledger import write_ledger_line

router = APIRouter(prefix="/bank", tags=["Bank"])


@router.post(
    "/confirm",
    response_model=ContributionOut,
    status_code=status.HTTP_200_OK,
)
def confirm_transfer(
    body: BankConfirmIn,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    _: str = Depends(require_bank_robot),
):
    contribution = session.get(Contribution, body.contribution_id)
    if contribution is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contribution not found",
        )

    if contribution.confirmed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This contribution is already confirmed",
        )

    contribution.confirmed = True
    session.add(contribution)
    session.commit()
    session.refresh(contribution)

    background_tasks.add_task(
        write_ledger_line,
        contribution.id,
        contribution.circle_id,
        contribution.user_id,
        contribution.amount,
        contribution.week,
    )

    return contribution


@router.get(
    "/ledger",
    response_model=list[LedgerOut],
    status_code=status.HTTP_200_OK,
)
def read_ledger(
    session: Session = Depends(get_session),
    _: str = Depends(require_bank_robot),
):
    return session.exec(
        select(LedgerEntry).order_by(LedgerEntry.id)
    ).all()
