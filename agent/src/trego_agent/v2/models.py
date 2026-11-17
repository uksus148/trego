"""The existing chat envelope, independent of the old application factory."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from trego_agent.api_models import ApiPlace


Nonblank = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    sessionId: Nonblank = Field(max_length=128)
    message: Nonblank = Field(max_length=4000)


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    reply: Nonblank = Field(max_length=4000)
    places: list[ApiPlace] = Field(default_factory=list)
    routeId: str | None = None
