from enum import Enum
from pydantic import BaseModel, EmailStr

from sqlmodel import SQLModel, Field


class UserRole(str, Enum):
    ADMIN = "admin"
    MEMBER = "member"

class User(SQLModel,table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    email: EmailStr
    hashed_password: str
    role: UserRole



class UserBase(BaseModel):
    name: str 
    email: EmailStr
    role: str = "member"

class CreateUser(UserBase):
    password: str
