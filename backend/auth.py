from datetime import datetime, timedelta, timezone
from typing import Optional
import asyncio
import jwt
import bcrypt
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from backend.config import (
    JWT_SECRET,
    JWT_ALGORITHM,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    REFRESH_TOKEN_EXPIRE_DAYS,
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    APP_ENV,
    SEED_DEMO_USERS,
    DEMO_ADMIN_EMAIL,
    DEMO_ADMIN_PASSWORD,
    DEMO_USER_EMAIL,
    DEMO_USER_PASSWORD,
)
from backend.database import get_db, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        pw_bytes = plain_password.encode("utf-8")[:72]
        hash_bytes = hashed_password.encode("utf-8")
        return bcrypt.checkpw(pw_bytes, hash_bytes)
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    pw_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pw_bytes, salt).decode("utf-8")


async def verify_password_async(plain_password: str, hashed_password: str) -> bool:
    return await asyncio.to_thread(verify_password, plain_password, hashed_password)


async def get_password_hash_async(password: str) -> str:
    return await asyncio.to_thread(get_password_hash, password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def get_user_from_token_str(token_str: str, db: Session) -> Optional[User]:
    """Decodes JWT string and returns User, or None if invalid/expired/inactive."""
    try:
        payload = jwt.decode(token_str, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        if user_id is not None:
            user = db.query(User).filter(User.id == int(user_id)).first()
            if user and user.is_active:
                tv = payload.get("token_version")
                if tv is None or tv == user.token_version:
                    return user
    except Exception:
        return None
    return None


def get_current_user(
    request: Request,
    bearer_token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    token = bearer_token
    if not token:
        token = request.cookies.get("access_token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing subject",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except jwt.PyJWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"User {user_id} not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Invalidate session if token_version mismatch (password changed or reset)
    token_version = payload.get("token_version")
    if token_version is not None and token_version != user.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session invalidated. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Inactive / deactivated user
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been deactivated. Please contact an administrator.",
        )

    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Admin privileges required",
        )
    return current_user


FORBIDDEN_ADMIN_PASSWORDS = {"admin@123", "admin123", "password"}


def validate_password_strength(password: str) -> Optional[str]:
    """Returns error message if password does not meet requirements, else None."""
    if len(password) < 8:
        return "Password must be at least 8 characters long."
    if password.lower() in FORBIDDEN_ADMIN_PASSWORDS or password.lower() in {"12345678", "qwerty123", "password123"}:
        return "This password is too common or easily guessed. Please choose a stronger password."
    return None


def send_reset_email(to_email: str, reset_url: str) -> bool:
    """Send reset email if SMTP configured, else log."""
    import smtplib
    from email.mime.text import MIMEText
    from backend.config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, SMTP_TLS, COMPANY_NAME
    if not SMTP_HOST:
        return False

    msg = MIMEText(
        f"Hello,\n\nA password reset request was received for your account.\n\n"
        f"Click the link below to reset your password (valid for 30 minutes):\n{reset_url}\n\n"
        f"If you did not request this, please ignore this email.\n"
    )
    msg["Subject"] = f"Password Reset Request"
    msg["From"] = SMTP_FROM or SMTP_USER
    msg["To"] = to_email

    try:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10)
        if SMTP_TLS:
            server.starttls()
        if SMTP_USER and SMTP_PASSWORD:
            server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"[SMTP Error] Failed to send email to {to_email}: {e}")
        return False


def seed_default_users(db: Session):
    """Seed the admin from ADMIN_EMAIL and ADMIN_PASSWORD only if configured and valid.
    Never seed any baseline or demo user unless SEED_DEMO_USERS=true.
    """
    # 1. Configured Admin Account
    if not ADMIN_EMAIL or not ADMIN_PASSWORD:
        print("[startup INFO] ADMIN_EMAIL or ADMIN_PASSWORD not configured. Initial admin account seeding skipped.")
    elif len(ADMIN_PASSWORD) < 8 or ADMIN_PASSWORD.lower() in FORBIDDEN_ADMIN_PASSWORDS:
        print(
            "[startup ERROR] ADMIN_PASSWORD was refused because it is shorter than 8 characters "
            "or matches a known weak default. Admin account seeding skipped."
        )
    else:
        existing_admin = db.query(User).filter(User.email == ADMIN_EMAIL).first()
        if not existing_admin:
            admin_user = User(
                email=ADMIN_EMAIL,
                password_hash=get_password_hash(ADMIN_PASSWORD),
                role="admin",
            )
            db.add(admin_user)
            db.flush()

    # 2. Demo User Accounts (only when SEED_DEMO_USERS=true, refused in production)
    if SEED_DEMO_USERS:
        if APP_ENV == "production":
            print("[startup ERROR] Refusing SEED_DEMO_USERS=true when APP_ENV=production. Demo user seeding aborted.")
        elif not (DEMO_ADMIN_EMAIL and DEMO_ADMIN_PASSWORD and DEMO_USER_EMAIL and DEMO_USER_PASSWORD):
            print(
                "[startup INFO] SEED_DEMO_USERS=true but one or more required demo environment variables "
                "are missing (DEMO_ADMIN_EMAIL, DEMO_ADMIN_PASSWORD, DEMO_USER_EMAIL, DEMO_USER_PASSWORD). "
                "Skipping demo user seeding."
            )
        else:
            # Seed demo admin if not exists
            demo_admin = db.query(User).filter(User.email == DEMO_ADMIN_EMAIL).first()
            if not demo_admin:
                db.add(User(
                    email=DEMO_ADMIN_EMAIL,
                    password_hash=get_password_hash(DEMO_ADMIN_PASSWORD),
                    role="admin",
                ))
                db.flush()
            # Seed demo regular user if not exists
            demo_user = db.query(User).filter(User.email == DEMO_USER_EMAIL).first()
            if not demo_user:
                db.add(User(
                    email=DEMO_USER_EMAIL,
                    password_hash=get_password_hash(DEMO_USER_PASSWORD),
                    role="user",
                ))
                db.flush()

    db.commit()
