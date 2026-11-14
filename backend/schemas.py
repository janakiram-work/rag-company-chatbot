from typing import List, Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict, model_validator

EMAIL_REGEX = r"^[\w\.-]+@[\w\.-]+\.\w+$"


# User Schemas
class UserRegisterRequest(BaseModel):
    username: Optional[str] = Field(None, min_length=3, max_length=30, pattern=r"^[a-zA-Z0-9_.]+$")
    email: str = Field(..., pattern=EMAIL_REGEX)
    password: str = Field(..., min_length=8)
    display_name: Optional[str] = None


class UserLoginRequest(BaseModel):
    identifier: Optional[str] = None  # Accepts either username or email
    username: Optional[str] = None
    email: Optional[str] = Field(None, pattern=EMAIL_REGEX)       # Backward compatibility
    password: str

    @model_validator(mode="after")
    def validate_identifier(self):
        if not (self.identifier or self.username or self.email):
            raise ValueError("Either identifier, username or email is required")
        return self


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    username: Optional[str] = None
    display_name: Optional[str] = None
    avatar_color: Optional[str] = None
    role: str
    is_active: bool = True
    must_change_password: bool = False
    token_version: int = 0
    last_login_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class ForgotPasswordRequest(BaseModel):
    identifier: str = Field(..., min_length=1)


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)


class ProfileUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    username: Optional[str] = None
    avatar_color: Optional[str] = None


class UserPreferencesRequest(BaseModel):
    theme: str = Field(..., pattern=r"^(light|dark|system)$")


class BrandingUpdateRequest(BaseModel):
    company_name: Optional[str] = None
    tagline: Optional[str] = None
    accent_color: Optional[str] = None


class SupportRequestCreate(BaseModel):
    type: str = Field(..., pattern=r"^(question|document_access|issue|feature)$")
    subject: str = Field(..., min_length=1, max_length=255)
    message: str = Field(..., min_length=1)
    related_conversation_id: Optional[str] = None


class SupportMessageCreate(BaseModel):
    body: str = Field(..., min_length=1)


class SupportStatusUpdate(BaseModel):
    status: str = Field(..., pattern=r"^(open|in_progress|resolved|closed)$")


class AdminUserCreateRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=30, pattern=r"^[a-zA-Z0-9_.]+$")
    email: str = Field(..., pattern=EMAIL_REGEX)
    password: str = Field(..., min_length=8)
    role: str = "user"
    display_name: Optional[str] = None


class AdminUserUpdateRequest(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None
    display_name: Optional[str] = None


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
    username: Optional[str] = None
    display_name: Optional[str] = None
    avatar_color: Optional[str] = None
    role: str
    is_active: bool = True
    must_change_password: bool = False
    last_login_at: Optional[datetime] = None
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
