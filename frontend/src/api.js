const API_BASE = '/api';

export const getAuthToken = () => localStorage.getItem('app_token') || localStorage.getItem('acme_token');
export const setAuthToken = (token) => {
  localStorage.setItem('app_token', token);
  localStorage.setItem('acme_token', token);
};
export const removeAuthToken = () => {
  localStorage.removeItem('app_token');
  localStorage.removeItem('app_user');
  localStorage.removeItem('acme_token');
  localStorage.removeItem('acme_user');
};

export const getStoredUser = () => {
  try {
    const raw = localStorage.getItem('app_user') || localStorage.getItem('acme_user');
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
};
export const setStoredUser = (user) => {
  localStorage.setItem('app_user', JSON.stringify(user));
  localStorage.setItem('acme_user', JSON.stringify(user));
};

async function request(url, options = {}, isRetry = false) {
  const token = getAuthToken();
  const headers = {
    ...(options.headers || {}),
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  if (!(options.body instanceof FormData) && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }

  const isAuthEndpoint =
    url.includes('/auth/login') ||
    url.includes('/auth/register') ||
    url.includes('/auth/refresh');

  let res;
  try {
    res = await fetch(`${API_BASE}${url}`, {
      ...options,
      credentials: 'include',
      headers,
    });
  } catch (netErr) {
    throw new Error('Server unreachable');
  }

  if (res.status === 401) {
    if (isAuthEndpoint) {
      if (url.includes('/auth/login')) {
        throw new Error('Invalid email or password');
      }
      let errDetail = 'Unauthorized';
      try {
        const errJson = await res.json();
        errDetail = errJson.detail || errJson.message || errDetail;
      } catch {}
      throw new Error(errDetail);
    }

    const hadPriorSession = !!getAuthToken() || !!getStoredUser();
    if (!isRetry && hadPriorSession) {
      try {
        const refreshRes = await fetch(`${API_BASE}/auth/refresh`, {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
        });
        if (refreshRes.ok) {
          const refreshData = await refreshRes.json();
          if (refreshData.access_token) {
            setAuthToken(refreshData.access_token);
          }
          if (refreshData.user) {
            setStoredUser(refreshData.user);
          }
          return request(url, options, true);
        }
      } catch {
        // Refresh failed, proceed to handle 401
      }
    }

    removeAuthToken();
    if (hadPriorSession) {
      window.dispatchEvent(
        new CustomEvent('auth-expired', {
          detail: { message: 'Session expired. Please log in again.' },
        })
      );
      throw new Error('Session expired. Please log in again.');
    } else {
      throw new Error('Unauthorized');
    }
  }

  if (res.status === 429) {
    let errDetail = 'Too many attempts. Try again in 60 seconds';
    try {
      const errJson = await res.json();
      errDetail = errJson.detail || errJson.message || errDetail;
    } catch {
      errDetail = (await res.text()) || errDetail;
    }
    throw new Error(errDetail);
  }

  if (!res.ok) {
    let errorDetail = 'Request failed';
    try {
      const errJson = await res.json();
      errorDetail = errJson.detail || errJson.message || errorDetail;
    } catch {
      errorDetail = (await res.text()) || errorDetail;
    }
    throw new Error(errorDetail);
  }

  const contentType = res.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    return res.json();
  }
  return res.text();
}

// Authentication API
export const apiLogin = (email, password) =>
  request('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });

export const apiRegister = (email, password) =>
  request('/auth/register', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });

export const apiLogout = () =>
  request('/auth/logout', {
    method: 'POST',
  });

export const apiGetMe = () => request('/auth/me');

// Conversations API
export const apiGetConversations = () => request('/conversations');
export const apiCreateConversation = (title, active_doc_id = null) =>
  request('/conversations', {
    method: 'POST',
    body: JSON.stringify({ title, active_doc_id }),
  });
export const apiGetConversation = (id) => request(`/conversations/${id}`);
export const apiDeleteConversation = (id) =>
  request(`/conversations/${id}`, { method: 'DELETE' });
export const apiUpdateFilter = (conversationId, docId) =>
  request(`/conversations/${conversationId}/filter?doc_id=${docId || ''}`, {
    method: 'PUT',
  });
export const apiRemoveAttachment = (conversationId, docId) =>
  request(`/conversations/${conversationId}/documents/${docId}`, {
    method: 'DELETE',
  });
export const apiClearAllAttachments = (conversationId) =>
  request(`/conversations/${conversationId}/documents`, {
    method: 'DELETE',
  });
export const apiGetAttachments = (conversationId) =>
  request(`/conversations/${conversationId}/documents`);

// Documents API
export const apiUploadDocument = (file, conversationId = null, onUploadProgress = null) => {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const query = conversationId ? `?conversation_id=${encodeURIComponent(conversationId)}` : '';
    xhr.open('POST', `${API_BASE}/documents/upload${query}`);
    xhr.withCredentials = true;

    const token = getAuthToken();
    if (token) {
      xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    }

    if (xhr.upload && onUploadProgress) {
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable && event.total > 0) {
          const percent = Math.round((event.loaded * 100) / event.total);
          onUploadProgress(percent, event.loaded, event.total);
        }
      };
    }

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const data = JSON.parse(xhr.responseText);
          resolve(data);
        } catch {
          resolve(xhr.responseText);
        }
      } else {
        try {
          const errData = JSON.parse(xhr.responseText);
          reject(new Error(errData.detail || 'Upload failed'));
        } catch {
          reject(new Error(`Upload failed with status ${xhr.status}`));
        }
      }
    };

    xhr.onerror = () => reject(new Error('Network error during upload'));
    xhr.ontimeout = () => reject(new Error('Upload timed out'));

    const formData = new FormData();
    formData.append('file', file);
    xhr.send(formData);
  });
};

