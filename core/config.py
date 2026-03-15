from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import List


class Settings(BaseSettings):
    SUPABASE_URL: str
    SUPABASE_SERVICE_ROLE_KEY: str   # SERVICE ROLE — never anon key
    REDIS_URL: str                   # must start with rediss://
    ENCRYPTION_KEY: str              # 64 hex chars = 32 bytes
    JWT_SECRET: str                  # min 64 chars
    JWT_EXPIRY_MINUTES: int = 10
    MAGIC_LINK_EXPIRY_MINUTES: int = 15
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_ADMIN_UID: int
    ENV: str = 'production'
    PORT: int = 3000
    ALLOWED_ORIGINS: List[str] = []
    INTERNAL_API_URL: str = ''
    ROTATION_THRESHOLD: float = 0.80

    @field_validator('REDIS_URL')
    @classmethod
    def check_redis_url(cls, v: str) -> str:
        if not (v.startswith('rediss://') or v.startswith('redis://')):
            raise ValueError('REDIS_URL must start with redis:// or rediss://')
        return v

    @field_validator('ENCRYPTION_KEY')
    @classmethod
    def check_enc_key(cls, v: str) -> str:
        if len(v) != 64:
            raise ValueError(f'ENCRYPTION_KEY must be 64 hex chars, got {len(v)}')
        try:
            bytes.fromhex(v)
        except ValueError as e:
            raise ValueError(f'ENCRYPTION_KEY must be valid hex: {e}')
        return v

    @field_validator('JWT_SECRET')
    @classmethod
    def check_jwt_secret(cls, v: str) -> str:
        if len(v) < 64:
            raise ValueError('JWT_SECRET min 64 chars')
        return v

    class Config:
        env_file = '.env'


settings = Settings()   # raises at startup if any var wrong/missing
