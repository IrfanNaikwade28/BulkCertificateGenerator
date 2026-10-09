import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api.routes import certificates, health, jobs
from app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    application = FastAPI(
        title="Bulk Certificate Generator API",
        version="1.0.0",
        description=(
            "Accepts a batch of recipients, generates one PDF certificate per "
            "recipient in the background, and exposes job progress plus "
            "certificate metadata and downloads."
        ),
    )
    application.include_router(health.router)
    application.include_router(jobs.router, prefix="/api/v1")
    application.include_router(certificates.router, prefix="/api/v1")

    @application.exception_handler(Exception)
    async def unhandled_exception_handler(request, exception):  # noqa: ANN001
        logging.getLogger(__name__).exception(
            "Unhandled error on %s %s", request.method, request.url.path
        )
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    return application


app = create_app()
