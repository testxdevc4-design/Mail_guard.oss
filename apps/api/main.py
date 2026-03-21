from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from core.config import settings
from apps.api.routes import health, otp
from apps.api.routes import magic
from apps.api.routes import webhooks
from apps.api.middleware.rate_limit import RateLimitMiddleware
from apps.api.middleware.security import SecurityHeadersMiddleware
from apps.api.middleware.csrf import CSRFProtectionMiddleware


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
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Requested-With"],
    )

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(CSRFProtectionMiddleware)

    app.include_router(health.router, tags=["System"])
    app.include_router(otp.router)
    app.include_router(magic.router)
    app.include_router(webhooks.router)

    return app


app = create_app()
