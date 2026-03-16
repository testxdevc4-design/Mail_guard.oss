from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from core.config import settings
from apps.api.routes import health
from apps.api.middleware.rate_limit import RateLimitMiddleware
from apps.api.middleware.security import SecurityHeadersMiddleware


def create_app() -> FastAPI:
    app = FastAPI(
        title="MailGuard OSS",
        version="1.0.0",
        docs_url="/docs" if settings.ENV == "development" else None,
        redoc_url="/redoc" if settings.ENV == "development" else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,  # never ['*']
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RateLimitMiddleware)

    app.include_router(health.router, tags=["System"])

    return app


app = create_app()
