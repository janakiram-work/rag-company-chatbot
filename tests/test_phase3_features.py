import os
import json
import uuid
import secrets
import hashlib
import datetime
from datetime import timezone
from io import BytesIO
import pytest
from PIL import Image, ImageDraw
from starlette.testclient import TestClient

from backend.main import app
from backend.database import (
    SessionLocal,
    User,
    Document,
    Conversation,
    ConversationDocument,
    SupportRequest,
    SupportMessage,
    Notification,
    PasswordReset,
    AppSetting,
    AuditLog,
    init_db,
    utcnow,
)
from backend.auth import create_access_token, get_password_hash

client = TestClient(app)


def make_test_image(size=(200, 200), color=(100, 180, 220)) -> Image.Image:
    """Generate a test image with distinct shapes."""
    im = Image.new("RGB", size, color=color)
    d = ImageDraw.Draw(im)
    d.rectangle([20, 20, 100, 100], fill=(220, 80, 80), outline="black")
    d.ellipse([110, 110, 180, 180], fill=(80, 220, 80), outline="black")
    d.line([0, 0, size[0], size[1]], fill="white", width=3)
    return im


def parse_sse_events(res_text: str):
    """Parse SSE streaming response text into a list of parsed JSON event payloads."""
    events = []
    for line in res_text.splitlines():
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:].strip()))
            except Exception:
                pass
    return events


# ---------------------------------------------------------------------------
# Test 1: Migration Idempotency & User Preservation
# ---------------------------------------------------------------------------
def test_migration_and_user_preservation():
    """Verify all existing users are preserved in database and init_db is idempotent."""
    # Ensure init_db runs cleanly without errors
    init_db()

    with SessionLocal() as db:
        users = db.query(User).all()
        # rag_company.db has 17 baseline users; confirm all are present
        assert len(users) >= 17, f"Expected at least 17 users, found {len(users)}"

        admin_user = db.query(User).filter(User.email == "admin@abctechnologies.com").first()
        assert admin_user is not None
        assert admin_user.role == "admin"

        # Check required schema columns on User
        for u in users:
            assert hasattr(u, "username")
            assert hasattr(u, "display_name")
            assert hasattr(u, "avatar_color")
            assert hasattr(u, "is_active")
            assert hasattr(u, "token_version")
            assert hasattr(u, "must_change_password")
            # All users should have a backfilled username
            assert u.username is not None and len(u.username) > 0

        # Check auxiliary tables exist and can be queried
        assert db.query(SupportRequest).count() >= 0
        assert db.query(SupportMessage).count() >= 0
        assert db.query(Notification).count() >= 0
        assert db.query(PasswordReset).count() >= 0
        assert db.query(AppSetting).count() >= 0
        assert db.query(AuditLog).count() >= 0

    # Run init_db second time to prove idempotency
    init_db()


# ---------------------------------------------------------------------------
# Test 2: Unique Username Backfill and Registration Validation
# ---------------------------------------------------------------------------
def test_unique_username_backfill_and_validation():
    """Verify unique username requirements and validation during registration."""
    with SessionLocal() as db:
        usernames = [u.username.lower() for u in db.query(User).all() if u.username]
        # Verify all existing usernames are distinct
        assert len(usernames) == len(set(usernames)), "Usernames in DB must be unique"

    uid = uuid.uuid4().hex[:6]
    valid_username = f"uname_{uid}"
    valid_email = f"user_{uid}@abctechnologies.com"

    # Register with username
    reg_res = client.post(
        "/api/auth/register",
        json={
            "email": valid_email,
            "username": valid_username,
            "password": "SecurePassword123!",
            "full_name": "Test User",
        },
    )
    assert reg_res.status_code == 200, reg_res.text
    data = reg_res.json()
    assert data["user"]["username"] == valid_username

    # Duplicate username registration must fail
    dup_uname_res = client.post(
        "/api/auth/register",
        json={
            "email": f"diff_{uid}@abctechnologies.com",
            "username": valid_username,
            "password": "SecurePassword123!",
        },
    )
    assert dup_uname_res.status_code in (400, 409), dup_uname_res.text
    assert "already taken" in dup_uname_res.text.lower() or "already exists" in dup_uname_res.text.lower()

    # Invalid username format (too short or invalid chars)
    invalid_res = client.post(
        "/api/auth/register",
        json={
            "email": f"short_{uid}@abctechnologies.com",
            "username": "ab",  # min 3 chars
            "password": "SecurePassword123!",
        },
    )
    assert invalid_res.status_code in (400, 422), invalid_res.text


