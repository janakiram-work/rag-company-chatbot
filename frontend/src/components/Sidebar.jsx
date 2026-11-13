import React from 'react';
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
}) {
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
                onClick={() => onSelectConversation(c.id)}
                className={`group flex items-center justify-between px-3 py-2 rounded-xl text-xs font-medium cursor-pointer transition ${
                  isActive
                    ? 'bg-emerald-500/15 text-emerald-800 dark:text-emerald-300 font-semibold ring-1 ring-emerald-500/40 shadow-xs'
                    : 'text-gray-700 dark:text-zinc-300 hover:bg-gray-100 dark:hover:bg-zinc-800/60'
                }`}
              >
                <div className="flex items-center gap-2 truncate">
                  <MessageSquare className={`w-3.5 h-3.5 flex-shrink-0 ${isActive ? 'text-emerald-600 dark:text-emerald-400' : 'text-gray-400'}`} />
                  <span className="truncate">{c.title || 'Untitled Chat'}</span>
                </div>
                {c.active_doc_id && (
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
                  className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-red-500/20 hover:text-red-600 transition"
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

  return (
    <aside className="w-64 flex flex-col h-screen bg-gray-50/80 dark:bg-zinc-900/90 border-r border-gray-200 dark:border-zinc-800 select-none">
      {/* Top Header & New Chat */}
      <div className="p-3 border-b border-gray-200/60 dark:border-zinc-800">
        <div className="flex items-center gap-2.5 px-2 py-1 mb-3">
          <div className="w-8 h-8 rounded-lg bg-emerald-600 flex items-center justify-center text-white shadow">
            <Sparkles className="w-4 h-4" />
          </div>
          <div>
            <h2 className="text-sm font-bold text-gray-900 dark:text-white leading-none">ABC Technologies</h2>
            <span className="text-[10px] text-gray-400 dark:text-zinc-500">Enterprise Knowledge</span>
          </div>
        </div>

        <button
          type="button"
          onClick={onNewChat}
          className="w-full py-2 px-3 bg-white dark:bg-zinc-800 hover:bg-gray-100 dark:hover:bg-zinc-700/60 text-gray-800 dark:text-zinc-200 border border-gray-200 dark:border-zinc-700 rounded-xl text-xs font-semibold flex items-center justify-between shadow-sm transition"
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

      {/* Bottom Controls & User Profile */}
      <div className="p-3 border-t border-gray-200/60 dark:border-zinc-800 space-y-1">
        {currentUser?.role === 'admin' && (
          <button
            type="button"
            onClick={() => onSwitchView(currentView === 'admin' ? 'chat' : 'admin')}
            className={`w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs font-medium transition ${
              currentView === 'admin'
                ? 'bg-purple-600 text-white shadow-sm'
                : 'text-gray-700 dark:text-zinc-300 hover:bg-gray-100 dark:hover:bg-zinc-800'
            }`}
          >
            <span className="flex items-center gap-2">
              <Shield className="w-3.5 h-3.5 text-purple-400" />
              {currentView === 'admin' ? 'Back to User Chat' : 'Admin Dashboard'}
            </span>
            <ChevronRight className="w-3.5 h-3.5 opacity-60" />
          </button>
        )}

        <div className="flex items-center justify-between px-3 py-1.5">
          <span className="text-[11px] text-gray-400 dark:text-zinc-500">Theme</span>
          <button
            type="button"
            onClick={onToggleDarkMode}
            className="p-1.5 rounded-lg text-gray-500 dark:text-zinc-400 hover:bg-gray-200 dark:hover:bg-zinc-800 transition"
            title="Toggle Dark/Light Mode"
          >
            {isDarkMode ? <Sun className="w-3.5 h-3.5" /> : <Moon className="w-3.5 h-3.5" />}
          </button>
        </div>

        {/* User Card */}
        <div className="pt-2 border-t border-gray-200/40 dark:border-zinc-800/80 flex items-center justify-between">
          <div className="truncate pr-2">
            <p className="text-xs font-semibold text-gray-900 dark:text-white truncate">
              {currentUser?.email}
            </p>
            <span
              className={`inline-block px-1.5 py-0.2 rounded text-[10px] font-bold uppercase ${
                currentUser?.role === 'admin'
                  ? 'bg-purple-100 dark:bg-purple-950/60 text-purple-700 dark:text-purple-300'
                  : 'bg-emerald-100 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300'
              }`}
            >
              {currentUser?.role}
            </span>
          </div>
          <button
            type="button"
            onClick={onLogout}
            className="p-1.5 text-gray-400 hover:text-red-600 dark:hover:text-red-400 rounded-lg hover:bg-red-500/10 transition"
            title="Log Out"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </div>
    </aside>
  );
}
