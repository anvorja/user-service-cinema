# app/core/config.py
from typing import Any, List
from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "User Service"
    VERSION: str = "1.0.0"

    DATABASE_URL: str
    BOOKING_DATABASE_URL: str = ""
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    REDIS_URL: str = ""
    AUTH_SERVICE_URL: str

    # Kafka — consume user.registered para poblar perfiles
    KAFKA_ENABLED: bool = False
    KAFKA_BOOTSTRAP_SERVERS: str = ""
    KAFKA_API_KEY: str = ""
    KAFKA_API_SECRET: str = ""

    BACKEND_CORS_ORIGINS: List[str] = ["*"]
    DEBUG: bool = False

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    def assemble_cors_origins(cls, v: Any) -> List[str]:
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            stripped = v.strip()
            if stripped.startswith("["):
                import json
                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, list):
                        return parsed
                except json.JSONDecodeError:
                    pass
            return [i.strip() for i in stripped.split(",") if i.strip()]
        raise ValueError(f"Invalid CORS origins: {v}")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
        "extra": "ignore",
    }


settings = Settings()