# ---------------------------------------------------------------------------
# Test 3: Dual Identifier Login (Email OR Username)
# ---------------------------------------------------------------------------
def test_dual_identifier_login():
    """Verify users can log in using either email or username."""
    uid = uuid.uuid4().hex[:6]
    test_username = f"dual_{uid}"
    test_email = f"dual_{uid}@abctechnologies.com"
    test_password = "DualLoginSecret2026!"

    with SessionLocal() as db:
        new_user = User(
            email=test_email,
            username=test_username,
            password_hash=get_password_hash(test_password),
            role="user",
            is_active=True,
            token_version=1,
        )
        db.add(new_user)
        db.commit()

    # 1. Login with email
    res_email = client.post(
        "/api/auth/login",
        json={"identifier": test_email, "password": test_password},
    )
    assert res_email.status_code == 200, res_email.text
    assert "access_token" in res_email.json()

    # 2. Login with username
    res_user = client.post(
        "/api/auth/login",
        json={"identifier": test_username, "password": test_password},
    )
    assert res_user.status_code == 200, res_user.text
    assert "access_token" in res_user.json()

    # 3. Login with username case-insensitive
    res_upper = client.post(
        "/api/auth/login",
        json={"identifier": test_username.upper(), "password": test_password},
    )
    assert res_upper.status_code == 200, res_upper.text

    # 4. Login with wrong password -> 401
    res_wrong = client.post(
        "/api/auth/login",
        json={"identifier": test_username, "password": "WrongPassword999!"},
    )
    assert res_wrong.status_code == 401

    # 5. Login with deactivated account -> 403
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == test_email).first()
        u.is_active = False
        db.commit()

    res_deactivated = client.post(
        "/api/auth/login",
        json={"identifier": test_username, "password": test_password},
    )
    assert res_deactivated.status_code == 403
    assert "deactivated" in res_deactivated.text.lower()


# ---------------------------------------------------------------------------
# Test 4: Forgot Password Generic Response (No User Enumeration)
# ---------------------------------------------------------------------------
def test_forgot_password_generic_response():
    """Verify forgot-password returns generic message for existing and non-existent users."""
    existing_identifier = "admin@abctechnologies.com"
    nonexistent_identifier = f"nonexistent_{uuid.uuid4().hex}@domain.com"

    res_exist = client.post("/api/auth/forgot-password", json={"identifier": existing_identifier})
    assert res_exist.status_code == 200
    data_exist = res_exist.json()

    res_nonexist = client.post("/api/auth/forgot-password", json={"identifier": nonexistent_identifier})
    assert res_nonexist.status_code == 200
    data_nonexist = res_nonexist.json()

    # Responses must be identical to avoid user enumeration
    assert data_exist.get("message") == data_nonexist.get("message")
    assert "if an account matches" in data_exist.get("message", "").lower() or "reset" in data_exist.get("message", "").lower()


