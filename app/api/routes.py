# app/api/routes.py
from typing import List

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.api.dependencies import get_current_user, get_current_token
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
            )
        except httpx.TransportError:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "booking-service no disponible")

    if resp.status_code != status.HTTP_200_OK:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Error al consultar el historial de compras")

    return [MyPurchaseResponse(**item) for item in resp.json()]
