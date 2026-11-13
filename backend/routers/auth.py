import jwt
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from sqlalchemy.orm import Session

from backend.database import get_db, User
from backend.schemas import UserRegisterRequest, UserLoginRequest, TokenResponse, UserResponse
from backend.auth import (
    verify_password,
    get_password_hash,
    create_access_token,
    create_refresh_token,
    get_current_user,
)
from backend.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    REFRESH_TOKEN_EXPIRE_DAYS,
    JWT_SECRET,
    JWT_ALGORITHM,
    COOKIE_SECURE,
)
from backend.rate_limiter import (
    limiter,
    get_login_key,
    check_login_rate_limit,
    record_failed_login,
    clear_failed_logins,
)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


def set_auth_cookies(response: Response, access_token: str, refresh_token: str):
    response.set_cookie(
        key="access_token",
        value=access_token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        path="/",
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        path="/",
    )


@router.post("/register", response_model=TokenResponse)
def register_user(
    request: Request,
    response: Response,
    payload: UserRegisterRequest,
    db: Session = Depends(get_db),
):
    # Check if email is taken
    existing = db.query(User).filter(User.email == payload.email.lower().strip()).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email already exists",
        )

    # Security requirement: /register ALWAYS creates role=user
    user = User(
        email=payload.email.lower().strip(),
        password_hash=get_password_hash(payload.password),
        role="user",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": str(user.id), "email": user.email, "role": user.role})
    refresh = create_refresh_token({"sub": str(user.id), "email": user.email, "role": user.role})
    set_auth_cookies(response, token, refresh)

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


@router.post("/login", response_model=TokenResponse)
def login_user(
    request: Request,
    response: Response,
    payload: UserLoginRequest,
    db: Session = Depends(get_db),
):
    key = get_login_key(request, payload.email)
    retry_after = check_login_rate_limit(key)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many attempts. Try again in {retry_after} seconds",
            headers={"Retry-After": str(retry_after)},
        )

    user = db.query(User).filter(User.email == payload.email.lower().strip()).first()
    if not user or not verify_password(payload.password, user.password_hash):
        retry_after = record_failed_login(key)
        # Check if this failure hit the limit
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

    # Login succeeded - clear any previous failed attempt counter
    clear_failed_logins(key)

    token = create_access_token({"sub": str(user.id), "email": user.email, "role": user.role})
    refresh = create_refresh_token({"sub": str(user.id), "email": user.email, "role": user.role})
    set_auth_cookies(response, token, refresh)

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


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

    new_access = create_access_token({"sub": str(user.id), "email": user.email, "role": user.role})
    response.set_cookie(
        key="access_token",
        value=new_access,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        path="/",
    )

    return {
        "status": "success",
        "access_token": new_access,
        "token_type": "bearer",
        "user": UserResponse.model_validate(user),
    }


@router.post("/logout")
def logout_user(response: Response):
    response.delete_cookie(key="access_token", path="/")
    response.delete_cookie(key="refresh_token", path="/")
    return {"status": "success", "message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
def get_profile(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)
