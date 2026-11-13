import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.routers.auth import router as auth_router
from backend.auth import seed_default_users
from backend.rate_limiter import limiter

# Create isolated test SQLite app
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

app = FastAPI()
app.state.limiter = limiter
app.include_router(auth_router)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)


def test_auth_routes():
    # 1. Seed users
    with TestingSessionLocal() as session:
        seed_default_users(session)

    # 2. Register regular user
    reg_res = client.post(
        "/api/auth/register",
        json={"email": "newemployee@abctechnologies.com", "password": "SecurePassword123"},
    )
    assert reg_res.status_code == 200, reg_res.text
    data = reg_res.json()
    assert "access_token" in data
    # Security requirement: /register ALWAYS creates role=user
    assert data["user"]["role"] == "user"
    assert data["user"]["email"] == "newemployee@abctechnologies.com"

    # 3. Duplicate registration rejected
    dup_res = client.post(
        "/api/auth/register",
        json={"email": "newemployee@abctechnologies.com", "password": "SecurePassword123"},
    )
    assert dup_res.status_code == 400

    # 4. Login with newly registered user
    login_res = client.post(
        "/api/auth/login",
        json={"email": "newemployee@abctechnologies.com", "password": "SecurePassword123"},
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]

    # 5. Get current profile via /me
    me_res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    assert me_res.json()["email"] == "newemployee@abctechnologies.com"

    # 6. Login with seeded admin
    admin_login = client.post(
        "/api/auth/login",
        json={"email": "admin@abctechnologies.com", "password": "Admin@123"},
    )
    assert admin_login.status_code == 200
    assert admin_login.json()["user"]["role"] == "admin"

    # 7. Login with invalid password
    bad_login = client.post(
        "/api/auth/login",
        json={"email": "admin@abctechnologies.com", "password": "WrongPassword"},
    )
    assert bad_login.status_code == 401

    # 8. Verify cookies set on login
    assert "access_token" in admin_login.cookies
    assert "refresh_token" in admin_login.cookies

    # 9. Verify cookie authentication on /me (without Authorization header)
    cookie_me = client.get("/api/auth/me", cookies={"access_token": admin_login.cookies["access_token"]})
    assert cookie_me.status_code == 200
    assert cookie_me.json()["role"] == "admin"

    # 10. Refresh token endpoint
    refresh_res = client.post("/api/auth/refresh", cookies={"refresh_token": admin_login.cookies["refresh_token"]})
    assert refresh_res.status_code == 200
    assert "access_token" in refresh_res.json()
    assert "access_token" in refresh_res.cookies

    # 11. Logout endpoint
    logout_res = client.post("/api/auth/logout")
    assert logout_res.status_code == 200
