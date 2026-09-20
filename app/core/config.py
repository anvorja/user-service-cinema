# app/core/config.py
from typing import Any, List
from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "User Service"
    VERSION: str = "1.0.0"

    DATABASE_URL: str
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    REDIS_URL: str = ""
    AUTH_SERVICE_URL: str
    BOOKING_SERVICE_URL: str = "http://booking-service:8004"

    # Secreto compartido para rutas /internal/* (propias y de otros
    # servicios) — ver ARCHITECTURE.md, "Aislamiento de base de datos por
    # servicio". Debe coincidir con el mismo valor en booking-service (lo
    # llamamos) y admin-service (nos llama).
    INTERNAL_SERVICE_TOKEN: str = ""

    # Kafka — consume user.registered para poblar perfiles
    KAFKA_ENABLED: bool = False
    KAFKA_BOOTSTRAP_SERVERS: str = ""
    KAFKA_API_KEY: str = ""
    KAFKA_API_SECRET: str = ""
    # Default = group_id histórico de producción, sin variable nueva en Render.
    # Local lo sobreescribe con sufijo "-local" — dev y prod comparten el
    # mismo cluster de Confluent Cloud, y sin distinguir el group_id ambos
    # entornos terminan en el MISMO grupo de consumidores.
    KAFKA_GROUP_ID: str = "user-service-group"

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
