from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import BigInteger, CheckConstraint, DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel


class OwnerType(str, Enum):
    SYSTEM = "system"
    CIRCLE = "circle"
    USER = "user"


class AccountType(str, Enum):
    BANK_CLEARING = "bank_clearing"
    CIRCLE_POT = "circle_pot"
    MEMBER_WALLET = "member_wallet"
    FEES = "fees"


class LedgerAccount(SQLModel, table=True):
    __tablename__ = "ledger_account"
    __table_args__ = (
        UniqueConstraint("owner_type", "owner_id", "account_type", "currency",
                         postgresql_nulls_not_distinct=True),
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_type: OwnerType
    owner_id: int | None = None
    account_type: AccountType
    currency: str = "NGN"


class JournalEntry(SQLModel, table=True):
    __tablename__ = "journal_entry"

    id: int | None = Field(default=None, primary_key=True)
    reference: str = Field(unique=True)
    description: str
    created_by: int = Field(foreign_key="user.id")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
    )
    reverses_id: int | None = Field(
        default=None,
        unique=True,
        foreign_key="journal_entry.id",
    )


class JournalLine(SQLModel, table=True):
    __tablename__ = "journal_line"
    __table_args__ = (
        CheckConstraint("amount_kobo <> 0", name="ck_journal_line_nonzero"),
    )

    id: int | None = Field(default=None, primary_key=True)
    entry_id: int = Field(foreign_key="journal_entry.id", index=True)
    account_id: int = Field(foreign_key="ledger_account.id", index=True)
    amount_kobo: int = Field(sa_type=BigInteger)


class LedgerEntry(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    contribution_id: int = Field(foreign_key="contribution.id")
    circle_id: int
    user_id: int
    amount: int
    week: int
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
    )
