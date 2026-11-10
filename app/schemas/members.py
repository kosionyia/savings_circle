from datetime import date, datetime

from pydantic import BaseModel


class StatementLineOut(BaseModel):
    entry_id: int
    reference: str
    description: str
    posted_at: datetime
    # The member's view: positive = money in to their wallet, negative = out
    amount_kobo: int
    # What we hold for the member straight after this line
    balance_kobo: int


class MemberStatement(BaseModel):
    member_id: int
    # The period as asked for, inclusive, in Lagos time. No from_date means
    # the statement starts at the member's first entry.
    from_date: date | None
    to_date: date
    opening_balance_kobo: int
    lines: list[StatementLineOut]
    closing_balance_kobo: int
