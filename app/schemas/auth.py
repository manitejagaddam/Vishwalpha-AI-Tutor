from typing import Optional
from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    username:  str = Field(min_length=3, max_length=50,  examples=["priya_sharma"])
    email:     str = Field(max_length=200,               examples=["priya@example.com"])
    password:  str = Field(min_length=6, max_length=128, examples=["SecurePass123"])
    class_num: int = Field(ge=6, le=12,                  examples=[10])


class LoginRequest(BaseModel):
    username: str = Field(examples=["priya_sharma"])
    password: str = Field(examples=["SecurePass123"])


class AuthResponse(BaseModel):
    user_id:       str           = Field(examples=["3fa85f64-5717-4562-b3fc-2c963f66afa6"])
    username:      str           = Field(examples=["priya_sharma"])
    class_num:     int           = Field(examples=[10])
    access_token:  str           = Field(examples=["eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."])
    refresh_token: Optional[str] = Field(default=None, examples=["dGhpcyBpcyBhIHNhbXBsZSByZWZyZXNoIHRva2Vu"])
    token_type:    str           = Field(default="bearer", examples=["bearer"])
    message:       str           = Field(default="", examples=["Login successful"])
    role:          str           = Field(default="student", examples=["student"])


class UserSummary(BaseModel):
    user_id:   str = Field(examples=["3fa85f64-5717-4562-b3fc-2c963f66afa6"])
    username:  str = Field(examples=["priya_sharma"])
    email:     str = Field(examples=["priya@example.com"])
    class_num: int = Field(examples=[10])
    role:      str = Field(examples=["student"])
