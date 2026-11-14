import React, { useState, useEffect } from 'react';
import LoginPage from './components/LoginPage';
import Sidebar from './components/Sidebar';
import ChatArea from './components/ChatArea';
import AdminDashboard from './components/AdminDashboard';
import FloatingAdminChat from './components/FloatingAdminChat';
import SettingsModal from './components/SettingsModal';
import ContactAdminModal from './components/ContactAdminModal';
import ErrorBoundary from './components/ErrorBoundary';
import {
  getAuthToken,
  getStoredUser,
  removeAuthToken,
  apiGetMe,
  apiLogout,
  apiGetConversations,
  apiCreateConversation,
  apiGetConversation,
  apiDeleteConversation,
} from './api';

export default function App() {
  const [currentUser, setCurrentUser] = useState(getStoredUser());
  const [isAuthenticated, setIsAuthenticated] = useState(!!getAuthToken());
  const [sessionExpiredMsg, setSessionExpiredMsg] = useState('');
  const [currentView, setCurrentView] = useState('chat'); // 'chat' | 'admin'
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false);

  // Branding State (cached in localStorage to avoid flicker)
  const [branding, setBranding] = useState(() => {
    try {
      const cached = localStorage.getItem('app_branding');
      return cached ? JSON.parse(cached) : null;
    } catch {
      return null;
    }
  });

  // Modals state
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [settingsInitialTab, setSettingsInitialTab] = useState('profile');
  const [isContactAdminOpen, setIsContactAdminOpen] = useState(false);
  const [contactAdminQuestion, setContactAdminQuestion] = useState('');
  const [contactAdminConvId, setContactAdminConvId] = useState(null);

  // Dark Mode State
  const [isDarkMode, setIsDarkMode] = useState(() => {
    return (
      localStorage.getItem('app_theme') === 'dark' ||
      localStorage.getItem('acme_theme') === 'dark' ||
      (!('app_theme' in localStorage) &&
        !('acme_theme' in localStorage) &&
        window.matchMedia('(prefers-color-scheme: dark)').matches)
    );
  });

  // Apply document title on mount from cache
  useEffect(() => {
    if (branding?.company_name) {
      document.title = `${branding.company_name} Assistant`;
    }
  }, []);

  // Fetch /api/config for live branding before render
  useEffect(() => {
    fetch('/api/config')
      .then((res) => res.json())
      .then((cfg) => {
        if (cfg && cfg.branding) {
          setBranding(cfg.branding);
          localStorage.setItem('app_branding', JSON.stringify(cfg.branding));
          if (cfg.branding.company_name) {
            document.title = `${cfg.branding.company_name} Assistant`;
          }
        }
      })
      .catch(() => {});
  }, []);

  // Conversations State
  const [conversations, setConversations] = useState([]);
  const [activeConversationId, setActiveConversationId] = useState(null);
  const [activeConversation, setActiveConversation] = useState(null);
  const [isLoadingConversation, setIsLoadingConversation] = useState(false);

  // Apply dark mode class
  useEffect(() => {
    if (isDarkMode) {
      document.documentElement.classList.add('dark');
      localStorage.setItem('app_theme', 'dark');
      localStorage.setItem('acme_theme', 'dark');
    } else {
      document.documentElement.classList.remove('dark');
      localStorage.setItem('app_theme', 'light');
      localStorage.setItem('acme_theme', 'light');
    }
  }, [isDarkMode]);

  // Check auth session on mount only if token or refresh cookie exists
  useEffect(() => {
    const hasToken = !!getAuthToken();
    const hasRefreshCookie = document.cookie.includes('refresh_token');

    if (hasToken || hasRefreshCookie) {
      apiGetMe()
        .then((user) => {
          setCurrentUser(user);
          setIsAuthenticated(true);
        })
        .catch(() => {
          removeAuthToken();
          setIsAuthenticated(false);
          setCurrentUser(null);
        });
    } else {
      setIsAuthenticated(false);
      setCurrentUser(null);
    }

    const handleExpired = (e) => {
      setIsAuthenticated(false);
      setCurrentUser(null);
      if (e?.detail?.message) {
        setSessionExpiredMsg(e.detail.message);
      }
    };
    window.addEventListener('auth-expired', handleExpired);
    return () => window.removeEventListener('auth-expired', handleExpired);
  }, []);

  // Server-Sent Events (SSE) live updates stream
  useEffect(() => {
    if (!isAuthenticated) return;

    let es = null;
    let reconnectTimeout = null;
    let retryDelay = 2000;
    let isCleanedUp = false;

    const connectSSE = () => {
      if (isCleanedUp) return;
      try {
        es = new EventSource('/api/events', { withCredentials: true });

        es.onopen = () => {
          retryDelay = 2000;
        };

        es.onmessage = (e) => {
          if (!e.data) return;
          try {
            const payload = JSON.parse(e.data);
            const { type, data } = payload;

            if (type === 'branding_updated' && data) {
              setBranding(data);
              localStorage.setItem('app_branding', JSON.stringify(data));
              if (data.company_name) {
                document.title = `${data.company_name} Assistant`;
              }
            } else if (type === 'new_notification') {
              window.dispatchEvent(new CustomEvent('app-new-notification', { detail: data }));
            } else if (type === 'request_updated') {
              window.dispatchEvent(new CustomEvent('admin-requests-changed', { detail: data }));
            } else if (type === 'user_changed') {
              window.dispatchEvent(new CustomEvent('admin-users-changed', { detail: data }));
            } else if (type === 'document_status') {
              window.dispatchEvent(new CustomEvent('app-document-status', { detail: data }));
            } else if (type === 'session_invalidated') {
              const msg = data?.reason || 'Your session has ended. Please sign in again.';
              setSessionExpiredMsg(msg);
              apiLogout().catch(() => {});
              removeAuthToken();
              setIsAuthenticated(false);
              setCurrentUser(null);
            }
          } catch (err) {
            console.error('Failed to parse SSE event:', err);
          }
        };

        es.onerror = () => {
          if (es) {
            es.close();
            es = null;
          }
          if (!isCleanedUp) {
            reconnectTimeout = setTimeout(() => {
              retryDelay = Math.min(retryDelay * 1.5, 30000);
              connectSSE();
            }, retryDelay);
          }
        };
      } catch (err) {
        console.error('Error opening SSE connection:', err);
      }
    };

    connectSSE();

    return () => {
      isCleanedUp = true;
      if (reconnectTimeout) clearTimeout(reconnectTimeout);
      if (es) {
        es.close();
        es = null;
      }
    };
  }, [isAuthenticated]);

  // Load conversations when authenticated
  const loadConversations = async () => {
    try {
      const convs = await apiGetConversations();
      setConversations(convs);
      if (convs.length > 0 && !activeConversationId) {
        selectConversation(convs[0].id);
      } else if (convs.length === 0) {
        setActiveConversationId(null);
        setActiveConversation({
          id: null,
          title: 'New Chat',
          messages: [],
          active_doc_id: null,
        });
      }
    } catch (err) {
      console.error('Failed to load conversations:', err);
    }
  };

  useEffect(() => {
    if (isAuthenticated) {
      loadConversations();
    }
  }, [isAuthenticated]);

  const selectConversation = async (id) => {
    setActiveConversationId(id);
    if (currentView !== 'chat') setCurrentView('chat');
    setIsLoadingConversation(true);
    try {
      const fullConv = await apiGetConversation(id);
      setActiveConversation(fullConv);
    } catch (err) {
      console.error('Failed to fetch conversation:', err);
    } finally {
      setIsLoadingConversation(false);
    }
  };

  const handleNewChat = () => {
    setActiveConversationId(null);
    setActiveConversation(null);
    if (currentView !== 'chat') setCurrentView('chat');
  };

  const handleConversationCreated = (newConv) => {
    setActiveConversationId(newConv.id);
    setActiveConversation((prev) => ({
      ...(prev || {}),
      id: newConv.id,
      title: newConv.title || 'New Chat',
      active_doc_id: newConv.active_doc_id || null,
      active_doc_name: newConv.active_doc_name || null,
    }));
    setConversations((prev) => {
      if (prev.some((c) => c.id === newConv.id)) return prev;
      return [newConv, ...prev];
    });
  };

  const handleDeleteConversation = async (id) => {
    try {
      await apiDeleteConversation(id);
      const remaining = conversations.filter((c) => c.id !== id);
      setConversations(remaining);
      if (activeConversationId === id) {
        if (remaining.length > 0) {
          selectConversation(remaining[0].id);
        } else {
          handleNewChat();
        }
      }
    } catch (err) {
      alert(`Delete conversation failed: ${err.message}`);
    }
  };

  const handleConversationDone = (doneData) => {
    if (!doneData || !doneData.conversation_id) return;

    const convId = doneData.conversation_id;
    const newTitle = doneData.title || 'New Chat';
    const activeDocId = doneData.active_doc_id || null;
    const activeDocName = doneData.active_doc_name || null;

    setActiveConversationId(convId);
    setActiveConversation((prev) => {
      if (!prev) return null;
      return {
        ...prev,
        id: convId,
        title: newTitle,
        active_doc_id: activeDocId,
        active_doc_name: activeDocName,
      };
    });

    setConversations((prev) => {
      const exists = prev.some((c) => c.id === convId);
      if (exists) {
        return prev.map((c) =>
          c.id === convId
            ? { ...c, title: newTitle, active_doc_id: activeDocId, active_doc_name: activeDocName }
            : c
        );
      } else {
        return [
          {
            id: convId,
            title: newTitle,
            active_doc_id: activeDocId,
            active_doc_name: activeDocName,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
          ...prev,
        ];
      }
    });
  };

  const handleLogout = async () => {
    try {
      await apiLogout();
    } catch {
      // Ignore network errors on logout
    }
    removeAuthToken();
    setIsAuthenticated(false);
    setCurrentUser(null);
    setConversations([]);
    setActiveConversation(null);
    setActiveConversationId(null);
  };

  const handleOpenSettings = (tab = 'profile') => {
    setSettingsInitialTab(tab);
    setIsSettingsOpen(true);
  };

  const handleOpenContactAdmin = (initialQuestion = '', convId = null) => {
    setContactAdminQuestion(initialQuestion);
    setContactAdminConvId(convId);
    setIsContactAdminOpen(true);
  };

  const handleBrandingUpdated = (newBranding) => {
    setBranding(newBranding);
    localStorage.setItem('app_branding', JSON.stringify(newBranding));
    if (newBranding?.company_name) {
      document.title = `${newBranding.company_name} Assistant`;
    }
  };

  const handleAllConversationsDeleted = () => {
    setConversations([]);
    setActiveConversation(null);
    setActiveConversationId(null);
    setIsSettingsOpen(false);
  };

  if (!isAuthenticated) {
    return (
      <LoginPage
        initialError={sessionExpiredMsg}
        onLoginSuccess={(user) => {
          setSessionExpiredMsg('');
          setCurrentUser(user);
          setIsAuthenticated(true);
        }}
      />
    );
  }

  return (
    <ErrorBoundary title="App Error">
      <div className="flex h-[100dvh] w-screen overflow-hidden bg-white dark:bg-zinc-950">
        {/* Sidebar Navigation */}
        <Sidebar
          conversations={conversations}
          activeConversationId={activeConversationId}
          onSelectConversation={selectConversation}
          onNewChat={handleNewChat}
          onDeleteConversation={handleDeleteConversation}
          currentUser={currentUser}
          currentView={currentView}
          onSwitchView={setCurrentView}
          isDarkMode={isDarkMode}
          onToggleDarkMode={() => setIsDarkMode(!isDarkMode)}
          onLogout={handleLogout}
          isMobileOpen={isMobileSidebarOpen}
          onCloseMobile={() => setIsMobileSidebarOpen(false)}
          branding={branding}
          onOpenSettings={handleOpenSettings}
          onOpenContactAdmin={handleOpenContactAdmin}
        />

        {/* Main Content Area */}
        <main className="flex-1 flex flex-col h-[100dvh] overflow-hidden relative">
          <div className={currentView === 'chat' ? 'flex-1 flex flex-col h-full overflow-hidden' : 'hidden'}>
            <ErrorBoundary title="Failed to render chat">
              <ChatArea
                conversation={activeConversation}
                isLoadingConversation={isLoadingConversation}
                onRefreshConversation={() => activeConversationId && selectConversation(activeConversationId)}
                onConversationDone={handleConversationDone}
                onConversationCreated={handleConversationCreated}
                currentUser={currentUser}
                onToggleMobileSidebar={() => setIsMobileSidebarOpen((prev) => !prev)}
                branding={branding}
                onOpenContactAdmin={handleOpenContactAdmin}
              />
            </ErrorBoundary>
          </div>
          {currentUser?.role === 'admin' && (
            <div className={currentView === 'admin' ? 'flex-1 flex flex-col h-full overflow-hidden relative' : 'hidden'}>
              <ErrorBoundary title="Failed to render Admin Console">
                <AdminDashboard onBackToChat={() => setCurrentView('chat')} />
                <FloatingAdminChat />
              </ErrorBoundary>
            </div>
          )}
        </main>

        {/* Settings Modal */}
        <SettingsModal
          isOpen={isSettingsOpen}
          onClose={() => setIsSettingsOpen(false)}
          currentUser={currentUser}
          onUserUpdated={(updated) => setCurrentUser(updated)}
          branding={branding}
          onBrandingUpdated={handleBrandingUpdated}
          isDarkMode={isDarkMode}
          onToggleDarkMode={() => setIsDarkMode(!isDarkMode)}
          onAllConversationsDeleted={handleAllConversationsDeleted}
          initialTab={settingsInitialTab}
        />

        {/* Contact Admin Modal */}
        <ContactAdminModal
          isOpen={isContactAdminOpen}
          onClose={() => setIsContactAdminOpen(false)}
          initialQuestion={contactAdminQuestion}
          conversationId={contactAdminConvId}
        />
      </div>
    </ErrorBoundary>
  );
}
