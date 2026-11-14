import React, { useState, useEffect, useRef } from 'react';
import { Bell, CheckCheck, MessageSquare, Info, ShieldAlert, Sparkles, ExternalLink } from 'lucide-react';
import { apiGetNotifications, apiMarkNotificationRead, apiMarkAllNotificationsRead } from '../api';

export default function NotificationBell({ onOpenSupport, onToast }) {
  const [isOpen, setIsOpen] = useState(false);
  const [notifications, setNotifications] = useState([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const dropdownRef = useRef(null);
  const prevCountRef = useRef(0);

  const fetchNotifications = async (quiet = true) => {
    if (document.visibilityState !== 'visible') return;
    if (!quiet) setLoading(true);
    try {
      const data = await apiGetNotifications();
      const items = data.items || [];
      const newUnread = data.unread_count || 0;

      // Toast when new unread notification arrives
      if (newUnread > prevCountRef.current && items.length > 0) {
        const newest = items[0];
        if (onToast && !newest.is_read) {
          onToast(newest.title || 'New notification', 'info');
        }
      }
      prevCountRef.current = newUnread;
      setNotifications(items);
      setUnreadCount(newUnread);
    } catch {
      // Quiet fail on polling
    } finally {
      if (!quiet) setLoading(false);
    }
  };

  useEffect(() => {
    fetchNotifications(false);
    const interval = setInterval(() => {
      fetchNotifications(true);
    }, 15000);

    const handleVisibility = () => {
      if (document.visibilityState === 'visible') {
        fetchNotifications(true);
      }
    };
    const handleNewNotif = () => {
      fetchNotifications(false);
    };

    document.addEventListener('visibilitychange', handleVisibility);
    window.addEventListener('app-new-notification', handleNewNotif);

    return () => {
      clearInterval(interval);
      document.removeEventListener('visibilitychange', handleVisibility);
      window.removeEventListener('app-new-notification', handleNewNotif);
    };
  }, []);

  // Close dropdown on outside click
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setIsOpen(false);
      }
    };
    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isOpen]);

  const handleMarkAll = async () => {
    try {
      await apiMarkAllNotificationsRead();
      setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })));
      setUnreadCount(0);
      prevCountRef.current = 0;
    } catch (err) {
      console.error('Failed to mark all as read:', err);
    }
  };

  const handleItemClick = async (notif) => {
    if (!notif.is_read) {
      try {
        await apiMarkNotificationRead(notif.id);
        setNotifications((prev) =>
          prev.map((n) => (n.id === notif.id ? { ...n, is_read: true } : n))
        );
        setUnreadCount((prev) => Math.max(0, prev - 1));
        prevCountRef.current = Math.max(0, prevCountRef.current - 1);
      } catch (err) {
        console.error('Failed to mark read:', err);
      }
    }
    setIsOpen(false);
    if (notif.link && notif.link.includes('support') && onOpenSupport) {
      onOpenSupport(notif.link);
    }
  };

  const getIcon = (type) => {
    switch (type) {
      case 'support_reply':
      case 'support_status':
      case 'new_support':
        return <MessageSquare className="w-4 h-4 text-emerald-500" />;
      case 'password_reset_pending':
        return <ShieldAlert className="w-4 h-4 text-amber-500" />;
      default:
        return <Info className="w-4 h-4 text-blue-500" />;
    }
  };

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        type="button"
        onClick={() => {
          setIsOpen(!isOpen);
          if (!isOpen) fetchNotifications(true);
        }}
        className="relative p-2 rounded-xl text-gray-500 dark:text-zinc-400 hover:bg-gray-100 dark:hover:bg-zinc-800 transition focus:outline-none"
        title="Notifications"
        aria-label="Notifications"
      >
        <Bell className="w-5 h-5" />
        {unreadCount > 0 && (
          <span className="absolute top-1 right-1 flex h-4 min-w-[16px] px-1 items-center justify-center rounded-full bg-red-500 text-[10px] font-bold text-white shadow-xs">
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {isOpen && (
        <div className="absolute right-0 mt-2 w-80 sm:w-96 rounded-2xl bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 shadow-xl z-50 overflow-hidden flex flex-col max-h-[460px]">
          {/* Header */}
          <div className="px-4 py-3 border-b border-gray-100 dark:border-zinc-800 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-sm text-gray-900 dark:text-white">Notifications</span>
              {unreadCount > 0 && (
                <span className="px-1.5 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-100 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300">
                  {unreadCount} unread
                </span>
              )}
            </div>
            {unreadCount > 0 && (
              <button
                type="button"
                onClick={handleMarkAll}
                className="text-xs text-emerald-600 dark:text-emerald-400 hover:underline flex items-center gap-1 font-medium"
              >
                <CheckCheck className="w-3.5 h-3.5" />
                Mark all read
              </button>
            )}
          </div>

          {/* List */}
          <div className="overflow-y-auto flex-1 divide-y divide-gray-100 dark:divide-zinc-800/60">
            {notifications.length === 0 ? (
              <div className="py-12 text-center text-gray-400 dark:text-zinc-500 text-xs">
                No notifications right now
              </div>
            ) : (
              notifications.map((n) => (
                <div
                  key={n.id}
                  onClick={() => handleItemClick(n)}
                  className={`p-3.5 flex gap-3 items-start cursor-pointer transition hover:bg-gray-50 dark:hover:bg-zinc-800/50 ${
                    !n.is_read ? 'bg-emerald-500/5 dark:bg-emerald-500/10' : ''
                  }`}
                >
                  <div className="mt-0.5 p-1.5 rounded-lg bg-gray-100 dark:bg-zinc-800 flex-shrink-0">
                    {getIcon(n.type)}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-2">
                      <p className={`text-xs font-semibold truncate ${!n.is_read ? 'text-gray-900 dark:text-white' : 'text-gray-600 dark:text-zinc-300'}`}>
                        {n.title}
                      </p>
                      {!n.is_read && (
                        <span className="w-2 h-2 rounded-full bg-emerald-500 flex-shrink-0" />
                      )}
                    </div>
                    <p className="text-[11px] text-gray-500 dark:text-zinc-400 mt-0.5 line-clamp-2">
                      {n.body}
                    </p>
                    <span className="text-[10px] text-gray-400 dark:text-zinc-500 mt-1 block">
                      {n.created_at ? new Date(n.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}
                    </span>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
