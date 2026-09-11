from datetime import datetime

from pydantic import BaseModel, ConfigDict


class BankConfirmIn(BaseModel):
    contribution_id: int

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"contribution_id": 1}]
        }
    )


class LedgerOut(BaseModel):
    id: int
    contribution_id: int
    circle_id: int
    user_id: int
    amount: int
    week: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
