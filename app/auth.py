from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import Cookie, Depends, HTTPException
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from app.config import settings
from app.database import get_db
from app.models import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_access_token(user_id: int, email: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode({"sub": str(user_id), "email": email, "role": role, "exp": expire},
                      settings.secret_key, algorithm=settings.jwt_algorithm)

def get_current_user(access_token: Optional[str] = Cookie(default=None),
                     db: Session = Depends(get_db)) -> User:
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
