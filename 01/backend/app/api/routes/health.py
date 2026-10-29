"""Health check endpoint."""

from fastapi import APIRouter, status

from app.schemas.common import HealthResponse

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Health check",
    description="Return `ok` when the application is up and able to serve requests.",
    response_description="The application is healthy.",
)
def health_check() -> HealthResponse:
    """Report that the application is running.

    Returns:
        A body with status `ok`.
    """
    return HealthResponse(status="ok")
