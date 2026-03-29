from pydantic import BaseModel, field_validator
from typing import Optional


class TokenUpdate(BaseModel):
    updates: dict[str, str]

    @field_validator("updates")
    @classmethod
    def no_empty_keys(cls, v):
        if not v:
            raise ValueError("updates cannot be empty")
        return v


class TokenInfo(BaseModel):
    label: str
    required: bool
    set: bool
    value: str   # redacted string or ""


class TokensResponse(BaseModel):
    tokens: dict[str, TokenInfo]
    missing_required: list[str]


class TokenUpdateResponse(BaseModel):
    changed: list[str]
    message: str