export const apiGetDocumentStatus = (docId) => request(`/documents/${docId}/status`);
export const apiGetUserDocuments = () => request('/documents/user');

// Admin API
export const apiGetAdminStats = () => request('/admin/stats');
export const apiGetAnalytics = () => request('/admin/analytics');
export const apiGetAdminDocuments = () => request('/admin/documents');
export const apiDeleteAdminDocument = (docId) =>
  request(`/admin/documents/${docId}`, { method: 'DELETE' });
export const apiGetAdminUsers = () => request('/admin/users');
export const apiGetAdminUserConversations = (userId) =>
  request(`/admin/users/${userId}/conversations`);

// Feedback API
export const apiSubmitFeedback = (messageId, rating, comment = null) =>
  request(`/messages/${messageId}/feedback`, {
    method: 'POST',
    body: JSON.stringify({ rating, comment }),
  });

// Streaming SSE Chat Message
export async function apiStreamChatMessage(
  conversationId,
  message,
  onToken,
  onDone,
  onError,
  onStatus = null,
  signal = null,
  extraPayload = {},
  isRetry = false
) {
  const token = getAuthToken();
  try {
    const res = await fetch(`${API_BASE}/conversations/${conversationId}/messages`, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ message, ...extraPayload }),
      signal,
    });

    if (res.status === 401 && !isRetry) {
      try {
        const refreshRes = await fetch(`${API_BASE}/auth/refresh`, {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
        });
        if (refreshRes.ok) {
          const refreshData = await refreshRes.json();
          if (refreshData.access_token) {
            setAuthToken(refreshData.access_token);
          }
          if (refreshData.user) {
            setStoredUser(refreshData.user);
          }
          return apiStreamChatMessage(
            conversationId,
            message,
            onToken,
            onDone,
            onError,
            onStatus,
            signal,
            extraPayload,
            true
          );
        }
      } catch {
        // Refresh failed, proceed to error handling
      }

      removeAuthToken();
      window.dispatchEvent(new Event('auth-expired'));
      throw new Error('Session expired. Please log in again.');
    }

    if (!res.ok) {
      let errorDetail = 'Chat request failed';
      try {
        const errJson = await res.json();
        errorDetail = errJson.detail || errJson.message || errorDetail;
      } catch {
        errorDetail = await res.text() || errorDetail;
      }
      throw new Error(errorDetail);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n\n');
      buffer = lines.pop() || '';

      for (const block of lines) {
        const line = block.trim();
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6));
            if (data.type === 'status') {
              if (onStatus) onStatus(data.message);
            } else if (data.type === 'token') {
              onToken(data.content);
            } else if (data.type === 'done') {
              onDone(data.sources || [], data.images || [], data);
            }
          } catch {
            // ignore JSON parse of malformed chunk
          }
        }
      }
    }
  } catch (err) {
    if (err.name !== 'AbortError') {
      onError(err.message || 'Stream connection lost');
    }
  }
}
