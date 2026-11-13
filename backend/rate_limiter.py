import time
from collections import defaultdict
from typing import Optional
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address
import jwt

from backend.config import JWT_SECRET, JWT_ALGORITHM

failed_logins = defaultdict(list)
LOGIN_LIMIT = 10
LOGIN_WINDOW_SEC = 60


def get_login_key(request: Request, email: str) -> str:
    ip = request.client.host if request.client else "127.0.0.1"
    clean_email = email.lower().strip()
    return f"{ip}:{clean_email}"


def check_login_rate_limit(key: str) -> Optional[int]:
    now = time.time()
    attempts = [t for t in failed_logins[key] if now - t < LOGIN_WINDOW_SEC]
    failed_logins[key] = attempts
    if len(attempts) >= LOGIN_LIMIT:
        oldest = attempts[0]
        retry_after = max(1, int(LOGIN_WINDOW_SEC - (now - oldest)))
        return retry_after
    return None


def record_failed_login(key: str) -> int:
    now = time.time()
    attempts = [t for t in failed_logins[key] if now - t < LOGIN_WINDOW_SEC]
    attempts.append(now)
    failed_logins[key] = attempts
    oldest = attempts[0]
    return max(1, int(LOGIN_WINDOW_SEC - (now - oldest)))


def clear_failed_logins(key: str):
    failed_logins.pop(key, None)


def get_user_id_or_ip(request: Request) -> str:
    """Extract authenticated user ID from Authorization header or access_token cookie, falling back to remote IP."""
    token = None
    auth = request.headers.get("Authorization")
    if auth and auth.startswith("Bearer "):
        token = auth[7:].strip()
    if not token:
        token = request.cookies.get("access_token")

    if token:
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            user_id = payload.get("sub")
            if user_id is not None:
                return f"user:{user_id}"
        except Exception:
            pass

    return get_remote_address(request)


limiter = Limiter(key_func=get_remote_address)
