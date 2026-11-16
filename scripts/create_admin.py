"""Interactive and CLI utility to create or reset an administrator account.
Allows server owners to create the initial admin account interactively with getpass
(minimum password length 10) without editing .env.
"""

import sys
import os
import re
import getpass
import argparse
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

from sqlalchemy import func
from backend.database import SessionLocal, User, init_db, log_audit
from backend.auth import get_password_hash

FORBIDDEN_PASSWORDS = {
    "admin@123",
    "admin123",
    "password",
    "password123",
    "password1234",
    "123456789012",
    "user@123",
    "user123",
    "changeme",
    "change-me",
    "administrator",
    "letmein12345",
}


def validate_admin_password(password: str, confirm_password: str) -> None:
    if not password:
        raise ValueError("Password cannot be empty.")
    if len(password) < 10:
        raise ValueError("Password must be at least 10 characters long.")
    if password.lower().strip() in FORBIDDEN_PASSWORDS:
        raise ValueError("Password matches a known weak default. Please choose a stronger password.")
    if password != confirm_password:
        raise ValueError("Passwords do not match.")


def create_or_reset_admin(email: str, password: str, confirm_password: str) -> bool:
    clean_email = email.strip().lower()
    if not clean_email or "@" not in clean_email or "." not in clean_email:
        print("[-] Error: A valid email address is required.")
        return False

    try:
        validate_admin_password(password, confirm_password)
    except ValueError as e:
        print(f"[-] Error: {e}")
        return False

    init_db()
    with SessionLocal() as db:
        user = db.query(User).filter(func.lower(User.email) == clean_email).first()

        if user:
            user.password_hash = get_password_hash(password)
            user.role = "admin"
            user.is_active = True
            user.must_change_password = False
            user.token_version = (user.token_version or 0) + 1
            log_audit(db, actor_id=user.id, action="admin_reset_cli", target=user.email, details="CLI create_admin reset")
            db.commit()
            print(f"[+] Existing account '{clean_email}' successfully promoted/reset to admin.")
            print("[+] All previous sessions for this account have been invalidated.")
            return True
        else:
            # Generate unique base username
            base_uname = re.sub(r"[^\w\.-]", "_", clean_email.split("@")[0]) or "admin"
            candidate_uname = base_uname
            idx = 1
            while db.query(User).filter(func.lower(User.username) == candidate_uname.lower()).first():
                candidate_uname = f"{base_uname}_{idx}"
                idx += 1

            new_admin = User(
                email=clean_email,
                username=candidate_uname,
                password_hash=get_password_hash(password),
                role="admin",
                is_active=True,
                must_change_password=False,
                token_version=1,
            )
            db.add(new_admin)
            db.flush()
            log_audit(db, actor_id=new_admin.id, action="admin_create_cli", target=new_admin.email, details="CLI create_admin")
            db.commit()
            print(f"[+] Admin account '{clean_email}' (username: {candidate_uname}) created successfully.")
            return True


def main():
    parser = argparse.ArgumentParser(description="Create or reset an administrator account.")
    parser.add_argument("--email", help="Administrator email address")
    parser.add_argument("--password", help="Administrator password (min length 10)")
    args = parser.parse_args()

    email = args.email
    password = args.password

    if not email:
        try:
            email = input("Admin email address: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            sys.exit(1)

    if not password:
        try:
            password = getpass.getpass("Admin password (min length 10): ")
            confirm = getpass.getpass("Confirm password: ")
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            sys.exit(1)
    else:
        confirm = password

    success = create_or_reset_admin(email, password, confirm)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
