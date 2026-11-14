# REST and SSE API Reference

The Enterprise RAG Assistant exposes REST endpoints and Server-Sent Events (SSE) streaming connections. Authentication uses JWT Bearer tokens in the `Authorization` header (`Bearer <token>`) or `access_token` in HTTP cookies.

---

## 1. Authentication and User Endpoints

| Method | Endpoint | Access | Description |
|---|---|---|---|
| `POST` | `/api/auth/register` | Public | Register new account (always created with `role="user"`). |
| `POST` | `/api/auth/login` | Public | Authenticate with username or email and password. Sets `access_token` and `refresh_token` httpOnly cookies. |
| `POST` | `/api/auth/refresh` | Public | Refresh expired access token using refresh token cookie. |
| `POST` | `/api/auth/logout` | Authenticated | Invalidate token and clear auth cookies. |
| `GET` | `/api/auth/me` | Authenticated | Retrieve current user profile (`id`, `email`, `username`, `display_name`, `role`, `avatar_color`, `must_change_password`). |
| `POST` | `/api/auth/forgot-password` | Public | Request password reset. If SMTP is configured, sends email; otherwise creates pending request in Admin Approval inbox. |
| `POST` | `/api/auth/reset-password` | Public | Complete password reset using token. |

---

## 2. Chat and Conversation Endpoints

| Method | Endpoint | Access | Description |
|---|---|---|---|
| `GET` | `/api/conversations` | Authenticated | List all conversations for the current user. |
| `POST` | `/api/conversations` | Authenticated | Create a new conversation (`title`, optional initial document attachment). |
| `GET` | `/api/conversations/{id}` | Authenticated | Retrieve conversation details and message history. |
| `PATCH` | `/api/conversations/{id}` | Authenticated | Rename conversation title. |
| `DELETE` | `/api/conversations/{id}` | Authenticated | Delete conversation and associated messages. |
| `POST` | `/api/chat/messages` | Authenticated | Stream chat completion over Server-Sent Events (SSE). |
| `POST` | `/api/chat/clarification` | Authenticated | Submit clarification choice or free-text answer to continue conversational stream. |
| `POST` | `/api/chat/feedback` | Authenticated | Submit user rating (`up` / `down`) and optional comment on an assistant message. |

### Chat SSE Event Format (`/api/chat/messages`)

The endpoint streams JSON-encoded SSE events:
- `data: {"type": "token", "content": "..."}`: Real-time text token chunk.
- `data: {"type": "citations", "sources": [...]}`: Final document citation chips.
- `data: {"type": "images", "images": [...]}`: Relevant figure or diagram image URLs.
- `data: {"type": "clarification", "options": [...]}`: Interactive clarification choices.
- `data: {"type": "done"}`: Stream completion signal.

---

## 3. Documents and Knowledge Base Endpoints

| Method | Endpoint | Access | Description |
|---|---|---|---|
| `GET` | `/api/documents` | Authenticated | List documents. Users receive company documents + private documents; admins see all. |
| `POST` | `/api/documents/upload` | Authenticated | Upload PDF, DOCX, TXT, PNG, or JPG document. Admins upload to company scope; users upload to conversation scope. |
| `GET` | `/api/documents/{id}` | Authenticated | Retrieve processing status (`processing`, `ready`, `failed`) and chunk counts. |
| `GET` | `/api/documents/{id}/download`| Authenticated | Download original document file. |
| `DELETE` | `/api/documents/{id}` | Authenticated / Owner | Delete document. Cascades through database, ChromaDB vectors, and storage files. |

---

## 4. Real-Time Events SSE Endpoint

| Method | Endpoint | Access | Description |
|---|---|---|---|
| `GET` | `/api/events` | Authenticated | Real-time Server-Sent Events stream for application updates. Accepts cookie or `?token=` parameter. Includes 20-second heartbeat comment (`: ping`). |

### Event Types Dispatched Over `/api/events`

