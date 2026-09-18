# user-service-cinema

Perfil de usuario del sistema Cinema: datos de contacto e historial de compras, separado de las credenciales de acceso.

## Responsabilidad

Este servicio posee `cinema_users.users` — el perfil (nombre, teléfono, rol) de cada cuenta, **sin** `password_hash`. Las credenciales y el login viven exclusivamente en `auth-service-cinema` (`cinema_auth`); este servicio nunca las toca.

El perfil se crea/actualiza de forma reactiva: no hay endpoint de registro propio, se puebla al escuchar `user.registered` publicado por `auth-service`. Esto mantiene una única fuente de verdad para el alta de usuarios.

También expone el historial de compras del usuario, leyendo directamente `cinema_booking` (propiedad de `booking-service-cinema`) en modo **solo lectura** — no crea tablas ni escribe ahí.

## Stack

FastAPI + SQLAlchemy 2.0 + PostgreSQL (`psycopg2`), Redis (cliente disponible, no crítico para el flujo actual), `aiokafka`, JWT vía `python-jose`. Puerto **8008**.

El esquema de `cinema_users` se crea con `Base.metadata.create_all` al arrancar (no usa Alembic, a diferencia de `booking-service-cinema` — ver `db_asuntos/docDBcambios.md`).

## API

Todos los endpoints bajo `/api/v1/users` requieren JWT (`Authorization: Bearer`), validado localmente contra `JWT_SECRET` (compartido con `auth-service`, no se llama por HTTP para verificar el token).

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/me` | Perfil del usuario autenticado |
| PUT | `/me` | Actualizar nombre, apellido o teléfono |
| DELETE | `/me` | Soft-delete del perfil + publica `user.deactivated` |
| PUT | `/me/password` | Cambiar contraseña — delega en `auth-service` vía HTTP, no valida ni almacena nada aquí |
| GET | `/me/purchases` | Historial de compras (lee `cinema_booking`, solo lectura) |

## Eventos Kafka

Ver `../kafka-schemas-cinema/event_contracts_operativos.md` para los contratos completos.

- **Consume** `user.registered` (de `auth-service`) → crea o actualiza el perfil en `cinema_users` (idempotente, `ON CONFLICT DO UPDATE`).
- **Publica** `user.deactivated` (al hacer `DELETE /me`) → `auth-service` lo consume para bloquear futuros logins en `cinema_auth`.

Ninguno de los dos está detallado como sección propia en `event_contracts_operativos.md` (solo en su tabla de schemas) — son eventos simples de ciclo de vida de usuario, sin la complejidad de la saga de compra.

## Variables de entorno clave

| Variable | Para qué sirve |
|---|---|
| `DATABASE_URL` | Conexión a `cinema_users`, propia de este servicio |
| `BOOKING_DATABASE_URL` | Conexión de solo lectura a `cinema_booking`, para `GET /me/purchases` |
| `JWT_SECRET` / `JWT_ALGORITHM` | Deben coincidir con `auth-service` — este servicio valida tokens localmente, no llama a `/verify-token` |
| `AUTH_SERVICE_URL` | URL de `auth-service`, usada solo por `PUT /me/password` (delega el cambio de contraseña) |
| `REDIS_URL` | Cliente Redis disponible; no es requisito duro del arranque |
| `KAFKA_ENABLED` / `KAFKA_BOOTSTRAP_SERVERS` / `KAFKA_API_KEY` / `KAFKA_API_SECRET` | Confluent Cloud — ver `../IMPLEMENTATION-GUIDE.md` Fase 3 |
| `BACKEND_CORS_ORIGINS` | Orígenes permitidos, admite lista JSON o CSV |

`AUTH_SERVICE_URL` es un campo requerido (sin default) — si queda vacío el servicio arranca pero `PUT /me/password` falla en runtime. En local debe apuntar a `http://auth-service:8005` (corregido 2026-09-18, ver `../IMPLEMENTATION-GUIDE.md` Fase 0).

## Dependencias

- **auth-service** — única llamada HTTP saliente (`PUT /api/v1/auth/password`), y origen del evento `user.registered`.
- **cinema_booking** — leída directamente (no vía API de `booking-service`), acoplamiento de datos compartido documentado en `db_asuntos/docDBcambios.md`.
- **Confluent Cloud** — productor y consumidor Kafka.

## Correr en local

Standalone:

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8008
```

Requiere `.env` con al menos `DATABASE_URL` y `AUTH_SERVICE_URL`. Como parte del stack completo, ver `../infra-cinema/docker-compose.yml` y `../IMPLEMENTATION-GUIDE.md` (Fase 4-5) para el flujo de arranque y restauración de datos.
