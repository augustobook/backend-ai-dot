"""Health check endpoint."""

from fastapi import APIRouter

from app.api.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    summary="Health check",
    description=(
        "Liveness probe. Does not call OpenAI, so it answers even when the API key "
        "is missing or the LLM is unavailable."
    ),
)
async def health() -> HealthResponse:
    """Report that the API process is running.

    Returns:
        `{"status": "ok"}`.
    """
    return HealthResponse(status="ok")
