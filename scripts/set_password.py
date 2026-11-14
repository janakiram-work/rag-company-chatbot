"""CLI utility to securely set a user's password without echoing secrets to the terminal.
Enforces minimum 12 characters and rejects known weak default passwords.
"""

import sys
import os
import getpass
from pathlib import Path

# Ensure backend modules can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import or_, func
from backend.database import SessionLocal, User, log_audit, init_db
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


def validate_new_password(pw: str, confirm_pw: str) -> None:
    if not pw:
        raise ValueError("Password cannot be empty.")
    if len(pw) < 12:
        raise ValueError("Password must be at least 12 characters long.")
    if pw.lower().strip() in FORBIDDEN_PASSWORDS:
        raise ValueError("Password matches a known weak default. Please choose a stronger password.")
    if pw != confirm_pw:
        raise ValueError("Passwords do not match.")


def set_user_password(identifier: str, password: str, confirm_password: str) -> bool:
    validate_new_password(password, confirm_password)

    init_db()
    with SessionLocal() as db:
        clean_id = identifier.strip().lower()
        user = db.query(User).filter(
            or_(func.lower(User.email) == clean_id, func.lower(User.username) == clean_id)
        ).first()

        if not user:
            print(f"[-] Error: User '{identifier}' not found in database.")
            return False

        user.password_hash = get_password_hash(password)
        user.token_version = (user.token_version or 0) + 1
        user.must_change_password = False
        log_audit(db, actor_id=user.id, action="password_reset_cli", target=user.email, details="CLI set_password")
        db.commit()

        print(f"[+] Password successfully updated for user '{user.email}' (username: {user.username or 'none'}).")
        print("[+] Any active sessions for this account have been invalidated.")
        return True


def main():
    if len(sys.argv) > 1:
        target_user = sys.argv[1].strip()
    else:
        target_user = input("Enter username or email: ").strip()

    if not target_user:
        print("[-] Target user is required.")
        sys.exit(1)

    try:
        pw1 = getpass.getpass("Enter new password (min 12 chars): ")
        pw2 = getpass.getpass("Confirm new password: ")
    except (KeyboardInterrupt, EOFError):
        print("\nOperation cancelled.")
        sys.exit(1)

    try:
        success = set_user_password(target_user, pw1, pw2)
        sys.exit(0 if success else 1)
    except ValueError as e:
        print(f"[-] Validation error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
