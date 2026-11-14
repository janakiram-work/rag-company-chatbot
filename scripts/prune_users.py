#!/usr/bin/env python3
"""CLI utility to safely prune users from the database while preserving data integrity.

Rules:
- Dry-run by default: inspects models/FKs in backend/database.py and prints detailed tables.
- Refuses if no active admin remains among kept users.
- Reassigns company-scoped documents to the primary kept admin.
- Deletes private-scoped documents, files on disk, and Chroma vector embeddings.
- In --apply mode:
    * Creates a timestamped backup copy in backups/
    * Runs in an atomic database transaction
    * Nullifies foreign keys on app_settings, audit_log, and password_resets.approved_by
    * Deletes related records for pruned users
    * Adds an audit_log entry
    * Executes PRAGMA integrity_check
    * Reports before and after user counts
"""

import sys
import os
import glob
import json
import shutil
import logging
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

# Ensure repository root is on Python module path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import sessionmaker, Session
from backend.database import (
    Base,
    User,
    Conversation,
    ConversationDocument,
    Message,
    Feedback,
    Document,
    ImageAsset,
    ImageHash,
    AppSetting,
    UserPreference,
    PasswordReset,
    SupportRequest,
    SupportMessage,
    Notification,
    AuditLog,
)

logger = logging.getLogger("prune_users")

from backend.user_cleanup import (
    get_chroma_collection_safe,
    delete_chroma_vectors_for_doc as delete_doc_vectors,
    resolve_file_location as resolve_document_filepath,
)


def get_doc_vector_count(collection, doc_id: str) -> int:
    """Return count of vectors for a doc_id in Chroma."""
    if collection is None:
        return 0
    try:
        existing = collection.get(where={"doc_id": str(doc_id)})
        return len(existing["ids"]) if existing and "ids" in existing else 0
    except Exception:
        return 0


def backup_sqlite_db(db_file_path: str, backup_dir: str = "backups") -> Optional[str]:
    """Create a timestamped backup copy of SQLite database file."""
    if not db_file_path or not os.path.isfile(db_file_path):
        return None
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = Path(db_file_path).stem
    backup_file = os.path.join(backup_dir, f"{stem}_backup_{timestamp}.db")

    try:
        import sqlite3
        src = sqlite3.connect(db_file_path)
        dst = sqlite3.connect(backup_file)
        with dst:
            src.backup(dst)
        dst.close()
        src.close()
    except Exception:
        shutil.copy2(db_file_path, backup_file)

    return backup_file


def resolve_sqlite_path(db_url: str) -> Optional[str]:
    """Extract file path from a sqlite:/// URL."""
    if not db_url or not db_url.startswith("sqlite"):
        return None
    clean = db_url.replace("sqlite:///", "")
    if clean.startswith("/"):
        # Unix absolute path
        return clean
    # Windows absolute or relative
    return os.path.abspath(clean)


