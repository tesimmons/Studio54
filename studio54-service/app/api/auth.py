"""
Auth API Router
Login, password management, and user administration endpoints
"""
import uuid
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime, timezone
from pydantic import BaseModel, Field
import logging

from app.database import get_db
from app.models.user import User, UserRole
import copy
from app.auth import (
    hash_password, verify_password, create_access_token,
    get_current_user, require_director,
)
from sqlalchemy.dialects.postgresql import JSONB
from app.security import rate_limit

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Pydantic schemas ---

class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=4)


class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=100)
    password: str = Field(..., min_length=4)
    display_name: Optional[str] = None
    role: str = UserRole.PARTYGOER


class UpdateUserRequest(BaseModel):
    display_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    reset_password: Optional[str] = Field(None, min_length=4)


def _user_response(user: User) -> dict:
    return {
        "id": str(user.id),
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "is_active": user.is_active,
        "must_change_password": user.must_change_password,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


# --- Public ---

@router.post("/auth/login")
@rate_limit("20/minute")
async def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate and return JWT access token."""
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    user.last_login_at = datetime.now(timezone.utc)
    db.commit()

    token = create_access_token(str(user.id), user.username, user.role)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": _user_response(user),
    }


# --- Authenticated ---

@router.post("/auth/change-password")
@rate_limit("10/minute")
async def change_password(
    request: Request,
    body: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Change current user's password."""
    if not verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")

    current_user.password_hash = hash_password(body.new_password)
    current_user.must_change_password = False
    current_user.updated_at = datetime.now(timezone.utc)
    db.commit()

    # Return new token so client doesn't need to re-login
    token = create_access_token(str(current_user.id), current_user.username, current_user.role)
    return {"message": "Password changed successfully", "access_token": token}


@router.get("/auth/me")
@rate_limit("60/minute")
async def get_me(request: Request, current_user: User = Depends(get_current_user)):
    """Get current user profile."""
    return _user_response(current_user)


@router.get("/auth/me/preferences")
@rate_limit("60/minute")
async def get_preferences(request: Request, current_user: User = Depends(get_current_user)):
    """Get current user's preferences."""
    return current_user.preferences or {}


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base, returning a new dict."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


@router.put("/auth/me/preferences")
@rate_limit("30/minute")
async def update_preferences(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Deep-merge request body into current user's preferences."""
    body = await request.json()
    existing = current_user.preferences or {}
    merged = _deep_merge(existing, body)
    current_user.preferences = merged
    current_user.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(current_user)
    return current_user.preferences


# --- Director-only user management ---

@router.get("/auth/users")
@rate_limit("60/minute")
async def list_users(
    request: Request,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db),
):
    """List all users. Director only."""
    users = db.query(User).order_by(User.created_at).all()
    return {"users": [_user_response(u) for u in users]}


@router.post("/auth/users", status_code=status.HTTP_201_CREATED)
@rate_limit("30/minute")
async def create_user(
    request: Request,
    body: CreateUserRequest,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db),
):
    """Create a new user. Director only."""
    if body.role not in UserRole.ALL:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid role. Must be one of: {UserRole.ALL}")

    existing = db.query(User).filter(User.username == body.username).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already taken")

    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        display_name=body.display_name or body.username,
        role=body.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    logger.info(f"User created: {user.username} (role: {user.role}) by {current_user.username}")
    return _user_response(user)


@router.patch("/auth/users/{user_id}")
@rate_limit("30/minute")
async def update_user(
    request: Request,
    user_id: str,
    body: UpdateUserRequest,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db),
):
    """Update a user. Director only. Cannot demote self."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    is_self = str(user.id) == str(current_user.id)

    if body.role is not None:
        if body.role not in UserRole.ALL:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid role")
        if is_self and body.role != current_user.role:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot change your own role")
        user.role = body.role

    if body.is_active is not None:
        if is_self and not body.is_active:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot deactivate your own account")
        user.is_active = body.is_active

    if body.display_name is not None:
        user.display_name = body.display_name

    if body.reset_password is not None:
        user.password_hash = hash_password(body.reset_password)
        user.must_change_password = True

    user.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)

    logger.info(f"User updated: {user.username} by {current_user.username}")
    return _user_response(user)


@router.delete("/auth/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
@rate_limit("10/minute")
async def delete_user(
    request: Request,
    user_id: str,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db),
):
    """Delete a user. Director only. Cannot delete self."""
    if str(current_user.id) == user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete your own account")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    logger.info(f"User deleted: {user.username} by {current_user.username}")
    db.delete(user)
    db.commit()
