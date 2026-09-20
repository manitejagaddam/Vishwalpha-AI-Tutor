from typing import Optional
from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    username:  str = Field(min_length=3, max_length=50)
    email:     str = Field(max_length=200)
    password:  str = Field(min_length=6, max_length=128)
    class_num: int = Field(ge=6, le=12)


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    user_id:      str
    username:     str
    class_num:    int
    access_token: str
    refresh_token: Optional[str] = None
    token_type:   str = "bearer"
    message:      str = ""
    role:         str = "student"


class UserSummary(BaseModel):
    user_id: str
    username: str
    email: str
    class_num: int
    role: str
