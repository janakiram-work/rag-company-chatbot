import React, { useState, useEffect, useRef } from 'react';
import {
  Plus,
  MessageSquare,
  Trash2,
  Moon,
  Sun,
  Shield,
  LogOut,
  Sparkles,
  ChevronRight,
  Filter,
  X,
  Settings as SettingsIcon,
  HelpCircle,
  MoreVertical,
  ChevronUp,
} from 'lucide-react';

export default function Sidebar({
  conversations,
  activeConversationId,
  onSelectConversation,
  onNewChat,
  onDeleteConversation,
  currentUser,
  currentView,
  onSwitchView,
  isDarkMode,
  onToggleDarkMode,
  onLogout,
  isMobileOpen = false,
  onCloseMobile = null,
  branding = null,
  onOpenSettings = null,
  onOpenContactAdmin = null,
}) {
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const menuRef = useRef(null);

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape' && isMobileOpen && onCloseMobile) {
        onCloseMobile();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isMobileOpen, onCloseMobile]);

  // Close user menu on outside click
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setIsMenuOpen(false);
      }
    };
    if (isMenuOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isMenuOpen]);

  // Group conversations by date
  const groupConversations = () => {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const sevenDaysAgo = new Date(today);
    sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);

    const groups = {
      today: [],
      sevenDays: [],
      older: [],
    };

    conversations.forEach((conv) => {
      const d = new Date(conv.updated_at || conv.created_at);
      if (d >= today) {
        groups.today.push(conv);
      } else if (d >= sevenDaysAgo) {
        groups.sevenDays.push(conv);
      } else {
        groups.older.push(conv);
      }
    });

    return groups;
  };

  const groups = groupConversations();

  const renderGroup = (title, items) => {
    if (items.length === 0) return null;
    return (
      <div className="mb-4">
        <h3 className="px-3 text-[11px] font-semibold uppercase tracking-wider text-gray-400 dark:text-zinc-500 mb-1.5">
          {title}
        </h3>
        <div className="space-y-0.5">
          {items.map((c) => {
            const isActive = c.id === activeConversationId;
            return (
              <div
                key={c.id}
                onClick={() => {
                  onSelectConversation(c.id);
                  if (onCloseMobile) onCloseMobile();
                }}
                className={`group flex items-center justify-between px-3 py-2.5 rounded-xl text-xs font-medium cursor-pointer min-h-[44px] transition ${
                  isActive
                    ? 'bg-emerald-500/15 text-emerald-800 dark:text-emerald-300 font-semibold ring-1 ring-emerald-500/40 shadow-xs'
                    : 'text-gray-700 dark:text-zinc-300 hover:bg-gray-100 dark:hover:bg-zinc-800/60'
                }`}
              >
                <div className="flex items-center gap-2 truncate">
                  <MessageSquare className={`w-3.5 h-3.5 flex-shrink-0 ${isActive ? 'text-emerald-600 dark:text-emerald-400' : 'text-gray-400'}`} />
                  <span className="truncate">{c.title || 'Untitled Chat'}</span>
                </div>
                {c.active_doc_id && c.active_doc_name && (
                  <span title="Document filter active" className="text-emerald-600 dark:text-emerald-400 flex-shrink-0">
                    <Filter className="w-3 h-3" />
                  </span>
                )}
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDeleteConversation(c.id);
                  }}
                  className="opacity-0 group-hover:opacity-100 p-1.5 rounded hover:bg-red-500/20 hover:text-red-600 transition"
                  title="Delete chat"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            );
          })}
        </div>
      </div>
    );
  };

  const companyName = branding?.company_name || 'Enterprise Assistant';
  const tagline = branding?.tagline || 'Enterprise Knowledge';
  const logoUrl = branding?.logo_url;
  const accentColor = branding?.accent_color || '#10b981';

  const userInitials = (
    currentUser?.display_name ||
    currentUser?.username ||
    currentUser?.email ||
    'U'
  )
    .slice(0, 2)
    .toUpperCase();

  return (
    <>
      {/* Mobile Backdrop */}
      {isMobileOpen && (
        <div
          onClick={onCloseMobile}
          className="fixed inset-0 bg-black/50 z-40 md:hidden transition-opacity"
        />
      )}

      <aside
        className={`fixed inset-y-0 left-0 z-50 w-72 md:w-64 flex flex-col h-[100dvh] bg-gray-50 dark:bg-zinc-900 border-r border-gray-200 dark:border-zinc-800 select-none transform transition-transform duration-300 ease-in-out md:static md:translate-x-0 ${
          isMobileOpen ? 'translate-x-0 shadow-2xl' : '-translate-x-full'
        }`}
      >
        {/* Top Header & New Chat */}
        <div className="p-3 border-b border-gray-200/60 dark:border-zinc-800">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2.5 px-1 py-1 truncate">
              {logoUrl ? (
                <img
                  src={logoUrl}
                  alt="Logo"
                  className="w-8 h-8 rounded-lg object-contain bg-white dark:bg-zinc-800 p-0.5 shadow-xs flex-shrink-0"
                />
              ) : (
                <div
                  className="w-8 h-8 rounded-lg flex items-center justify-center text-white shadow-xs flex-shrink-0"
                  style={{ backgroundColor: accentColor }}
                >
                  <Sparkles className="w-4 h-4" />
                </div>
              )}
              <div className="truncate">
                <h2 className="text-sm font-bold text-gray-900 dark:text-white leading-none truncate">
                  {companyName}
                </h2>
                <span className="text-[10px] text-gray-400 dark:text-zinc-500 truncate block mt-0.5">
                  {tagline}
                </span>
              </div>
            </div>
            {onCloseMobile && (
              <button
                type="button"
                onClick={onCloseMobile}
                className="p-2 rounded-lg text-gray-500 hover:bg-gray-200 dark:hover:bg-zinc-800 md:hidden"
                aria-label="Close sidebar"
              >
                <X className="w-5 h-5" />
              </button>
            )}
          </div>

          <button
            type="button"
            onClick={() => {
              onNewChat();
              if (onCloseMobile) onCloseMobile();
            }}
            className="w-full py-2.5 px-3 min-h-[44px] bg-white dark:bg-zinc-800 hover:bg-gray-100 dark:hover:bg-zinc-700/60 text-gray-800 dark:text-zinc-200 border border-gray-200 dark:border-zinc-700 rounded-xl text-xs font-semibold flex items-center justify-between shadow-xs transition"
          >
            <span className="flex items-center gap-2">
              <Plus className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
              New Chat
            </span>
            <span className="text-[10px] text-gray-400">Ctrl+K</span>
          </button>
        </div>

        {/* Conversations List */}
        <div className="flex-1 overflow-y-auto p-2 scrollbar-thin">
          {conversations.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
              <div className="w-10 h-10 rounded-full bg-gray-100 dark:bg-zinc-800 flex items-center justify-center mb-2.5 text-gray-400 dark:text-zinc-500">
                <MessageSquare className="w-5 h-5" />
              </div>
              <p className="text-xs font-semibold text-gray-600 dark:text-zinc-400">No conversations yet</p>
              <p className="text-[11px] text-gray-400 dark:text-zinc-500 mt-1">Click "New Chat" above to start asking questions.</p>
            </div>
          ) : (
            <>
              {renderGroup('Today', groups.today)}
              {renderGroup('Previous 7 Days', groups.sevenDays)}
              {renderGroup('Older', groups.older)}
            </>
          )}
        </div>

        {/* Bottom User Card with Popover Menu (ChatGPT / Claude style) */}
        <div className="p-2 border-t border-gray-200/60 dark:border-zinc-800 relative" ref={menuRef}>
          {/* Popover Menu */}
          {isMenuOpen && (
            <div className="absolute bottom-full left-2 right-2 mb-2 bg-white dark:bg-zinc-900 rounded-2xl shadow-xl border border-gray-200 dark:border-zinc-800 p-1.5 z-50 text-xs animate-in fade-in zoom-in-95 duration-150">
              <div className="px-3 py-2 border-b border-gray-100 dark:border-zinc-800">
                <p className="font-semibold text-gray-900 dark:text-white truncate">
                  {currentUser?.display_name || currentUser?.username || 'User'}
                </p>
                <p className="text-[11px] text-gray-400 truncate">
                  {currentUser?.email}
                </p>
              </div>

              <div className="py-1 space-y-0.5">
                <button
                  type="button"
                  onClick={() => {
                    setIsMenuOpen(false);
                    if (onOpenSettings) onOpenSettings('profile');
                  }}
                  className="w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-gray-700 dark:text-zinc-300 hover:bg-gray-100 dark:hover:bg-zinc-800 font-medium transition"
                >
                  <SettingsIcon className="w-4 h-4 text-gray-400" />
                  Settings
                </button>

                <button
                  type="button"
                  onClick={() => {
                    setIsMenuOpen(false);
                    if (onOpenContactAdmin) onOpenContactAdmin();
                  }}
                  className="w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-gray-700 dark:text-zinc-300 hover:bg-gray-100 dark:hover:bg-zinc-800 font-medium transition"
                >
                  <HelpCircle className="w-4 h-4 text-emerald-500" />
                  Contact Admin / Requests
                </button>

                {currentUser?.role === 'admin' && (
                  <button
                    type="button"
                    onClick={() => {
                      setIsMenuOpen(false);
                      onSwitchView(currentView === 'admin' ? 'chat' : 'admin');
                    }}
                    className="w-full flex items-center justify-between px-3 py-2 rounded-xl text-purple-700 dark:text-purple-300 hover:bg-purple-50 dark:hover:bg-purple-950/40 font-medium transition"
                  >
                    <span className="flex items-center gap-2.5">
                      <Shield className="w-4 h-4 text-purple-500" />
                      {currentView === 'admin' ? 'Back to User Chat' : 'Admin Panel'}
                    </span>
                    <ChevronRight className="w-3.5 h-3.5 opacity-60" />
                  </button>
                )}

                <button
                  type="button"
                  onClick={() => {
                    onToggleDarkMode();
                  }}
                  className="w-full flex items-center justify-between px-3 py-2 rounded-xl text-gray-700 dark:text-zinc-300 hover:bg-gray-100 dark:hover:bg-zinc-800 font-medium transition"
                >
                  <span className="flex items-center gap-2.5">
                    {isDarkMode ? <Sun className="w-4 h-4 text-amber-500" /> : <Moon className="w-4 h-4 text-blue-500" />}
                    Theme
                  </span>
                  <span className="text-[10px] text-gray-400 uppercase font-semibold">
                    {isDarkMode ? 'Dark' : 'Light'}
                  </span>
                </button>
              </div>

              <div className="pt-1 border-t border-gray-100 dark:border-zinc-800">
                <button
                  type="button"
                  onClick={() => {
                    setIsMenuOpen(false);
                    onLogout();
                  }}
                  className="w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/30 font-medium transition"
                >
                  <LogOut className="w-4 h-4" />
                  Log Out
                </button>
              </div>
            </div>
          )}

          {/* User Card Trigger */}
          <button
            type="button"
            onClick={() => setIsMenuOpen(!isMenuOpen)}
            className="w-full flex items-center justify-between p-2 rounded-xl hover:bg-gray-200/60 dark:hover:bg-zinc-800/80 transition text-left focus:outline-none"
          >
            <div className="flex items-center gap-2.5 truncate">
              <div
                className="w-8 h-8 rounded-xl flex items-center justify-center text-white font-bold text-xs shadow-xs flex-shrink-0"
                style={{ backgroundColor: currentUser?.avatar_color || '#10b981' }}
              >
                {userInitials}
              </div>
              <div className="truncate">
                <p className="text-xs font-semibold text-gray-900 dark:text-white truncate leading-tight">
                  {currentUser?.display_name || currentUser?.username || 'User'}
                </p>
                <p className="text-[10px] text-gray-400 truncate">
                  {currentUser?.email}
                </p>
              </div>
            </div>
            <ChevronUp className={`w-4 h-4 text-gray-400 transition-transform ${isMenuOpen ? 'rotate-180' : ''}`} />
          </button>
        </div>
      </aside>
    </>
  );
}