# ---------------------------------------------------------------------------
# Test 5: Password Reset Token Single-Use and Expiry
# ---------------------------------------------------------------------------
def test_password_reset_token_single_use_and_expiry():
    """Verify password reset tokens can only be used once and expire correctly."""
    uid = uuid.uuid4().hex[:6]
    test_email = f"reset_{uid}@abctechnologies.com"
    initial_pw = "InitialPassword123!"
    new_pw = "NewSecretPassword2026!"

    with SessionLocal() as db:
        user = User(
            email=test_email,
            username=f"reset_{uid}",
            password_hash=get_password_hash(initial_pw),
            role="user",
            is_active=True,
            token_version=1,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        # Create valid reset token
        valid_raw_token = secrets.token_urlsafe(32)
        valid_hash = hashlib.sha256(valid_raw_token.encode("utf-8")).hexdigest()
        prt = PasswordReset(
            user_id=user.id,
            token_hash=valid_hash,
            status="approved",
            expires_at=datetime.datetime.now(timezone.utc) + datetime.timedelta(hours=1),
        )
        db.add(prt)

        # Create expired reset token
        expired_raw_token = secrets.token_urlsafe(32)
        expired_hash = hashlib.sha256(expired_raw_token.encode("utf-8")).hexdigest()
        prt_exp = PasswordReset(
            user_id=user.id,
            token_hash=expired_hash,
            status="approved",
            expires_at=datetime.datetime.now(timezone.utc) - datetime.timedelta(minutes=10),
        )
        db.add(prt_exp)
        db.commit()

    # 1. Attempt reset with expired token -> 400
    res_exp = client.post(
        "/api/auth/reset-password",
        json={"token": expired_raw_token, "new_password": new_pw},
    )
    assert res_exp.status_code == 400
    assert "expired" in res_exp.text.lower() or "invalid" in res_exp.text.lower()

    # 2. Reset with valid token -> 200
    res_valid = client.post(
        "/api/auth/reset-password",
        json={"token": valid_raw_token, "new_password": new_pw},
    )
    assert res_valid.status_code == 200

    # 3. Attempt to use same token a second time -> 400 (single use enforced)
    res_reuse = client.post(
        "/api/auth/reset-password",
        json={"token": valid_raw_token, "new_password": "AnotherNewPassword123!"},
    )
    assert res_reuse.status_code == 400

    # 4. Verify login with new password succeeds and old password fails
    login_old = client.post("/api/auth/login", json={"identifier": test_email, "password": initial_pw})
    assert login_old.status_code == 401

    login_new = client.post("/api/auth/login", json={"identifier": test_email, "password": new_pw})
    assert login_new.status_code == 200


# ---------------------------------------------------------------------------
# Test 6: Last-Admin Protection
# ---------------------------------------------------------------------------
def test_last_admin_protection():
    """Verify admins cannot demote or deactivate themselves or the last admin."""
    with SessionLocal() as db:
        admin = db.query(User).filter(User.role == "admin").first()
        assert admin is not None
        admin_token = create_access_token({"sub": str(admin.id), "email": admin.email, "role": "admin"})

    headers = {"Authorization": f"Bearer {admin_token}"}

    # Attempt to demote self to user -> must return 400
    demote_res = client.patch(
        f"/api/admin/users/{admin.id}",
        headers=headers,
        json={"role": "user"},
    )
    assert demote_res.status_code == 400
    assert "cannot" in demote_res.text.lower()

    # Attempt to deactivate self -> must return 400
    deactivate_res = client.patch(
        f"/api/admin/users/{admin.id}",
        headers=headers,
        json={"is_active": False},
    )
    assert deactivate_res.status_code == 400
    assert "cannot" in deactivate_res.text.lower()


# ---------------------------------------------------------------------------
# Test 7: Branding Dynamic Change Reflected in /api/config
# ---------------------------------------------------------------------------
def test_branding_dynamic_change():
    """Verify updating company branding via admin endpoint dynamically updates /api/config."""
    with SessionLocal() as db:
        admin = db.query(User).filter(User.role == "admin").first()
        admin_token = create_access_token({"sub": str(admin.id), "email": admin.email, "role": "admin"})

    headers = {"Authorization": f"Bearer {admin_token}"}

    update_payload = {
        "company_name": "Phase 3 Innovations Inc.",
        "tagline": "Next-Gen Enterprise AI Assistant",
        "support_email": "helpdesk@p3innovations.com",
        "primary_color": "#1e40af",
    }

    put_res = client.put("/api/admin/settings/branding", headers=headers, json=update_payload)
    assert put_res.status_code == 200, put_res.text

    # Public config must reflect updated branding immediately
    config_res = client.get("/api/config")
    assert config_res.status_code == 200
    cfg_data = config_res.json()
    assert cfg_data.get("company_name") == "Phase 3 Innovations Inc."
    assert cfg_data.get("tagline") == "Next-Gen Enterprise AI Assistant"


# ---------------------------------------------------------------------------
# Test 8: RBAC & Resource Isolation
# ---------------------------------------------------------------------------
def test_rbac_and_resource_isolation():
    """Verify non-admin users cannot access admin endpoints or another user's support data."""
    with SessionLocal() as db:
        user_a = User(
            email=f"usr_a_{uuid.uuid4().hex[:5]}@test.com",
            username=f"usra_{uuid.uuid4().hex[:5]}",
            password_hash=get_password_hash("Pass123!"),
            role="user",
            is_active=True,
        )
        user_b = User(
            email=f"usr_b_{uuid.uuid4().hex[:5]}@test.com",
            username=f"usrb_{uuid.uuid4().hex[:5]}",
            password_hash=get_password_hash("Pass123!"),
            role="user",
            is_active=True,
        )
        admin = db.query(User).filter(User.role == "admin").first()
        db.add_all([user_a, user_b])
        db.commit()
        db.refresh(user_a)
        db.refresh(user_b)

        token_a = create_access_token({"sub": str(user_a.id), "email": user_a.email, "role": "user"})
        token_b = create_access_token({"sub": str(user_b.id), "email": user_b.email, "role": "user"})
        admin_token = create_access_token({"sub": str(admin.id), "email": admin.email, "role": "admin"})

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}
    headers_admin = {"Authorization": f"Bearer {admin_token}"}

    # 1. Regular user forbidden from admin routes
    assert client.get("/api/admin/users", headers=headers_a).status_code == 403
    assert client.get("/api/admin/audit", headers=headers_a).status_code == 403
    assert client.get("/api/admin/support/requests", headers=headers_a).status_code == 403

    # 2. User A creates a support request
    req_res = client.post(
        "/api/support/requests",
        headers=headers_a,
        json={"subject": "Need access to Q3 financials", "message": "Please grant access.", "type": "document_access"},
    )
    assert req_res.status_code == 200, req_res.text
    ticket_id = req_res.json()["id"]

    # 3. User B cannot see User A's ticket
    b_view = client.get(f"/api/support/requests/{ticket_id}", headers=headers_b)
    assert b_view.status_code in (403, 404)

    # 4. Admin replies to User A's ticket
    reply_res = client.post(
        f"/api/support/requests/{ticket_id}/messages",
        headers=headers_admin,
        json={"body": "Access granted for Q3 financials."},
    )
    assert reply_res.status_code == 200, reply_res.text

    # 5. User A receives notification
    notif_res = client.get("/api/notifications", headers=headers_a)
    assert notif_res.status_code == 200
    notifs = notif_res.json().get("notifications", [])
    assert len(notifs) >= 1
    notif_id = notifs[0]["id"]

    # 6. User B cannot mark User A's notification as read
    b_patch = client.post(f"/api/notifications/{notif_id}/read", headers=headers_b)
    assert b_patch.status_code in (403, 404)


