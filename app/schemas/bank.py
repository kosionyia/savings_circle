from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.ledger import AccountType, OwnerType


class BankConfirmIn(BaseModel):
    contribution_id: int

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"contribution_id": 1}]
        }
    )


class JournalLineOut(BaseModel):
    account_id: int
    owner_type: OwnerType
    owner_id: int | None
    account_type: AccountType
    amount_kobo: int


class JournalEntryOut(BaseModel):
    id: int
    reference: str
    description: str
    created_by: int | None
    created_at: datetime
    reverses_id: int | None
    lines: list[JournalLineOut]
