from typing import Annotated
from uuid import UUID

from pydantic import Field, field_validator

from chatflow_shared.schemas import Input, Title, trim


class MessageInput(Input):
    content: Annotated[str, Field(min_length=1, max_length=4000)]
    request_key: UUID
    model: Annotated[str | None, Field(max_length=100)] = None
    normalize = field_validator("content", mode="before")(trim)
