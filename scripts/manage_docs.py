#!/usr/bin/env python3
"""CLI utility to list and safely delete documents from the database and vector store.

Usage:
    python scripts/manage_docs.py list
    python scripts/manage_docs.py delete --ids <id1> <id2> ... [--apply]
"""

import sys
import os
import glob
import argparse
import logging
from pathlib import Path
from typing import List, Optional

# Ensure repository root is on sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

from backend.config import UPLOAD_DIR, DOCS_DIR, IMAGES_DIR, RENDERED_PAGES_DIR, CHROMA_DIR
from backend.database import SessionLocal, Document, ImageAsset, ImageHash, ConversationDocument, User
from backend.rag.vector_store import delete_document_vectors, get_chroma_collection
from backend.rag.hybrid import invalidate_bm25_cache
from scripts.prune_users import resolve_document_filepath, get_doc_vector_count

logger = logging.getLogger("manage_docs")


def list_documents():
    db = SessionLocal()
    collection = None
    try:
        collection = get_chroma_collection()
    except Exception:
        pass

    try:
        docs = db.query(Document).order_by(Document.scope.desc(), Document.filename.asc()).all()
        print(f"\nTotal documents in database: {len(docs)}\n")
        fmt = "{:<38} {:<32} {:<10} {:<30} {:<12} {:<8}"
        print(fmt.format("ID", "FILENAME", "SCOPE", "OWNER", "FILE EXISTS", "CHROMA"))
        print("-" * 135)
        for d in docs:
            owner = db.query(User).filter(User.id == d.owner_id).first()
            owner_label = owner.email if owner else f"User ID {d.owner_id}"
            resolved = resolve_document_filepath(d.id, d.filename, d.filepath, UPLOAD_DIR)
            file_exists = "YES" if (resolved and os.path.exists(resolved)) else "NO"
            chunks = get_doc_vector_count(collection, d.id) if collection else 0
            print(fmt.format(d.id, d.filename[:30], d.scope, owner_label[:28], file_exists, chunks))
        print("\n")
    finally:
        db.close()


def delete_documents(doc_ids: List[str], apply: bool = False):
    db = SessionLocal()
    try:
        docs_to_delete = db.query(Document).filter(Document.id.in_(doc_ids)).all()
        found_ids = {d.id for d in docs_to_delete}
        missing_ids = [did for did in doc_ids if did not in found_ids]

        if missing_ids:
            print(f"[WARNING] Documents not found in database: {', '.join(missing_ids)}")

        if not docs_to_delete:
            print("[INFO] No matching documents found to delete.")
            return

        print("\n" + "=" * 70)
        print("          DELETE DOCUMENTS: " + ("EXECUTION PLAN" if apply else "DRY-RUN"))
        print("=" * 70)
        fmt = "{:<38} {:<30} {:<10} {:<15}"
        print(fmt.format("ID", "FILENAME", "SCOPE", "STORED FILEPATH"))
        print("-" * 95)
        for d in docs_to_delete:
            print(fmt.format(d.id, d.filename[:28], d.scope, (d.filepath or "")[:35]))

        if not apply:
            print("\n[DRY-RUN] No documents were deleted. Pass --apply to execute deletion.\n")
            return

        print("\n[APPLY] Deleting documents from database, Chroma vector store, and disk...")
        for doc in docs_to_delete:
            doc_id = doc.id
            stored_filepath = doc.filepath
            resolved_filepath = resolve_document_filepath(doc_id, doc.filename, stored_filepath, UPLOAD_DIR)

            # 1. Delete DB record
            db.delete(doc)
            db.commit()

            # 2. Delete child ImageAsset and ImageHash records
            db.query(ImageAsset).filter(ImageAsset.doc_id == doc_id).delete(synchronize_session=False)
            db.query(ImageHash).filter(ImageHash.doc_id == doc_id).delete(synchronize_session=False)
            db.query(ConversationDocument).filter(ConversationDocument.doc_id == doc_id).delete(synchronize_session=False)
            db.commit()

            # 3. Delete vector embeddings and disk files using standard delete_document_vectors
            chunks_deleted = delete_document_vectors(doc_id, stored_filepath)

            # Also delete resolved filepath if different from stored_filepath
            if resolved_filepath and os.path.exists(resolved_filepath) and resolved_filepath != stored_filepath:
                try:
                    os.remove(resolved_filepath)
                except OSError:
                    pass

            # Delete any rendered pages matching doc_id
            for rf in glob.glob(os.path.join(RENDERED_PAGES_DIR, f"{doc_id}*")):
                try:
                    os.remove(rf)
                except OSError:
                    pass

            print(f"  [DELETED] {doc_id} ('{doc.filename}') - Chunks removed: {chunks_deleted}")

        # Invalidate BM25 and query caches
        try:
            invalidate_bm25_cache()
        except Exception:
            pass

        print(f"\n[SUCCESS] Successfully deleted {len(docs_to_delete)} document(s).\n")
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="Manage documents in RAG system.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # list subcommand
    subparsers.add_parser("list", help="List all documents")

    # delete subcommand
    delete_parser = subparsers.add_parser("delete", help="Delete documents by ID")
    delete_parser.add_argument("--ids", nargs="+", required=True, help="List of document IDs to delete")
    delete_parser.add_argument("--apply", action="store_true", default=False, help="Execute deletion (default: dry-run)")

    args = parser.parse_args()

    if args.command == "list":
        list_documents()
    elif args.command == "delete":
        delete_documents(args.ids, apply=args.apply)


if __name__ == "__main__":
    main()