# ---------------------------------------------------------------------------
# Test 9: Regression Test: Document-Scoped Chat "show me the image"
# ---------------------------------------------------------------------------
def test_regression_document_scoped_chat_show_me_the_image(tmp_path):
    """
    Regression Test: A document-scoped chat with an image document and the
    question 'show me the image' must return an image URL and no error.
    """
    # 1. Create a genuine textured image file
    img_filename = f"spec_diagram_{uuid.uuid4().hex[:6]}.png"
    img_filepath = str(tmp_path / img_filename)
    make_test_image(size=(320, 240)).save(img_filepath)

    with SessionLocal() as db:
        user = db.query(User).filter(User.role == "user", User.is_active == True).first()
        assert user is not None, "Need an active user in the database"

        doc = Document(
            id=f"doc_reg_{uuid.uuid4().hex[:8]}",
            filename=img_filename,
            filepath=img_filepath,
            file_type="png",
            scope="user",
            owner_id=user.id,
            status="ready",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        conv = Conversation(
            user_id=user.id,
            title="Image Spec Chat",
            active_doc_id=doc.id,
        )
        db.add(conv)
        db.commit()
        db.refresh(conv)

        token = create_access_token({"sub": str(user.id), "email": user.email, "role": user.role})
        conv_id = conv.id

    headers = {"Authorization": f"Bearer {token}"}

    # 2. Ask "show me the image" in the document-scoped chat
    chat_res = client.post(
        f"/api/conversations/{conv_id}/messages",
        headers=headers,
        json={"message": "show me the image"},
    )
    assert chat_res.status_code == 200, f"Chat request failed with {chat_res.status_code}: {chat_res.text}"

    # 3. Parse SSE stream and verify events
    events = parse_sse_events(chat_res.text)
    assert len(events) > 0, "Expected SSE events from chat stream"

    # Must NOT have any error event
    error_events = [e for e in events if e.get("type") == "error"]
    assert len(error_events) == 0, f"Received unexpected error events: {error_events}"

    # Find the done event
    done_event = next((e for e in events if e.get("type") == "done"), None)
    assert done_event is not None, f"Expected 'done' SSE event in: {events}"

    # Verify images were returned and have valid URLs
    images = done_event.get("images") or []
    assert len(images) > 0, f"Expected at least 1 image returned, got: {images}"

    first_image = images[0]
    assert "url" in first_image, f"Image dict missing 'url': {first_image}"
    img_url = first_image["url"]
    assert img_url.startswith("/uploads/") or img_url.startswith("/api/images/") or "image" in img_url.lower(), (
        f"Unexpected image URL format: {img_url}"
    )

    # 4. Fetch the image URL and verify it responds 200 OK with image content type
    fetch_res = client.get(img_url, headers=headers)
    assert fetch_res.status_code == 200, f"Fetching image URL '{img_url}' returned {fetch_res.status_code}"
    content_type = fetch_res.headers.get("Content-Type", "")
    assert "image" in content_type or "octet-stream" in content_type, f"Invalid Content-Type: {content_type}"
