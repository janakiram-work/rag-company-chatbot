import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.database import Base, User
from backend.auth import (
    verify_password,
    get_password_hash,
    create_access_token,
    seed_default_users,
)

# Test in-memory SQLite database
TEST_DB_URL = "sqlite:///:memory:"
engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


def test_password_hashing():
    pw = "SecretPass123!"
    h = get_password_hash(pw)
    assert h != pw
    assert verify_password(pw, h) is True
    assert verify_password("WrongPass", h) is False


def test_seed_default_users(db):
    seed_default_users(db)

    admin = db.query(User).filter(User.email == "admin@abctechnologies.com").first()
    assert admin is not None
    assert admin.role == "admin"
    admin_pw = os.getenv("ADMIN_PASSWORD", "AdminTestSecurePass!2026")
    assert verify_password(admin_pw, admin.password_hash) is True

    user = db.query(User).filter(User.email == "user@abctechnologies.com").first()
    assert user is not None
    assert user.role == "user"
    user_pw = os.getenv("DEMO_USER_PASSWORD", "UserTestSecurePass!2026")
    assert verify_password(user_pw, user.password_hash) is True


def test_jwt_token_generation():
    token = create_access_token({"sub": 42, "role": "admin"})
    assert isinstance(token, str)
    assert len(token) > 20


def test_seed_security_validations(db, monkeypatch):
    import backend.auth as auth_mod

    # 1. Refuse password shorter than 8 chars
    monkeypatch.setattr(auth_mod, "ADMIN_EMAIL", "short_pw_admin@test.com")
    monkeypatch.setattr(auth_mod, "ADMIN_PASSWORD", "short")
    monkeypatch.setattr(auth_mod, "SEED_DEMO_USERS", False)
    auth_mod.seed_default_users(db)
    assert db.query(User).filter(User.email == "short_pw_admin@test.com").first() is None

    # 2. Refuse known default passwords (e.g. admin123, password)
    monkeypatch.setattr(auth_mod, "ADMIN_EMAIL", "default_pw_admin@test.com")
    monkeypatch.setattr(auth_mod, "ADMIN_PASSWORD", "admin123")
    auth_mod.seed_default_users(db)
    assert db.query(User).filter(User.email == "default_pw_admin@test.com").first() is None

    monkeypatch.setattr(auth_mod, "ADMIN_PASSWORD", "password")
    auth_mod.seed_default_users(db)
    assert db.query(User).filter(User.email == "default_pw_admin@test.com").first() is None

    # 3. Refuse SEED_DEMO_USERS when APP_ENV=production
    monkeypatch.setattr(auth_mod, "ADMIN_EMAIL", "")
    monkeypatch.setattr(auth_mod, "ADMIN_PASSWORD", "")
    monkeypatch.setattr(auth_mod, "APP_ENV", "production")
    monkeypatch.setattr(auth_mod, "SEED_DEMO_USERS", True)
    monkeypatch.setattr(auth_mod, "DEMO_ADMIN_EMAIL", "prod_demo@test.com")
    monkeypatch.setattr(auth_mod, "DEMO_ADMIN_PASSWORD", "SecureDemoPass!2026")
    monkeypatch.setattr(auth_mod, "DEMO_USER_EMAIL", "prod_user@test.com")
    monkeypatch.setattr(auth_mod, "DEMO_USER_PASSWORD", "SecureDemoUser!2026")
    auth_mod.seed_default_users(db)
    assert db.query(User).filter(User.email == "prod_demo@test.com").first() is None

    # 4. Skip demo seeding if any DEMO_* variable is missing
    monkeypatch.setattr(auth_mod, "APP_ENV", "development")
    monkeypatch.setattr(auth_mod, "DEMO_USER_PASSWORD", "")
    auth_mod.seed_default_users(db)
    assert db.query(User).filter(User.email == "prod_demo@test.com").first() is None