- `new_notification`: Dispatched to user when an admin replies to a support request or status updates.
- `request_updated`: Dispatched when an admin or user appends a message to a support thread.
- `branding_updated`: Dispatched to all connected users when admin updates company name, logo, or theme accent color.
- `user_changed`: Dispatched to admins when a user is created, updated, or deactivated.
- `document_status`: Dispatched when background document processing completes (`ready` or `failed`).
- `session_invalidated`: Dispatched to target user when deactivated or deleted, triggering immediate client logout.

---

## 5. Administration Endpoints (Admin Role Only)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/admin/stats` | System overview stats (users, company docs, chunk counts, messages, storage). |
| `GET` | `/api/admin/users` | Paginated user management table with search and role filters. Returns `{items, total, page, limit}`. |
| `POST` | `/api/admin/users` | Create user account manually. |
| `PATCH` | `/api/admin/users/{id}` | Update user role (`admin` / `user`) or active status (`is_active`). |
| `POST` | `/api/admin/users/{id}/force-password-reset` | Require user to choose a new password on their next login. |
| `DELETE` | `/api/admin/users/{id}` | Deactivates user (default) or permanently deletes user with cascade when `?permanent=true`. |
| `GET` | `/api/admin/audit` | Paginated immutable audit log entries. Returns `{items, total, page, limit}`. |
| `GET` | `/api/admin/diagnostics` | System diagnostics: memory usage, active streams, model cache, and dependencies. |
| `GET` | `/api/admin/analytics` | Analytics metrics: daily queries, feedback ratings, latency distributions. |
| `GET` | `/api/admin/chats/{user_id}` | Inspect historical conversation transcripts for a specific user. |
| `GET` | `/api/admin/password-resets` | List pending password reset requests awaiting approval. |
| `POST` | `/api/admin/password-resets/{id}/approve` | Approve reset request; generates single-use reset link. |
| `POST` | `/api/admin/password-resets/{id}/reject` | Reject reset request. |
| `PUT` | `/api/admin/settings/branding` | Update company branding (name, tagline, accent color). |
| `POST` | `/api/admin/settings/logo` | Upload custom branding logo (PNG, JPG, SVG). |
| `DELETE` | `/api/admin/settings/logo` | Reset custom logo to default. |

---

## 6. Profile and Support Endpoints

| Method | Endpoint | Access | Description |
|---|---|---|---|
| `GET` | `/api/profile` | Authenticated | Get user profile and preferences (theme, notification settings). |
| `PATCH` | `/api/profile` | Authenticated | Update display name and avatar color. |
| `PUT` | `/api/profile/preferences` | Authenticated | Update user interface preferences. |
| `POST` | `/api/profile/change-password` | Authenticated | Change password (requires existing password validation). |
| `GET` | `/api/profile/export-chats` | Authenticated | Export personal chat conversations and messages as JSON. |
| `DELETE` | `/api/profile/delete-chats` | Authenticated | Permanently delete all personal conversation history. |
| `POST` | `/api/support/requests` | Authenticated | Submit an "Ask Admin" support or access request. |
| `GET` | `/api/support/requests` | Authenticated | List user support requests (or all requests for admins). |
| `GET` | `/api/support/requests/{id}` | Authenticated | Retrieve thread messages for a specific request. |
| `POST` | `/api/support/requests/{id}/messages` | Authenticated | Send a message reply within a support request thread. |
| `PATCH` | `/api/support/requests/{id}/status` | Admin | Update request status (`open`, `in_progress`, `resolved`, `closed`). |
| `GET` | `/api/notifications` | Authenticated | List user notifications. |
| `PATCH` | `/api/notifications/{id}/read` | Authenticated | Mark single notification as read. |
| `POST` | `/api/notifications/mark-all-read` | Authenticated | Mark all notifications as read. |

---

## 7. System Health and Metadata Endpoints

| Method | Endpoint | Access | Description |
|---|---|---|---|
| `GET` | `/health` | Public | System health check (database, ChromaDB, Groq configuration, memory). |
| `GET` | `/api/health` | Public | Alias to `/health`. |
| `GET` | `/api/config` | Public | Public company branding, version, and demo mode flags. |
| `GET` | `/api/branding/logo` | Public | Serve active company logo image. |
| `GET` | `/api/images/{filename}` | Authenticated / Token | Serve document-extracted image or rendered PDF page with RBAC access check. |
