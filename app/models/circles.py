from sqlmodel import SQLModel, Field

class Circle(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    weekly_amount: int
    member_limit: int
    admin_id: int = Field(foreign_key="user.id")