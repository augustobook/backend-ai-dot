"""Generic response schemas shared across endpoints."""

from typing import Literal

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Error body, following FastAPI's default `{"detail": ...}` format."""

    detail: str = Field(
        ...,
        description="Human-readable description of the error.",
        examples=["Book with id 42 not found"],
    )


class HealthResponse(BaseModel):
    """Body returned by the health check endpoint."""

    status: Literal["ok"] = Field(
        ..., description="Health status of the application.", examples=["ok"]
    )
