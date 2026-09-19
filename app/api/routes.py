# app/api/routes.py
from typing import List

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.api.dependencies import get_current_user, get_current_token, verify_internal_token
from app.models.user import User
from app.schemas.user import UserProfileResponse, UserUpdate, MyPurchaseResponse
from app.services.user_service import UserService

router = APIRouter(prefix="/api/v1/users", tags=["Users"])


@router.get("/me", response_model=UserProfileResponse)
async def get_profile(current_user: User = Depends(get_current_user)):
    """Perfil del usuario autenticado (datos en cinema_users)."""
    return UserProfileResponse.from_orm(current_user)


@router.put("/me", response_model=UserProfileResponse)
async def update_profile(
    data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Actualizar nombre, apellido o teléfono."""
    updated = UserService.update_profile(db, current_user.id, data)
    return UserProfileResponse.from_orm(updated)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Soft-delete en cinema_users + publica user.deactivated →
    auth-service desactiva en cinema_auth para bloquear futuros logins.
    """
    await UserService.delete_account(db, current_user.id)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(..., description="Contraseña actual")
    new_password: str = Field(..., min_length=6, description="Nueva contraseña (mínimo 6 caracteres)")


@router.put("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    data: PasswordChangeRequest,
    token: str = Depends(get_current_token),
    _: User = Depends(get_current_user),
):
    """
    Cambiar contraseña del usuario autenticado.
    Delega la validación y actualización a auth-service, que es el dueño de las credenciales.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.put(
            f"{settings.AUTH_SERVICE_URL}/api/v1/auth/password",
            json={"current_password": data.current_password, "new_password": data.new_password},
            headers={"Authorization": f"Bearer {token}"},
        )

    if resp.status_code == status.HTTP_400_BAD_REQUEST:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, resp.json().get("detail", "Contraseña actual incorrecta"))
    if resp.status_code == status.HTTP_401_UNAUTHORIZED:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No autorizado")
    if resp.status_code not in (status.HTTP_204_NO_CONTENT, status.HTTP_200_OK):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Error al cambiar la contraseña. Intenta de nuevo.")


@router.get("/me/purchases", response_model=List[MyPurchaseResponse])
async def get_my_purchases(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    purchase_status: str = Query(None, alias="status"),
    current_user: User = Depends(get_current_user),
):
    """
    Historial de compras del usuario autenticado.
    Delega en booking-service (dueño de cinema_booking) vía HTTP interno —
    este servicio ya no lee esa base directamente (ver ARCHITECTURE.md,
    "Aislamiento de base de datos por servicio").
    """
    params = {"skip": skip, "limit": limit}
    if purchase_status:
        params["status"] = purchase_status

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                f"{settings.BOOKING_SERVICE_URL}/api/v1/purchases/internal/users/{current_user.id}/purchases",
                params=params,
                headers={"X-Internal-Token": settings.INTERNAL_SERVICE_TOKEN},
            )
        except httpx.TransportError:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "booking-service no disponible")

    if resp.status_code != status.HTTP_200_OK:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Error al consultar el historial de compras")

    return [MyPurchaseResponse(**item) for item in resp.json()]


# ── Internas, para admin-service (ver ARCHITECTURE.md, "Aislamiento de ────────
# base de datos por servicio", caso 2). Protegidas por X-Internal-Token, no
# por JWT de usuario final — admin-service ya validó al admin autenticado.
# El orden de declaración importa: /internal/lookup debe ir antes que
# /internal/{user_id} para que no lo capture como user_id="lookup".

@router.get("/internal", response_model=List[UserProfileResponse], dependencies=[Depends(verify_internal_token)])
async def list_users_internal(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    include_inactive: bool = Query(False),
    search: str = Query(None),
    db: Session = Depends(get_db),
):
    users = UserService.list_users(db, skip, limit, include_inactive, search)
    return [UserProfileResponse.from_orm(u) for u in users]


@router.get("/internal/lookup", response_model=UserProfileResponse, dependencies=[Depends(verify_internal_token)])
async def get_user_by_email_internal(
    email: str = Query(...),
    db: Session = Depends(get_db),
):
    """Resuelve email → perfil completo. Usado por admin-service para autenticación/autorización."""
    user = UserService.get_by_email(db, email)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado")
    return UserProfileResponse.from_orm(user)


@router.get("/internal/{user_id}", response_model=UserProfileResponse, dependencies=[Depends(verify_internal_token)])
async def get_user_internal(
    user_id: int,
    db: Session = Depends(get_db),
):
    user = UserService.get_profile(db, user_id)
    return UserProfileResponse.from_orm(user)


@router.patch("/internal/{user_id}/toggle", response_model=UserProfileResponse, dependencies=[Depends(verify_internal_token)])
async def toggle_user_internal(
    user_id: int,
    db: Session = Depends(get_db),
):
    user = await UserService.toggle_status(db, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado")
    return UserProfileResponse.from_orm(user)
