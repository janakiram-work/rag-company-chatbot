import secrets
import hashlib
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
import jwt
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from backend.database import (
    get_db,
    User,
    PasswordReset,
    Notification,
    AuditLog,
    log_audit,
    create_notification,
    utcnow,
)
from backend.schemas import (
    UserRegisterRequest,
    UserLoginRequest,
    TokenResponse,
    UserResponse,
    ForgotPasswordRequest,
    ResetPasswordRequest,
)
from backend.auth import (
    verify_password,
    get_password_hash,
    verify_password_async,
    get_password_hash_async,
    create_access_token,
    create_refresh_token,
    get_current_user,
    validate_password_strength,
    send_reset_email,
)
from backend.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    REFRESH_TOKEN_EXPIRE_DAYS,
    JWT_SECRET,
    JWT_ALGORITHM,
    COOKIE_SECURE,
    BEHIND_PROXY,
    PUBLIC_URL,
    SMTP_HOST,
)
from backend.rate_limiter import (
    limiter,
    get_login_key,
    check_login_rate_limit,
    record_failed_login,
    clear_failed_logins,
)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


def should_use_secure_cookie(request: Optional[Request] = None) -> bool:
    if COOKIE_SECURE:
        return True
    if request:
        if BEHIND_PROXY:
            proto = request.headers.get("x-forwarded-proto", "").lower()
            if proto == "https":
                return True
        if request.url.scheme == "https":
            return True
    return False





def set_auth_cookies(response: Response, access_token: str, refresh_token: str, request: Optional[Request] = None):
    sec = should_use_secure_cookie(request)
    response.set_cookie(
        key="access_token",
        value=access_token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        samesite="lax",
        secure=sec,
        path="/",
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=sec,
        path="/",
    )


@router.post("/register", response_model=TokenResponse)
async def register_user(
    request: Request,
    response: Response,
    payload: UserRegisterRequest,
    db: Session = Depends(get_db),
):
    # Validate password rules
    pw_err = validate_password_strength(payload.password)
    if pw_err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=pw_err)

    clean_email = payload.email.lower().strip()

    # Check email uniqueness
    existing_email = db.query(User).filter(func.lower(User.email) == clean_email).first()
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email already exists",
        )

    if payload.username:
        clean_username = payload.username.lower().strip()
        # Check username uniqueness
        existing_username = db.query(User).filter(func.lower(User.username) == clean_username).first()
        if existing_username:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username is already taken. Please choose another.",
            )
    else:
        import re
        base_user = re.sub(r"[^a-zA-Z0-9_.]", "", clean_email.split("@")[0])[:24]
        if len(base_user) < 3:
            base_user = f"user_{uuid.uuid4().hex[:6]}"
        clean_username = base_user
        collision = db.query(User).filter(func.lower(User.username) == clean_username.lower()).first()
        if collision:
            clean_username = f"{base_user[:20]}_{uuid.uuid4().hex[:4]}"

    # Assign avatar color
    palette = ["#10b981", "#3b82f6", "#8b5cf6", "#ec4899", "#f59e0b", "#06b6d4", "#6366f1"]
    avatar_color = palette[len(clean_email) % len(palette)]
    display_name = payload.display_name.strip() if payload.display_name else clean_username

    hashed_pw = await get_password_hash_async(payload.password)
    user = User(
        email=clean_email,
        username=clean_username,
        display_name=display_name,
        avatar_color=avatar_color,
        password_hash=hashed_pw,
        role="user",
        is_active=True,
        must_change_password=False,
        token_version=0,
        last_login_at=utcnow(),
        created_at=utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": str(user.id), "email": user.email, "role": user.role, "token_version": user.token_version})
    refresh = create_refresh_token({"sub": str(user.id), "email": user.email, "role": user.role, "token_version": user.token_version})
    set_auth_cookies(response, token, refresh, request)

    log_audit(db, user.id, "user_registered", target=user.email, details=f"Username: {user.username}")

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


@router.post("/login", response_model=TokenResponse)
async def login_user(
    request: Request,
    response: Response,
    payload: UserLoginRequest,
    db: Session = Depends(get_db),
):
    ident = (payload.identifier or payload.username or payload.email or "").strip().lower()
    if not ident:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email or username is required")

    key = get_login_key(request, ident)
    retry_after = check_login_rate_limit(key)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many attempts. Try again in {retry_after} seconds",
            headers={"Retry-After": str(retry_after)},
        )

    # Lookup user by email OR username (case-insensitive)
    user = db.query(User).filter(
        or_(func.lower(User.email) == ident, func.lower(User.username) == ident)
    ).first()

    is_valid = False
    if user:
        is_valid = await verify_password_async(payload.password, user.password_hash)

    if not user or not is_valid:
        retry_after = record_failed_login(key)
        if check_login_rate_limit(key) is not None:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many attempts. Try again in {retry_after} seconds",
                headers={"Retry-After": str(retry_after)},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # Friendly 403 on inactive/deactivated account
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been deactivated. Please contact an administrator.",
        )

    # Login succeeded - clear attempt counter and update last_login
    clear_failed_logins(key)
    user.last_login_at = utcnow()
    db.commit()

    token = create_access_token({"sub": str(user.id), "email": user.email, "role": user.role, "token_version": user.token_version})
    refresh = create_refresh_token({"sub": str(user.id), "email": user.email, "role": user.role, "token_version": user.token_version})
    set_auth_cookies(response, token, refresh, request)

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


