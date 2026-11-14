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

export function formatError(err) {
  if (!err) return 'An unexpected error occurred';
  if (typeof err === 'string') {
    if (err.includes('[object Object]')) return 'Enter a valid email address';
    if (
      err.toLowerCase().includes('failed to fetch') ||
      err.toLowerCase().includes('networkerror') ||
      err.toLowerCase().includes('server unreachable')
    ) {
      return 'Cannot reach the server';
    }
    return err;
  }

  const raw = err.response?.data?.detail || err.detail || err.message || err;

  if (typeof raw === 'string') {
    if (
      raw.toLowerCase().includes('failed to fetch') ||
      raw.toLowerCase().includes('networkerror') ||
      raw.toLowerCase().includes('server unreachable')
    ) {
      return 'Cannot reach the server';
    }
    if (raw.includes('[object Object]')) return 'Enter a valid email address';
    return raw;
  }

  if (Array.isArray(raw)) {
    const messages = raw
      .map((item) => {
        if (typeof item === 'string') return item;
        const field = item.loc ? item.loc[item.loc.length - 1] : '';
        const msg = item.msg || item.message || '';
        if (field === 'email') return 'Enter a valid email such as name@company.com';
        if (field === 'password') return 'Password must be at least 6 characters';
        return `${field ? field + ': ' : ''}${msg}`;
      })
      .filter(Boolean);
    return messages.join('. ') || 'Validation error';
  }

  if (typeof raw === 'object') {
    if (raw.msg) return raw.msg;
    if (raw.message) return raw.message;
    if (raw.detail) return formatError(raw.detail);
    try {
      return JSON.stringify(raw);
    } catch {
      return 'An unexpected error occurred';
    }
  }

  return String(raw);
}

async function request(url, options = {}, isRetry = false) {
  const token = getAuthToken();
  const headers = {
    'ngrok-skip-browser-warning': '1',
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
    throw new Error('Cannot reach the server');
  }

  const contentType = res.headers.get('content-type') || '';
  if (contentType.includes('text/html')) {
    throw new Error('The server returned an unexpected response, please reload');
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
          headers: {
            'Content-Type': 'application/json',
            'ngrok-skip-browser-warning': '1',
          },
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
    try {
      await fetch(`${API_BASE}/auth/logout`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'ngrok-skip-browser-warning': '1' },
      });
    } catch {}

    if (hadPriorSession) {
      window.dispatchEvent(
        new CustomEvent('auth-expired', {
          detail: { message: 'Your session ended, please sign in again' },
        })
      );
      throw new Error('Your session ended, please sign in again');
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

    xhr.setRequestHeader('ngrok-skip-browser-warning', '1');
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
      const cType = xhr.getResponseHeader('content-type') || '';
      if (cType.includes('text/html')) {
        reject(new Error('The server returned an unexpected response, please reload'));
        return;
      }
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

    xhr.onerror = () => reject(new Error('Cannot reach the server'));
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
export const apiGetDiagnostics = () => request('/admin/diagnostics');
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
        'ngrok-skip-browser-warning': '1',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ message, ...extraPayload }),
      signal,
    });

    const contentType = res.headers.get('content-type') || '';
    if (contentType.includes('text/html')) {
      throw new Error('The server returned an unexpected response, please reload');
    }

    if (res.status === 401 && !isRetry) {
      try {
        const refreshRes = await fetch(`${API_BASE}/auth/refresh`, {
          method: 'POST',
          credentials: 'include',
          headers: {
            'Content-Type': 'application/json',
            'ngrok-skip-browser-warning': '1',
          },
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
      window.dispatchEvent(
        new CustomEvent('auth-expired', {
          detail: { message: 'Your session ended, please sign in again' },
        })
      );
      throw new Error('Your session ended, please sign in again');
    }

    if (res.status === 503) {
      let errDetail = 'The server is busy processing other requests, please retry in a few seconds.';
      try {
        const errJson = await res.json();
        errDetail = errJson.detail || errDetail;
      } catch {}
      throw new Error(errDetail);
    }

    if (!res.ok) {
      let errorDetail = 'Chat request failed';
      try {
        const errJson = await res.json();
        errorDetail = errJson.detail || errJson.message || errorDetail;
      } catch {
        errorDetail = (await res.text()) || errorDetail;
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
        if (line.startsWith(':')) {
          continue; // SSE heartbeat comment
        }
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6));
            if (data.type === 'error') {
              onError(data.message || 'Stream error');
              return;
            } else if (data.type === 'status') {
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
      onError(formatError(err) || 'Stream connection lost');
    }
  }
}
