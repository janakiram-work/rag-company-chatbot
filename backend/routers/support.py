from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.database import (
    get_db,
    User,
    SupportRequest,
    SupportMessage,
    create_notification,
    log_audit,
    utcnow,
)
from backend.auth import get_current_user, require_admin
from backend.schemas import (
    SupportRequestCreate,
    SupportMessageCreate,
    SupportStatusUpdate,
)

router = APIRouter(prefix="/api/support", tags=["Support & Inquiries"])


@router.post("/requests")
def create_support_request(
    payload: SupportRequestCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    req = SupportRequest(
        user_id=current_user.id,
        type=payload.type,
        subject=payload.subject.strip(),
        message=payload.message.strip(),
        status="open",
        related_conversation_id=payload.related_conversation_id,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    # Notify all active admins
    admins = db.query(User).filter(User.role == "admin", User.is_active.is_(True)).all()
    for adm in admins:
        create_notification(
            db,
            user_id=adm.id,
            type="new_support_request",
            title="New Support Request",
            body=f"{current_user.display_name or current_user.username}: {req.subject}",
            link=f"/admin/requests",
        )

    log_audit(db, current_user.id, "support_request_created", target=req.id, details=req.subject)
    return req


@router.get("/requests")
def list_my_support_requests(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reqs = (
        db.query(SupportRequest)
        .filter(SupportRequest.user_id == current_user.id)
        .order_by(SupportRequest.updated_at.desc())
        .all()
    )
    return reqs


@router.get("/requests/{req_id}")
def get_support_request_thread(
    req_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    req = db.query(SupportRequest).filter(SupportRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")

    # Authorization: only request owner or admin
    if req.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied")

    messages = (
        db.query(SupportMessage)
        .filter(SupportMessage.request_id == req_id)
        .order_by(SupportMessage.created_at.asc())
        .all()
    )

    msg_data = []
    for m in messages:
        sender = db.query(User).filter(User.id == m.sender_id).first()
        msg_data.append({
            "id": m.id,
            "sender_id": m.sender_id,
            "sender_name": sender.display_name if sender else "User",
            "sender_role": m.sender_role,
            "body": m.body,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        })

    owner = db.query(User).filter(User.id == req.user_id).first()

    return {
        "id": req.id,
        "type": req.type,
        "subject": req.subject,
        "message": req.message,
        "status": req.status,
        "related_conversation_id": req.related_conversation_id,
        "created_at": req.created_at.isoformat() if req.created_at else None,
        "updated_at": req.updated_at.isoformat() if req.updated_at else None,
        "user": {
            "id": owner.id,
            "username": owner.username,
            "display_name": owner.display_name,
            "email": owner.email,
        } if owner else None,
        "messages": msg_data,
    }


@router.post("/requests/{req_id}/messages")
def reply_support_request(
    req_id: str,
    payload: SupportMessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    req = db.query(SupportRequest).filter(SupportRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")

    if req.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied")

    msg = SupportMessage(
        request_id=req.id,
        sender_id=current_user.id,
        sender_role=current_user.role,
        body=payload.body.strip(),
        created_at=utcnow(),
    )
    db.add(msg)
    req.updated_at = utcnow()

    # Re-open request if user replies to a closed/resolved request
    if current_user.id == req.user_id and req.status in ["resolved", "closed"]:
        req.status = "open"

    db.commit()

    # Notifications
    if current_user.role == "admin":
        # Admin replied: notify request owner
        create_notification(
            db,
            user_id=req.user_id,
            type="support_reply",
            title="Support Request Update",
            body=f"An administrator replied to: {req.subject}",
            link=f"/requests/{req.id}",
        )
    else:
        # User replied: notify admins
        admins = db.query(User).filter(User.role == "admin", User.is_active.is_(True)).all()
        for adm in admins:
            create_notification(
                db,
                user_id=adm.id,
                type="support_reply",
                title="Support Request Reply",
                body=f"{current_user.display_name or current_user.username} replied to: {req.subject}",
                link="/admin/requests",
            )

    log_audit(db, current_user.id, "support_message_added", target=req.id)
    return {"status": "success", "message_id": msg.id}


@router.patch("/requests/{req_id}/status")
def update_support_status(
    req_id: str,
    payload: SupportStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    req = db.query(SupportRequest).filter(SupportRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")

    # Normal user can only close their own request
    if current_user.role != "admin":
        if req.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Access denied")
        if payload.status != "closed":
            raise HTTPException(status_code=400, detail="Users may only close requests.")

    old_status = req.status
    req.status = payload.status
    req.updated_at = utcnow()
    db.commit()

    # If admin changed status, notify request owner
    if current_user.role == "admin" and current_user.id != req.user_id:
        create_notification(
            db,
            user_id=req.user_id,
            type="support_status_changed",
            title="Request Status Updated",
            body=f"Your request '{req.subject}' status was updated to {req.status}.",
            link=f"/requests/{req.id}",
        )

    log_audit(db, current_user.id, "support_status_updated", target=req.id, details=f"From {old_status} to {req.status}")
    return {"status": "success", "new_status": req.status}
