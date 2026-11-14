import json
import re
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.database import (
    get_db,
    User,
    Conversation,
    Message,
    UserPreference,
    log_audit,
    utcnow,
)
from backend.auth import (
    get_current_user,
    verify_password_async,
    get_password_hash,
    validate_password_strength,
)
from backend.schemas import (
    UserResponse,
    ProfileUpdateRequest,
    ChangePasswordRequest,
    UserPreferencesRequest,
)

router = APIRouter(prefix="/api/me", tags=["Profile & Preferences"])


@router.get("", response_model=UserResponse)
def get_my_profile(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)


@router.patch("", response_model=UserResponse)
def update_my_profile(
    payload: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.username is not None:
        new_username = payload.username.strip().lower()
        if not re.match(r"^[a-zA-Z0-9_.]{3,30}$", new_username):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username must be 3-30 characters long and contain only letters, numbers, underscores, and dots.",
            )
        # Check uniqueness if username changed
        if new_username != (current_user.username or "").lower():
            existing = db.query(User).filter(
                func.lower(User.username) == new_username,
                User.id != current_user.id,
            ).first()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Username is already taken by another account.",
                )
            current_user.username = new_username

    if payload.display_name is not None:
        display_name = payload.display_name.strip()
        if len(display_name) > 100:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Display name is too long (max 100 characters).")
        current_user.display_name = display_name or current_user.username

    if payload.avatar_color is not None:
        color = payload.avatar_color.strip()
        if not re.match(r"^#[0-9a-fA-F]{6}$", color) and len(color) <= 20:
            pass  # Accept standard hex or tailwind class strings up to 20 chars
        current_user.avatar_color = color[:20]

    db.commit()
    db.refresh(current_user)
    log_audit(db, current_user.id, "profile_updated", target=current_user.email)
    return UserResponse.model_validate(current_user)


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    valid_curr = await verify_password_async(payload.current_password, current_user.password_hash)
    if not valid_curr:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )

    pw_err = validate_password_strength(payload.new_password)
    if pw_err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=pw_err)

    current_user.password_hash = get_password_hash(payload.new_password)
    current_user.token_version += 1
    current_user.must_change_password = False
    db.commit()

    log_audit(db, current_user.id, "password_changed", target=current_user.email)
    return {"status": "success", "message": "Password changed successfully."}


@router.get("/preferences")
def get_user_preferences(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pref = db.query(UserPreference).filter(UserPreference.user_id == current_user.id).first()
    theme = pref.theme if pref else "system"
    return {"theme": theme}


@router.put("/preferences")
def update_user_preferences(
    payload: UserPreferencesRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pref = db.query(UserPreference).filter(UserPreference.user_id == current_user.id).first()
    if not pref:
        pref = UserPreference(user_id=current_user.id, theme=payload.theme)
        db.add(pref)
    else:
        pref.theme = payload.theme
    db.commit()
    return {"status": "success", "theme": pref.theme}


@router.delete("/conversations")
def delete_my_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    count = db.query(Conversation).filter(Conversation.user_id == current_user.id).delete()
    db.commit()
    log_audit(db, current_user.id, "conversations_cleared", details=f"Deleted {count} chats")
    return {"status": "success", "message": f"Deleted {count} conversations."}


@router.get("/export")
def export_my_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    convs = (
        db.query(Conversation)
        .filter(Conversation.user_id == current_user.id)
        .order_by(Conversation.created_at.desc())
        .all()
    )

    result = []
    for c in convs:
        msgs = (
            db.query(Message)
            .filter(Message.conversation_id == c.id)
            .order_by(Message.created_at.asc())
            .all()
        )
        msg_list = []
        for m in msgs:
            sources = []
            if m.sources_json:
                try:
                    sources = json.loads(m.sources_json)
                except Exception:
                    pass
            msg_list.append({
                "id": m.id,
                "sender": m.sender,
                "content": m.content,
                "sources": sources,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            })

        result.append({
            "id": c.id,
            "title": c.title,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            "messages": msg_list,
        })

    log_audit(db, current_user.id, "conversations_exported", details=f"Exported {len(result)} chats")
    return result
