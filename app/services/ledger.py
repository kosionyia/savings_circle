from sqlmodel import Session

from app.models.ledger import LedgerEntry
from app.services.db import engine


def write_ledger_line(
    contribution_id: int,
    circle_id: int,
    user_id: int,
    amount: int,
    week: int,
) -> None:
    with Session(engine) as session:
        session.add(
            LedgerEntry(
                contribution_id=contribution_id,
                circle_id=circle_id,
                user_id=user_id,
                amount=amount,
                week=week,
            )
        )
        session.commit()
