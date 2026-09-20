# app/kafka/consumer.py
import asyncio
import json
import logging
import ssl

from aiokafka import AIOKafkaConsumer

from app.core.config import settings

logger = logging.getLogger(__name__)


async def _handle_user_registered(payload: dict, db_factory) -> None:
    """
    Crea o actualiza el perfil del usuario en cinema_users cuando auth-service
    publica el evento user.registered (en registro nuevo).
    Idempotente: usa ON CONFLICT DO UPDATE para reenvíos seguros.
    """
    from sqlalchemy import text
    with db_factory() as db:
        db.execute(
            text("""
                INSERT INTO users (id, email, first_name, last_name, phone, role, is_active,
                                   created_at, updated_at)
                VALUES (:id, :email, :first_name, :last_name, :phone,
                        CAST(:role AS userrole), true, now(), now())
                ON CONFLICT (id) DO UPDATE
                    SET email      = EXCLUDED.email,
                        first_name = EXCLUDED.first_name,
                        last_name  = EXCLUDED.last_name,
                        phone      = EXCLUDED.phone,
                        role       = EXCLUDED.role,
                        updated_at = now()
            """),
            {
                "id": payload["id"],
                "email": payload["email"],
                "first_name": payload["first_name"],
                "last_name": payload["last_name"],
                "phone": payload["phone"],
                "role": payload["role"],
            },
        )
        db.commit()
    logger.info("Profile upserted from user.registered | user_id=%s", payload["id"])


async def start_consumer(db_factory) -> None:
    if not settings.KAFKA_ENABLED:
        logger.info("Kafka disabled — user profile consumer not started")
        return

    ssl_context = ssl.create_default_context()
    consumer = AIOKafkaConsumer(
        "user.registered",
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        security_protocol="SASL_SSL",
        sasl_mechanism="PLAIN",
        sasl_plain_username=settings.KAFKA_API_KEY,
        sasl_plain_password=settings.KAFKA_API_SECRET,
        ssl_context=ssl_context,
        group_id=settings.KAFKA_GROUP_ID,
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
    )

    await consumer.start()
    logger.info("User profile consumer started | topics=[user.registered]")

    try:
        async for msg in consumer:
            try:
                await _handle_user_registered(msg.value, db_factory)
            except Exception as e:
                logger.error("Error handling user.registered: %s", e)
    except asyncio.CancelledError:
        pass
    finally:
        await consumer.stop()
        logger.info("User profile consumer stopped")
