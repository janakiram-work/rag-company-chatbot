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
    assert verify_password("Admin@123", admin.password_hash) is True

    user = db.query(User).filter(User.email == "user@abctechnologies.com").first()
    assert user is not None
    assert user.role == "user"
    assert verify_password("User@123", user.password_hash) is True


def test_jwt_token_generation():
    token = create_access_token({"sub": 42, "role": "admin"})
    assert isinstance(token, str)
    assert len(token) > 20
