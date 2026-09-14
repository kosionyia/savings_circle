from pydantic import BaseModel, ConfigDict


class CircleCreate(BaseModel):
    name: str
    weekly_amount: int
    member_limit: int

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "Surulere Market Circle",
                    "weekly_amount": 5000,
                    "member_limit": 5,
                }
            ]
        }
    )


class AdmitMember(BaseModel):
    user_id: int

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"user_id": 2}]
        }
    )


class TurnOrderIn(BaseModel):
    user_ids: list[int]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"user_ids": [2, 3]}]
        }
    )


class TurnMember(BaseModel):
    user_id: int
    name: str
    turn_position: int


class MembershipOut(BaseModel):
    id: int
    user_id: int
    circle_id: int
    turn_position: int

    model_config = ConfigDict(from_attributes=True)



class GetCircle(CircleCreate):
    id: int
    current_week: int
    member_count: int

class CircleOut(BaseModel):
    id: int
    name: str
    weekly_amount: int
    member_limit: int
    current_week: int
    admin_id: int
    pot: int
    member_count: int
    turn_order: list[TurnMember]
    next_user_id: int | None
    next_user_name: str | None


class MemberHealth(BaseModel):
    user_id: int
    name: str


class CircleHealth(BaseModel):
    week: int
    paid: list[MemberHealth]
    behind: list[MemberHealth]
