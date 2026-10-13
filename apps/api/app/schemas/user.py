from pydantic import BaseModel, EmailStr, field_validator
from datetime import datetime


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str | None = None

    @field_validator("password")
    @classmethod
    def valid_password(cls, value):
        from app.core.security import validate_password
        validate_password(value)
        return value


class UserRead(BaseModel):
    id: int
    email: EmailStr
    full_name: str | None
    is_active: bool
    created_at: datetime
    # False for an account that signs in only with Microsoft or Google.
    has_password: bool = True
    auth_providers: list[str] = []
    credit_balance: int = 0
    credits_enabled: bool = False
    credits_unlimited: bool = False
    # May grant credits to any account (/admin/credits).
    is_admin: bool = False

    model_config = {"from_attributes": True}


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