@router.post("/forgot-password")
async def forgot_password(
    request: Request,
    payload: ForgotPasswordRequest,
    db: Session = Depends(get_db),
):
    ident = payload.identifier.strip().lower()
    key = f"forgot_{get_login_key(request, ident)}"
    retry_after = check_login_rate_limit(key)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many reset requests. Please try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    generic_msg = (
        "If an account matches that identifier, instructions have been sent "
        "or a request has been submitted to your administrator."
    )

    user = db.query(User).filter(
        or_(func.lower(User.email) == ident, func.lower(User.username) == ident)
    ).first()

    if user and user.is_active:
        # Generate single-use reset token
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        expires_at = utcnow() + timedelta(minutes=30)

        # Invalidate any older pending resets for this user
        db.query(PasswordReset).filter(
            PasswordReset.user_id == user.id,
            PasswordReset.status == "pending",
        ).update({"status": "expired"})

        pr = PasswordReset(
            user_id=user.id,
            token_hash=token_hash,
            status="pending",
            created_at=utcnow(),
            expires_at=expires_at,
        )
        db.add(pr)
        db.commit()

        if SMTP_HOST:
            base_url = PUBLIC_URL or f"{request.url.scheme}://{request.url.netloc}"
            reset_url = f"{base_url}/?token={raw_token}"
            threading.Thread(target=send_reset_email, args=(user.email, reset_url), daemon=True).start()
            log_audit(db, user.id, "password_reset_email_sent", target=user.email)
        else:
            # Create notification for all active admins to approve in panel
            active_admins = db.query(User).filter(User.role == "admin", User.is_active.is_(True)).all()
            for admin_u in active_admins:
                create_notification(
                    db,
                    user_id=admin_u.id,
                    type="password_reset_pending",
                    title="Password Reset Request",
                    body=f"User {user.display_name or user.username} ({user.email}) requested a password reset.",
                    link="/admin/users",
                )
            log_audit(db, user.id, "password_reset_pending_approval", target=user.email)

    # Always return exact same generic message (prevent enumeration)
    return {"message": generic_msg}


@router.post("/reset-password")
async def reset_password(
    payload: ResetPasswordRequest,
    db: Session = Depends(get_db),
):
    # Validate password rules
    pw_err = validate_password_strength(payload.new_password)
    if pw_err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=pw_err)

    token_hash = hashlib.sha256(payload.token.strip().encode("utf-8")).hexdigest()
    pr = db.query(PasswordReset).filter(
        PasswordReset.token_hash == token_hash,
        PasswordReset.status.in_(["pending", "approved"]),
    ).first()

    now = utcnow()
    is_expired = False
    if pr and pr.expires_at:
        exp = pr.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        is_expired = (exp < now)

    if not pr or is_expired:
        if pr and is_expired:
            pr.status = "expired"
            db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid, expired or already used password reset link.",
        )

    user = db.query(User).filter(User.id == pr.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Account not found or deactivated.")

    # Update password and invalidate all existing active sessions
    user.password_hash = get_password_hash(payload.new_password)
    user.token_version += 1
    user.must_change_password = False
    pr.status = "used"
    db.commit()

    log_audit(db, user.id, "password_reset_completed", target=user.email)

    return {"message": "Password has been successfully reset. You may now sign in with your new password."}


@router.post("/refresh")
def refresh_token(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    refresh = request.cookies.get("refresh_token")
    if not refresh:
        # Check Authorization header as fallback
        auth = request.headers.get("Authorization")
        if auth and auth.startswith("Bearer "):
            refresh = auth[7:].strip()

    if not refresh:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing refresh token",
        )

    try:
        payload = jwt.decode(refresh, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
            )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Expired or invalid refresh token",
        )

    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    tv = payload.get("token_version")
    if tv is not None and tv != user.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token invalidated. Please log in again.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been deactivated. Please contact an administrator.",
        )

    new_access = create_access_token({"sub": str(user.id), "email": user.email, "role": user.role, "token_version": user.token_version})
    sec = should_use_secure_cookie(request)
    response.set_cookie(
        key="access_token",
        value=new_access,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        samesite="lax",
        secure=sec,
        path="/",
    )

    return {
        "status": "success",
        "access_token": new_access,
        "token_type": "bearer",
        "user": UserResponse.model_validate(user),
    }


@router.post("/logout")
def logout_user(request: Request, response: Response):
    sec = should_use_secure_cookie(request)
    response.delete_cookie(key="access_token", path="/", samesite="lax", secure=sec)
    response.delete_cookie(key="refresh_token", path="/", samesite="lax", secure=sec)
    return {"status": "success", "message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
def get_profile(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)
