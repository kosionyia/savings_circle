from sqlmodel import Field, Relationship, SQLModel
from sqlalchemy import UniqueConstraint

from app.models.circles import Circle


class Membership(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("user_id", "circle_id"),
        UniqueConstraint("circle_id", "turn_position"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    circle_id: int = Field(foreign_key="circle.id")
    turn_position: int

    circle: Circle | None = Relationship(back_populates="memberships")
