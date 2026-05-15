from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional
import hashlib
import hmac
import os

from fastapi import Cookie, Depends, HTTPException
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from app.config import settings
from app.database import get_db
from app.models import User


def hash_password(password: str) -> str:
    """Hash password using SHA-256 with a random salt. No length limit."""
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 310000)
    return salt.hex() + ':' + key.hex()


def verify_password(plain: str, stored: str) -> bool:
    """Verify a password against a stored hash."""
    try:
        salt_hex, key_hex = stored.split(':')
        salt = bytes.fromhex(salt_hex)
        key = bytes.fromhex(key_hex)
        new_key = hashlib.pbkdf2_hmac('sha256', plain.encode('utf-8'), salt, 310000)
        return hmac.compare_digest(key, new_key)
    except Exception:
        return False


def create_access_token(user_id: int, email: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode(
        {"sub": str(user_id), "email": email, "role": role, "exp": expire},
        settings.secret_key, algorithm=settings.jwt_algorithm
    )


def get_current_user(
    access_token: Optional[str] = Cookie(default=None),
    db: Session = Depends(get_db)
) -> User:
    if not access_token:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    try:
        payload = jwt.decode(access_token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    user = db.query(User).filter(User.id == int(payload["sub"])).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or deactivated.")
    return user


def require_role(*roles: str):
    def checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(status_code=403, detail="You don't have permission to do this.")
        return current_user
    return checker


require_admin   = require_role("admin")
require_teacher = require_role("admin", "teacher")
require_any     = require_role("admin", "teacher", "student")
