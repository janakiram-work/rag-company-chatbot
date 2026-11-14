import React, { useState, useEffect } from 'react';
import LoginPage from './components/LoginPage';
import Sidebar from './components/Sidebar';
import ChatArea from './components/ChatArea';
import AdminDashboard from './components/AdminDashboard';
import FloatingAdminChat from './components/FloatingAdminChat';
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

  // Load conversations when authenticated
  const loadConversations = async () => {
    try {
      const convs = await apiGetConversations();
      setConversations(convs);
      if (convs.length > 0 && !activeConversationId) {
        selectConversation(convs[0].id);
      } else if (convs.length === 0) {
        // Do not create empty row in DB until first message is sent (Rule 13)
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

  // Rule 4: One click must immediately set activeConversation to null, clear
  // messages, filter chip and input, reset scroll to top, and show empty welcome state without waiting for any API call.
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

  // Immediately update sidebar title and active conv on SSE done event (Rule 13 & 14)
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
      </div>
    </ErrorBoundary>
  );
}
