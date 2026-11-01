from sqlalchemy import BigInteger
from sqlmodel import Field, Relationship, SQLModel

class Circle(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    weekly_amount_kobo: int = Field(sa_type=BigInteger)
    member_limit: int
    current_week: int = 1
    admin_id: int = Field(foreign_key="user.id")

    memberships: list["Membership"] = Relationship(back_populates="circle")
