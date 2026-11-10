"""Token-based JWT Authentication and Role Scoping for ecom.

Handles bcrypt password hashing, JWT creation/verification, role enforcement,
and auth endpoints.
"""

from datetime import datetime, timedelta, timezone
import logging
from typing import Optional

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import User
from app.db.session import get_db_session

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)
router = APIRouter(prefix="/api/auth", tags=["Authentication"])


# ─── Pydantic Schemas ────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: str
    name: str
    email: str
    role: str
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ─── Password Hashing & Verification ──────────────────────────────────────────

def hash_password(password: str) -> str:
    """Hash password using direct bcrypt."""
    pw_bytes = password.encode("utf-8")[:72]  # bcrypt max length
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pw_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against bcrypt hash."""
    pw_bytes = plain_password.encode("utf-8")[:72]
    hash_bytes = hashed_password.encode("utf-8")
    try:
        return bcrypt.checkpw(pw_bytes, hash_bytes)
    except Exception as e:
        logger.error("Error during password verification: %s", e)
        return False


# ─── JWT Generation & Parsing ─────────────────────────────────────────────────

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    return encoded_jwt


def decode_access_token(token: str) -> dict:
    """Decode and validate JWT access token."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ─── FastAPI Dependencies ─────────────────────────────────────────────────────

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
    session: AsyncSession = Depends(get_db_session),
) -> User:
    """Extract and validate current authenticated user from Bearer token."""
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing or invalid format.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(credentials.credentials)
    user_id: Optional[str] = payload.get("user_id")
    email: Optional[str] = payload.get("email")

    if not user_id or not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token payload is missing required identity claims.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User belonging to this token no longer exists.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Require user to hold 'admin' role."""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Admin privileges required.",
        )
    return current_user


# ─── Auth Endpoints ───────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Authenticate user with email/password and issue JWT."""
    result = await session.execute(
        select(User).where(User.email == request.email.lower().strip())
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(
        data={
            "user_id": user.id,
            "email": user.email,
            "role": user.role,
            "name": user.name,
        }
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserOut.model_validate(user),
    )


@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)):
    """Return currently authenticated user profile."""
    return UserOut.model_validate(current_user)


@router.get("/users", response_model=list[UserOut])
async def list_quick_switch_users(session: AsyncSession = Depends(get_db_session)):
    """List available demo users for frontend quick switching."""
    result = await session.execute(select(User).order_by(User.role.asc(), User.name.asc()))
    users = result.scalars().all()
    return [UserOut.model_validate(u) for u in users]
