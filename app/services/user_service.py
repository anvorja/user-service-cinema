# app/services/user_service.py
import logging
from typing import List, Optional
from sqlalchemy import or_
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.user import User
from app.schemas.user import UserUpdate

logger = logging.getLogger(__name__)


class UserService:

    @staticmethod
    def get_profile(db: Session, user_id: int) -> User:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado")
        return user

    @staticmethod
    def get_by_email(db: Session, email: str) -> Optional[User]:
        """Usado por admin-service para resolver auth/autorización (GET /internal/users/lookup)."""
        return db.query(User).filter(User.email == email).first()

    @staticmethod
    def list_users(
        db: Session,
        skip: int = 0,
        limit: int = 20,
        include_inactive: bool = False,
        search: Optional[str] = None,
    ) -> List[User]:
        """Usado por admin-service (GET /internal/users) — antes era una query directa a cinema_users."""
        q = db.query(User)
        if not include_inactive:
            q = q.filter(User.is_active == True)
        if search:
            term = f"%{search.strip()}%"
            q = q.filter(
                or_(
                    User.email.ilike(term),
                    User.first_name.ilike(term),
                    User.last_name.ilike(term),
                )
            )
        return q.offset(skip).limit(limit).all()

    @staticmethod
    async def toggle_status(db: Session, user_id: int) -> Optional[User]:
        """
        Activa / desactiva un usuario. Usado por admin-service (PATCH
        /internal/users/{id}/toggle) — la regla de negocio "un admin no
        puede desactivarse a sí mismo" vive en admin-service, que es quien
        conoce al admin autenticado; aquí solo se aplica el cambio de estado.
        """
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return None

        was_active = user.is_active
        user.is_active = not user.is_active
        db.commit()
        db.refresh(user)

        if was_active and not user.is_active:
            try:
                from app.kafka.producer import publish_event
                await publish_event("user.deactivated", {"user_id": user_id})
            except Exception as e:
                logger.warning("Could not publish user.deactivated: %s", e)

        return user

    @staticmethod
    def update_profile(db: Session, user_id: int, data: UserUpdate) -> User:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado")

        for field, value in data.model_dump(exclude_unset=True).items():
            if value is not None:
                setattr(user, field, value)

        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    async def delete_account(db: Session, user_id: int) -> None:
        """
        Soft-delete en cinema_users + publica user.deactivated para que
        auth-service invalide el acceso en cinema_auth.
        """
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado")

        user.is_active = False
        db.commit()

        try:
            from app.kafka.producer import publish_event
            await publish_event("user.deactivated", {"user_id": user_id})
        except Exception as e:
            logger.warning("Could not publish user.deactivated: %s", e)