def run_prune_users(
    keep_identifiers: List[str],
    apply: bool = False,
    db_path: Optional[str] = None,
    chroma_dir: Optional[str] = None,
    upload_dir: Optional[str] = None,
    backup_dir: str = "backups",
    session: Optional[Session] = None,
) -> Dict[str, Any]:
    """
    Core prune implementation. Can be called directly or via CLI.
    """
    # 1. Resolve DB Session & Engine
    close_session_at_end = False
    if session is None:
        from backend.config import DATABASE_URL, CHROMA_DIR, UPLOAD_DIR
        url = db_path if db_path else DATABASE_URL
        if url and not (url.startswith("sqlite") or url.startswith("postgresql")):
            url = f"sqlite:///{os.path.abspath(url)}"

        engine = create_engine(
            url,
            connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
        )
        if url.startswith("sqlite"):
            @event.listens_for(engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        SessionClass = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db = SessionClass()
        close_session_at_end = True
        actual_db_url = url
    else:
        db = session
        actual_db_url = str(db.bind.url) if db.bind else ""
        from backend.config import CHROMA_DIR, UPLOAD_DIR

    actual_chroma_dir = chroma_dir if chroma_dir else CHROMA_DIR
    actual_upload_dir = upload_dir if upload_dir else UPLOAD_DIR
    images_dir = os.path.join(actual_upload_dir, "images")
    rendered_pages_dir = os.path.join(actual_upload_dir, "rendered_pages")

    try:
        # 2. Query all existing users
        all_users = db.query(User).order_by(User.id).all()
        before_count = len(all_users)

        keep_set = {k.strip().lower() for k in keep_identifiers if k and k.strip()}
        kept_users = []
        pruned_users = []

        for u in all_users:
            u_email = (u.email or "").strip().lower()
            u_username = (u.username or "").strip().lower()
            if u_email in keep_set or u_username in keep_set:
                kept_users.append(u)
            else:
                pruned_users.append(u)

        # Check unmatched keep identifiers
        matched_keys = {u.email.strip().lower() for u in kept_users if u.email} | {
            u.username.strip().lower() for u in kept_users if u.username
        }
        unmatched = [k for k in keep_identifiers if k.strip().lower() not in matched_keys]
        if unmatched:
            print(f"[WARNING] Specified user(s) to keep not found: {', '.join(unmatched)}")

        # 3. Check for at least one active admin among kept users
        active_admins = [u for u in kept_users if u.role == "admin" and u.is_active]
        if not active_admins:
            msg = (
                "[ERROR] Refusing to prune: No active admin remains among kept users. "
                "At least one active admin must be kept."
            )
            print(msg)
            raise ValueError(msg)

        # Pick primary kept admin (prefer configured ADMIN_EMAIL if matched, else first)
        configured_admin_email = os.getenv("ADMIN_EMAIL", "").strip().lower()
        kept_admin = active_admins[0]
        for a in active_admins:
            if a.email and a.email.strip().lower() == configured_admin_email:
                kept_admin = a
                break

        pruned_user_ids = [u.id for u in pruned_users]
        kept_user_ids = [u.id for u in kept_users]

        # 4. Analyze documents
        if pruned_user_ids:
            company_docs = (
                db.query(Document)
                .filter(Document.owner_id.in_(pruned_user_ids), Document.scope == "company")
                .all()
            )
            private_docs = (
                db.query(Document)
                .filter(Document.owner_id.in_(pruned_user_ids), Document.scope != "company")
                .all()
            )
        else:
            company_docs = []
            private_docs = []

        private_doc_ids = [d.id for d in private_docs]

        # Chroma collection inspection
        chroma_collection = get_chroma_collection_safe(actual_chroma_dir)

        # Collect detailed info for private docs
        private_docs_info = []
        total_private_vectors = 0
        for doc in private_docs:
            vec_count = get_doc_vector_count(chroma_collection, doc.id)
            total_private_vectors += vec_count
            resolved_path = resolve_document_filepath(doc.id, doc.filename, doc.filepath, actual_upload_dir)
            file_exists = resolved_path is not None
            private_docs_info.append(
                {
                    "id": doc.id,
                    "filename": doc.filename,
                    "filepath": resolved_path or doc.filepath,
                    "file_exists": file_exists,
                    "vectors": vec_count,
                    "owner_id": doc.owner_id,
                }
            )

        # 5. Calculate counts of records to delete
        table_counts: Dict[str, int] = {
            "users": len(pruned_user_ids),
            "conversations": 0,
            "messages": 0,
            "feedbacks": 0,
            "conversation_documents": 0,
            "documents_company_reassigned": len(company_docs),
            "documents_private_deleted": len(private_docs),
            "image_assets": 0,
            "image_hashes": 0,
            "support_requests": 0,
            "support_messages": 0,
            "notifications": 0,
            "password_resets_deleted": 0,
            "user_preferences": 0,
            "app_settings_nullified": 0,
            "audit_log_nullified": 0,
            "password_resets_approved_nullified": 0,
        }

        pruned_conv_ids = []
        pruned_msg_ids = []
        pruned_req_ids = []

        if pruned_user_ids:
            # Conversations & messages
            conv_rows = db.query(Conversation.id).filter(Conversation.user_id.in_(pruned_user_ids)).all()
            pruned_conv_ids = [c[0] for c in conv_rows]
            table_counts["conversations"] = len(pruned_conv_ids)

            if pruned_conv_ids:
                msg_rows = db.query(Message.id).filter(Message.conversation_id.in_(pruned_conv_ids)).all()
                pruned_msg_ids = [m[0] for m in msg_rows]
                table_counts["messages"] = len(pruned_msg_ids)

                conv_doc_count = (
                    db.query(ConversationDocument)
                    .filter(ConversationDocument.conversation_id.in_(pruned_conv_ids))
                    .count()
                )
                table_counts["conversation_documents"] += conv_doc_count

            # Feedback
            fb_query = db.query(Feedback).filter(Feedback.user_id.in_(pruned_user_ids))
            if pruned_msg_ids:
                fb_query = db.query(Feedback).filter(
                    (Feedback.user_id.in_(pruned_user_ids)) | (Feedback.message_id.in_(pruned_msg_ids))
                )
            table_counts["feedbacks"] = fb_query.count()

            # Support requests & messages
            req_rows = db.query(SupportRequest.id).filter(SupportRequest.user_id.in_(pruned_user_ids)).all()
            pruned_req_ids = [r[0] for r in req_rows]
            table_counts["support_requests"] = len(pruned_req_ids)

            supp_msg_query = db.query(SupportMessage).filter(SupportMessage.sender_id.in_(pruned_user_ids))
            if pruned_req_ids:
                supp_msg_query = db.query(SupportMessage).filter(
                    (SupportMessage.sender_id.in_(pruned_user_ids))
                    | (SupportMessage.request_id.in_(pruned_req_ids))
                )
            table_counts["support_messages"] = supp_msg_query.count()

            # Notifications
            table_counts["notifications"] = (
                db.query(Notification).filter(Notification.user_id.in_(pruned_user_ids)).count()
            )

            # Password resets
            table_counts["password_resets_deleted"] = (
                db.query(PasswordReset).filter(PasswordReset.user_id.in_(pruned_user_ids)).count()
            )
            table_counts["password_resets_approved_nullified"] = (
                db.query(PasswordReset).filter(PasswordReset.approved_by.in_(pruned_user_ids)).count()
            )

            # User preferences
            table_counts["user_preferences"] = (
                db.query(UserPreference).filter(UserPreference.user_id.in_(pruned_user_ids)).count()
            )

            # App settings nullifications
            table_counts["app_settings_nullified"] = (
                db.query(AppSetting).filter(AppSetting.updated_by.in_(pruned_user_ids)).count()
            )

            # Audit log nullifications
            table_counts["audit_log_nullified"] = (
                db.query(AuditLog).filter(AuditLog.actor_id.in_(pruned_user_ids)).count()
            )

        if private_doc_ids:
            table_counts["image_assets"] = (
                db.query(ImageAsset).filter(ImageAsset.doc_id.in_(private_doc_ids)).count()
            )
            table_counts["image_hashes"] = (
                db.query(ImageHash).filter(ImageHash.doc_id.in_(private_doc_ids)).count()
            )

        # 6. Format and Print Dry-Run Tables
        print("\n" + "=" * 70)
        print("          PRUNE USERS: DRY-RUN REPORT" if not apply else "          PRUNE USERS: EXECUTION PLAN")
        print("=" * 70)

        # Table 1: Kept Users
        print("\n--- USERS TO KEEP ---")
        print(f"{'ID':<6} {'EMAIL':<30} {'USERNAME':<16} {'ROLE':<8} {'ACTIVE':<6}")
        print("-" * 68)
        for u in kept_users:
            is_kept_admin = " (primary)" if u.id == kept_admin.id else ""
            print(f"{u.id:<6} {u.email:<30} {(u.username or '-'):<16} {u.role:<8} {str(u.is_active):<6}{is_kept_admin}")

        # Table 2: Pruned Users
        print(f"\n--- USERS TO PRUNE ({len(pruned_users)}) ---")
        if pruned_users:
            print(f"{'ID':<6} {'EMAIL':<30} {'USERNAME':<16} {'ROLE':<8} {'ACTIVE':<6}")
            print("-" * 68)
            for u in pruned_users:
                print(f"{u.id:<6} {u.email:<30} {(u.username or '-'):<16} {u.role:<8} {str(u.is_active):<6}")
        else:
            print("  (None. All existing users are matched in --keep).")

        # Table 3: Company Documents to Reassign
        print(f"\n--- COMPANY DOCUMENTS TO REASSIGN TO ADMIN ({kept_admin.email}) ---")
        if company_docs:
            print(f"{'DOC ID':<38} {'FILENAME':<24} {'CURRENT OWNER ID':<16}")
            print("-" * 80)
            for d in company_docs:
                print(f"{d.id:<38} {d.filename[:22]:<24} {d.owner_id:<16}")
        else:
            print("  (None)")

        # Table 4: Private Documents / Files / Vectors
        print(f"\n--- PRIVATE DOCUMENTS TO DELETE ({len(private_docs)}) ---")
        if private_docs_info:
            print(f"{'DOC ID':<38} {'FILENAME':<20} {'FILE EXISTS':<12} {'CHROMA CHUNKS':<14}")
            print("-" * 86)
            for item in private_docs_info:
                print(f"{item['id']:<38} {item['filename'][:18]:<20} {str(item['file_exists']):<12} {item['vectors']:<14}")
        else:
            print("  (None)")

        # Table 5: Counts per Table
        print("\n--- RECORDS TO BE DELETED / MODIFIED PER TABLE ---")
        print(f"{'TABLE / ACTION':<40} {'COUNT':<10}")
        print("-" * 52)
        for tbl, cnt in table_counts.items():
            print(f"{tbl:<40} {cnt:<10}")

        backup_file = None
        integrity_ok = True

        # 7. Apply execution
        if not apply:
            print("\n" + "=" * 70)
            print("[DRY-RUN COMPLETE] No database or filesystem modifications were made.")
            print("To execute this plan, re-run with the --apply flag.")
            print("=" * 70 + "\n")
        else:
            print("\n" + "=" * 70)
            print("[APPLY MODE] Executing user pruning transaction...")
            print("=" * 70)

            # Step 1: Backup SQLite database if file-based
            sqlite_file = resolve_sqlite_path(actual_db_url)
            if sqlite_file and os.path.isfile(sqlite_file):
                backup_file = backup_sqlite_db(sqlite_file, backup_dir=backup_dir)
                if backup_file:
                    print(f"[BACKUP] SQLite database safely backed up to: {backup_file}")

            # Step 2: Atomic transaction
            try:
                # 2a. Reassign company documents to kept admin
                if company_docs:
                    company_doc_ids = [d.id for d in company_docs]
                    db.query(Document).filter(Document.id.in_(company_doc_ids)).update(
                        {Document.owner_id: kept_admin.id}, synchronize_session=False
                    )

                # 2b. Delete physical files and Chroma vectors for private documents
                for p_doc in private_docs:
                    # Chroma vectors
                    if chroma_collection is not None:
                        delete_doc_vectors(chroma_collection, p_doc.id)

                    # Source file on disk
                    paths_to_delete = set()
                    if p_doc.filepath and os.path.exists(p_doc.filepath):
                        paths_to_delete.add(p_doc.filepath)
                    resolved_p = resolve_document_filepath(p_doc.id, p_doc.filename, p_doc.filepath, actual_upload_dir)
                    if resolved_p and os.path.exists(resolved_p):
                        paths_to_delete.add(resolved_p)

                    for p in paths_to_delete:
                        try:
                            os.remove(p)
                        except OSError as e:
                            logger.warning(f"Could not remove doc file {p}: {e}")

                    # Extracted images and rendered pages matching doc.id
                    for folder in [images_dir, rendered_pages_dir]:
                        if folder and os.path.exists(folder):
                            for extra_file in glob.glob(os.path.join(folder, f"{p_doc.id}*")):
                                try:
                                    os.remove(extra_file)
                                except OSError:
                                    pass

                # 2c. Delete private doc child records
                if private_doc_ids:
                    # Remove disk files recorded in ImageAsset.path
                    assets = db.query(ImageAsset).filter(ImageAsset.doc_id.in_(private_doc_ids)).all()
                    for a in assets:
                        if a.path and os.path.exists(a.path):
                            try:
                                os.remove(a.path)
                            except OSError:
                                pass

                    db.query(ImageAsset).filter(ImageAsset.doc_id.in_(private_doc_ids)).delete(synchronize_session=False)
                    db.query(ImageHash).filter(ImageHash.doc_id.in_(private_doc_ids)).delete(synchronize_session=False)
                    db.query(ConversationDocument).filter(ConversationDocument.doc_id.in_(private_doc_ids)).delete(synchronize_session=False)
                    db.query(Document).filter(Document.id.in_(private_doc_ids)).delete(synchronize_session=False)

                # 2d. Nullify foreign keys
                if pruned_user_ids:
                    db.query(AppSetting).filter(AppSetting.updated_by.in_(pruned_user_ids)).update(
                        {AppSetting.updated_by: None}, synchronize_session=False
                    )
                    db.query(AuditLog).filter(AuditLog.actor_id.in_(pruned_user_ids)).update(
                        {AuditLog.actor_id: None}, synchronize_session=False
                    )
                    db.query(PasswordReset).filter(PasswordReset.approved_by.in_(pruned_user_ids)).update(
                        {PasswordReset.approved_by: None}, synchronize_session=False
                    )

                # 2e. Delete conversations and messages for pruned users
                if pruned_conv_ids:
                    if pruned_msg_ids:
                        db.query(Feedback).filter(Feedback.message_id.in_(pruned_msg_ids)).delete(synchronize_session=False)
                        db.query(Message).filter(Message.id.in_(pruned_msg_ids)).delete(synchronize_session=False)
                    db.query(ConversationDocument).filter(ConversationDocument.conversation_id.in_(pruned_conv_ids)).delete(synchronize_session=False)
                    db.query(Conversation).filter(Conversation.id.in_(pruned_conv_ids)).delete(synchronize_session=False)

                if pruned_user_ids:
                    # Remaining feedbacks
                    db.query(Feedback).filter(Feedback.user_id.in_(pruned_user_ids)).delete(synchronize_session=False)

                    # Support requests and messages
                    if pruned_req_ids:
                        db.query(SupportMessage).filter(SupportMessage.request_id.in_(pruned_req_ids)).delete(synchronize_session=False)
                        db.query(SupportRequest).filter(SupportRequest.id.in_(pruned_req_ids)).delete(synchronize_session=False)

                    db.query(SupportMessage).filter(SupportMessage.sender_id.in_(pruned_user_ids)).delete(synchronize_session=False)

                    # Notifications, password resets, user preferences
                    db.query(Notification).filter(Notification.user_id.in_(pruned_user_ids)).delete(synchronize_session=False)
                    db.query(PasswordReset).filter(PasswordReset.user_id.in_(pruned_user_ids)).delete(synchronize_session=False)
                    db.query(UserPreference).filter(UserPreference.user_id.in_(pruned_user_ids)).delete(synchronize_session=False)

                    # Delete users
                    db.query(User).filter(User.id.in_(pruned_user_ids)).delete(synchronize_session=False)

                # 2f. Write AuditLog entry
                audit_entry = AuditLog(
                    actor_id=kept_admin.id,
                    action="users_pruned",
                    target="users",
                    details=json.dumps(
                        {
                            "pruned_count": len(pruned_user_ids),
                            "kept_count": len(kept_user_ids),
                            "pruned_emails": [u.email for u in pruned_users],
                            "kept_emails": [u.email for u in kept_users],
                            "reassigned_company_docs": len(company_docs),
                            "deleted_private_docs": len(private_docs),
                        }
                    ),
                )
                db.add(audit_entry)

                # Commit transaction
                db.commit()
                print("[SUCCESS] Database transaction committed successfully.")
            except Exception as e:
                db.rollback()
                print(f"[ERROR] Transaction failed and was rolled back: {e}")
                raise

            # Step 3: SQLite integrity check
            if actual_db_url.startswith("sqlite"):
                try:
                    res = db.execute(text("PRAGMA integrity_check")).fetchall()
                    status_line = res[0][0] if res else "unknown"
                    if status_line.lower() == "ok":
                        print("[INTEGRITY] PRAGMA integrity_check: ok")
                        integrity_ok = True
                    else:
                        print(f"[INTEGRITY WARNING] PRAGMA integrity_check returned: {status_line}")
                        integrity_ok = False
                except Exception as e:
                    print(f"[INTEGRITY ERROR] Failed to run PRAGMA integrity_check: {e}")
                    integrity_ok = False

        after_count = db.query(User).count()
        print(f"\n[SUMMARY] Total users before: {before_count} | Total users after: {after_count}")

        return {
            "before_user_count": before_count,
            "after_user_count": after_count,
            "kept_count": len(kept_users),
            "pruned_count": len(pruned_users),
            "reassigned_company_docs": len(company_docs),
            "deleted_private_docs": len(private_docs),
            "backup_file": backup_file,
            "integrity_ok": integrity_ok,
            "counts": table_counts,
        }

    finally:
        if close_session_at_end:
            db.close()


def main():
    parser = argparse.ArgumentParser(
        description="Prune non-whitelisted users from the RAG assistant database."
    )
    parser.add_argument(
        "--keep",
        nargs="+",
        required=True,
        help="Email addresses or usernames of users to keep (all others will be pruned).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Execute the pruning plan. If omitted, performs a dry-run.",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Path or connection URL to the database. Defaults to DATABASE_URL in config.",
    )
    parser.add_argument(
        "--chroma-dir",
        default=None,
        help="Path to ChromaDB storage directory. Defaults to CHROMA_DIR in config.",
    )
    parser.add_argument(
        "--upload-dir",
        default=None,
        help="Path to uploads storage directory. Defaults to UPLOAD_DIR in config.",
    )
    parser.add_argument(
        "--backup-dir",
        default="backups",
        help="Directory to save pre-prune SQLite backup. Defaults to 'backups/'.",
    )

    args = parser.parse_args()

    try:
        run_prune_users(
            keep_identifiers=args.keep,
            apply=args.apply,
            db_path=args.db,
            chroma_dir=args.chroma_dir,
            upload_dir=args.upload_dir,
            backup_dir=args.backup_dir,
        )
    except Exception as e:
        sys.exit(1)


if __name__ == "__main__":
    main()
