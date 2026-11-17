"""Explicit configuration: importing the core never loads dotenv or service keys."""

from pydantic import BaseModel, ConfigDict, Field


class AppSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)

    chat_timeout_seconds: float = Field(default=180, gt=0, le=300)
