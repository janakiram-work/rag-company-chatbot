from typing import List, Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

EMAIL_REGEX = r"^[\w\.-]+@[\w\.-]+\.\w+$"


# User Schemas
class UserRegisterRequest(BaseModel):
    email: str = Field(..., pattern=EMAIL_REGEX)
    password: str = Field(..., min_length=6)


class UserLoginRequest(BaseModel):
    email: str = Field(..., pattern=EMAIL_REGEX)
    password: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: str
    created_at: Optional[datetime] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# Conversation Schemas
class ConversationCreate(BaseModel):
    title: Optional[str] = "New Chat"
    active_doc_id: Optional[str] = None


class SourceCitation(BaseModel):
    filename: str
    location_label: str  # "page 2", "section 1", "image"
    page: Optional[int] = None
    section: Optional[str] = None
    file_type: Optional[str] = None
    excerpt: Optional[str] = None


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    sender: str
    content: str
    sources: Optional[List[SourceCitation]] = []
    images: Optional[List[Any]] = []
    meta: Optional[Any] = None
    feedback: Optional[dict] = None
    latency_ms: Optional[float] = None
    created_at: Optional[datetime] = None


class FeedbackRequest(BaseModel):
    rating: Optional[str] = None  # 'up', 'down', or None (to remove)
    comment: Optional[str] = None


class AttachedDocumentItem(BaseModel):
    id: str
    filename: str
    file_type: Optional[str] = None
    status: Optional[str] = "ready"
    attached_at: Optional[datetime] = None


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    active_doc_id: Optional[str] = None
    active_doc_name: Optional[str] = None
    attached_documents: Optional[List[AttachedDocumentItem]] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    messages: Optional[List[MessageResponse]] = []


# Document Schemas
class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    file_type: str
    scope: str
    owner_id: int
    status: str
    page_count: int
    chunk_count: int
    file_size: int
    uploaded_at: Optional[datetime] = None
    error_message: Optional[str] = None


# Admin Schemas
class AdminUserDetail(BaseModel):
    id: int
    email: str
    role: str
    created_at: Optional[datetime] = None
    chat_count: int
    doc_count: int


class AdminStats(BaseModel):
    total_users: int
    total_company_docs: int
    total_user_docs: int
    total_chunks: int
    total_messages: int
    storage_mb: float


# Chat Request
class ChatMessageRequest(BaseModel):
    message: str
    selected_option: Optional[Any] = None
    offset: Optional[int] = 0
