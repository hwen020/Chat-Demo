from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Credentials(Input):
    email: Annotated[str, Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]
    password: Annotated[str, Field(min_length=10, max_length=128)]

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value):
        return value.strip().lower() if isinstance(value, str) else value

def trim(value):
    return value.strip() if isinstance(value, str) else value

class Title(Input):
    title: Annotated[str, Field(min_length=1, max_length=100)]
    normalize = field_validator("title", mode="before")(trim)

class MessageInput(Input):
    content: Annotated[str, Field(min_length=1, max_length=4000)]
    request_key: UUID
    normalize = field_validator("content", mode="before")(trim)
