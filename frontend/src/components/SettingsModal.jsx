import React, { useState, useEffect, useRef } from 'react';
import {
  X,
  Settings as SettingsIcon,
  User,
  Shield,
  Database,
  Building,
  Users,
  MessageSquare,
  KeyRound,
  FileClock,
  Sun,
  Moon,
  Laptop,
  Check,
  AlertCircle,
  Download,
  Trash2,
  Upload,
  RefreshCw,
  Search,
  Eye,
  EyeOff,
  Copy,
  ExternalLink,
  ChevronLeft,
  ChevronRight,
  Send,
  Sparkles,
} from 'lucide-react';
import {
  apiGetProfile,
  apiUpdateProfile,
  apiChangePassword,
  apiGetPreferences,
  apiUpdatePreferences,
  apiExportConversations,
  apiDeleteAllConversations,
  apiUpdateBranding,
  apiUploadLogo,
  apiGetAdminUsersPaginated,
  apiCreateAdminUser,
  apiUpdateAdminUser,
  apiForcePasswordReset,
  apiDeactivateUser,
  apiGetAdminSupportRequests,
  apiGetSupportRequest,
  apiReplySupportRequest,
  apiUpdateSupportStatus,
  apiGetPasswordResets,
  apiApprovePasswordReset,
  apiRejectPasswordReset,
  apiGetAuditLog,
  formatError,
  setStoredUser,
} from '../api';

const AVATAR_COLORS = [
  '#10b981', // emerald
  '#3b82f6', // blue
  '#8b5cf6', // purple
  '#ec4899', // pink
  '#f59e0b', // amber
  '#06b6d4', // cyan
  '#6366f1', // indigo
];

export default function SettingsModal({
  isOpen,
  onClose,
  currentUser,
  onUserUpdated,
  branding,
  onBrandingUpdated,
  isDarkMode,
  onToggleDarkMode,
  onAllConversationsDeleted,
  initialTab = 'profile',
  onToast = null,
}) {
  const [activeTab, setActiveTab] = useState(initialTab);

  // Profile Form
  const [displayName, setDisplayName] = useState(currentUser?.display_name || '');
  const [username, setUsername] = useState(currentUser?.username || '');
  const [avatarColor, setAvatarColor] = useState(currentUser?.avatar_color || '#10b981');
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileMsg, setProfileMsg] = useState({ type: '', text: '' });

  // Security Form
  const [currentPw, setCurrentPw] = useState('');
  const [newPw, setNewPw] = useState('');
  const [confirmPw, setConfirmPw] = useState('');
  const [showCurrentPw, setShowCurrentPw] = useState(false);
  const [showNewPw, setShowNewPw] = useState(false);
  const [pwSaving, setPwSaving] = useState(false);
  const [pwMsg, setPwMsg] = useState({ type: '', text: '' });

  // Preferences Form
  const [themePref, setThemePref] = useState(() => {
    return localStorage.getItem('app_theme') || 'system';
  });

  // Admin: Company Branding
  const [companyName, setCompanyName] = useState(branding?.company_name || '');
  const [tagline, setTagline] = useState(branding?.tagline || '');
  const [accentColor, setAccentColor] = useState(branding?.accent_color || '#10b981');
  const [logoFile, setLogoFile] = useState(null);
  const [logoPreview, setLogoPreview] = useState(branding?.logo_url || '');
  const [brandingSaving, setBrandingSaving] = useState(false);
  const [brandingMsg, setBrandingMsg] = useState({ type: '', text: '' });
  const logoInputRef = useRef(null);

  // Admin: Users Management
  const [userList, setUserList] = useState([]);
  const [userTotal, setUserTotal] = useState(0);
  const [userSearch, setUserSearch] = useState('');
  const [userPage, setUserPage] = useState(0);
  const [userLoading, setUserLoading] = useState(false);
  const [showCreateUserModal, setShowCreateUserModal] = useState(false);
  const [newUserData, setNewUserData] = useState({
    username: '',
    email: '',
    password: '',
    role: 'user',
    display_name: '',
  });

  // Admin: Support Requests
  const [adminRequests, setAdminRequests] = useState([]);
  const [reqStatusFilter, setReqStatusFilter] = useState('');
  const [reqLoading, setReqLoading] = useState(false);
  const [selectedReqThread, setSelectedReqThread] = useState(null);
  const [adminReplyText, setAdminReplyText] = useState('');
  const [replyingToUser, setReplyingToUser] = useState(false);

  // Admin: Password Resets
  const [resetsList, setResetsList] = useState([]);
  const [resetsLoading, setResetsLoading] = useState(false);
  const [approvedLinkData, setApprovedLinkData] = useState(null);

  // Admin: Audit Log
  const [auditLogs, setAuditLogs] = useState([]);
  const [auditLoading, setAuditLoading] = useState(false);

  useEffect(() => {
    if (currentUser) {
      setDisplayName(currentUser.display_name || '');
      setUsername(currentUser.username || '');
      setAvatarColor(currentUser.avatar_color || '#10b981');
    }
  }, [currentUser]);

  useEffect(() => {
    if (branding) {
      setCompanyName(branding.company_name || '');
      setTagline(branding.tagline || '');
      setAccentColor(branding.accent_color || '#10b981');
      setLogoPreview(branding.logo_url || '');
    }
  }, [branding]);

  useEffect(() => {
    if (initialTab) {
      setActiveTab(initialTab);
    }
  }, [initialTab, isOpen]);

  // Tab Loaders
  useEffect(() => {
    if (!isOpen) return;
    if (activeTab === 'users' && currentUser?.role === 'admin') {
      loadAdminUsers();
    } else if (activeTab === 'requests' && currentUser?.role === 'admin') {
      loadAdminRequests();
    } else if (activeTab === 'resets' && currentUser?.role === 'admin') {
      loadPasswordResets();
    } else if (activeTab === 'audit' && currentUser?.role === 'admin') {
      loadAuditLogs();
    }
  }, [activeTab, isOpen, userPage, userSearch, reqStatusFilter]);

  const loadAdminUsers = async () => {
    setUserLoading(true);
    try {
      const data = await apiGetAdminUsersPaginated(userSearch, userPage * 20, 20);
      setUserList(data.items || []);
      setUserTotal(data.total || 0);
    } catch (err) {
      console.error('Failed to load users:', err);
    } finally {
      setUserLoading(false);
    }
  };

  const loadAdminRequests = async () => {
    setReqLoading(true);
    try {
      const data = await apiGetAdminSupportRequests(reqStatusFilter || null);
      setAdminRequests(data || []);
    } catch (err) {
      console.error('Failed to load requests:', err);
    } finally {
      setReqLoading(false);
    }
  };

  const loadPasswordResets = async () => {
    setResetsLoading(true);
    try {
      const data = await apiGetPasswordResets('pending');
      setResetsList(data || []);
    } catch (err) {
      console.error('Failed to load resets:', err);
    } finally {
      setResetsLoading(false);
    }
  };

  const loadAuditLogs = async () => {
    setAuditLoading(true);
    try {
      const data = await apiGetAuditLog(100);
      setAuditLogs(data || []);
    } catch (err) {
      console.error('Failed to load audit logs:', err);
    } finally {
      setAuditLoading(false);
    }
  };

  if (!isOpen) return null;

  // Handlers
  const handleSaveProfile = async (e) => {
    e.preventDefault();
    setProfileSaving(true);
    setProfileMsg({ type: '', text: '' });
    try {
      const updated = await apiUpdateProfile({
        display_name: displayName.trim(),
        username: username.trim(),
        avatar_color: avatarColor,
      });
      setStoredUser(updated);
      if (onUserUpdated) onUserUpdated(updated);
      setProfileMsg({ type: 'success', text: 'Profile updated successfully' });
      if (onToast) onToast('Profile updated', 'success');
    } catch (err) {
      setProfileMsg({ type: 'error', text: formatError(err) });
    } finally {
      setProfileSaving(false);
    }
  };

  const handleChangePassword = async (e) => {
    e.preventDefault();
    if (newPw !== confirmPw) {
      setPwMsg({ type: 'error', text: 'New passwords do not match' });
      return;
    }
    if (newPw.length < 8) {
      setPwMsg({ type: 'error', text: 'Password must be at least 8 characters' });
      return;
    }
    setPwSaving(true);
    setPwMsg({ type: '', text: '' });
    try {
      await apiChangePassword(currentPw, newPw);
      setPwMsg({ type: 'success', text: 'Password changed successfully' });
      setCurrentPw('');
      setNewPw('');
      setConfirmPw('');
      if (onToast) onToast('Password changed', 'success');
    } catch (err) {
      setPwMsg({ type: 'error', text: formatError(err) });
    } finally {
      setPwSaving(false);
    }
  };

  const handleThemeChange = async (newTheme) => {
    setThemePref(newTheme);
    if (newTheme === 'dark') {
      document.documentElement.classList.add('dark');
      localStorage.setItem('app_theme', 'dark');
      localStorage.setItem('acme_theme', 'dark');
    } else if (newTheme === 'light') {
      document.documentElement.classList.remove('dark');
      localStorage.setItem('app_theme', 'light');
      localStorage.setItem('acme_theme', 'light');
    } else {
      // system
      const isSysDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
      if (isSysDark) document.documentElement.classList.add('dark');
      else document.documentElement.classList.remove('dark');
      localStorage.setItem('app_theme', 'system');
      localStorage.setItem('acme_theme', 'system');
    }
    try {
      await apiUpdatePreferences(newTheme);
    } catch {}
  };

  const handleExportChats = async () => {
    try {
      const data = await apiExportConversations();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `my_chat_history_${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      if (onToast) onToast('Chat history exported', 'success');
    } catch (err) {
      alert(`Export failed: ${formatError(err)}`);
    }
  };

  const handleDeleteAllChats = async () => {
    if (!window.confirm('Are you sure you want to delete ALL your conversations? This cannot be undone.')) {
      return;
    }
    try {
      await apiDeleteAllConversations();
      if (onAllConversationsDeleted) onAllConversationsDeleted();
      if (onToast) onToast('All conversations deleted', 'info');
    } catch (err) {
      alert(`Delete failed: ${formatError(err)}`);
    }
  };

  const handleLogoFileChange = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 1024 * 1024) {
      alert('Logo file must be under 1 MB');
      return;
    }
    setLogoFile(file);
    const previewUrl = URL.createObjectURL(file);
    setLogoPreview(previewUrl);
  };

  const handleSaveBranding = async (e) => {
    e.preventDefault();
    setBrandingSaving(true);
    setBrandingMsg({ type: '', text: '' });
    try {
      let updatedLogoUrl = branding?.logo_url;
      if (logoFile) {
        const logoRes = await apiUploadLogo(logoFile);
        updatedLogoUrl = logoRes.logo_url;
      }
      const brandingRes = await apiUpdateBranding({
        company_name: companyName.trim(),
        tagline: tagline.trim(),
        accent_color: accentColor,
      });

      const fullBranding = {
        ...brandingRes,
        logo_url: updatedLogoUrl,
      };
      if (onBrandingUpdated) onBrandingUpdated(fullBranding);
      setBrandingMsg({ type: 'success', text: 'Branding updated successfully' });
      if (onToast) onToast('Company branding updated', 'success');
    } catch (err) {
      setBrandingMsg({ type: 'error', text: formatError(err) });
    } finally {
      setBrandingSaving(false);
    }
  };

  const handleCreateUser = async (e) => {
    e.preventDefault();
    try {
      await apiCreateAdminUser(newUserData);
      setShowCreateUserModal(false);
      setNewUserData({ username: '', email: '', password: '', role: 'user', display_name: '' });
      await loadAdminUsers();
      if (onToast) onToast('User created successfully', 'success');
    } catch (err) {
      alert(`Create user failed: ${formatError(err)}`);
    }
  };

  const handleToggleUserRole = async (u) => {
    const newRole = u.role === 'admin' ? 'user' : 'admin';
    if (!window.confirm(`Change role of "${u.email}" to "${newRole}"?`)) return;
    try {
      await apiUpdateAdminUser(u.id, { role: newRole });
      await loadAdminUsers();
      if (onToast) onToast(`User role updated to ${newRole}`, 'success');
    } catch (err) {
      alert(`Update failed: ${formatError(err)}`);
    }
  };

  const handleToggleUserActive = async (u) => {
    const newActive = !u.is_active;
    const action = newActive ? 'reactivate' : 'deactivate';
    if (!window.confirm(`Are you sure you want to ${action} account "${u.email}"?`)) return;
    try {
      if (!newActive) {
        await apiDeactivateUser(u.id);
      } else {
        await apiUpdateAdminUser(u.id, { is_active: true });
      }
      await loadAdminUsers();
      if (onToast) onToast(`User ${action}d`, 'info');
    } catch (err) {
      alert(`Update failed: ${formatError(err)}`);
    }
  };

  const handleForceReset = async (u) => {
    if (!window.confirm(`Force password reset for "${u.email}" on next login?`)) return;
    try {
      await apiForcePasswordReset(u.id);
      await loadAdminUsers();
      if (onToast) onToast('Password reset flagged', 'info');
    } catch (err) {
      alert(`Action failed: ${formatError(err)}`);
    }
  };

  const handleApproveReset = async (resetReq) => {
    try {
      const res = await apiApprovePasswordReset(resetReq.id);
      setApprovedLinkData(res);
      await loadPasswordResets();
    } catch (err) {
      alert(`Approve failed: ${formatError(err)}`);
    }
  };

  const handleRejectReset = async (resetReq) => {
    if (!window.confirm(`Reject password reset for "${resetReq.user_email}"?`)) return;
    try {
      await apiRejectPasswordReset(resetReq.id);
      await loadPasswordResets();
      if (onToast) onToast('Reset request rejected', 'info');
    } catch (err) {
      alert(`Reject failed: ${formatError(err)}`);
    }
  };

  const handleAdminReplySubmit = async (e) => {
    e.preventDefault();
    if (!adminReplyText.trim() || !selectedReqThread) return;
    setReplyingToUser(true);
    try {
      const updated = await apiReplySupportRequest(selectedReqThread.id, adminReplyText.trim());
      setSelectedReqThread(updated);
      setAdminReplyText('');
      await loadAdminRequests();
      if (onToast) onToast('Reply sent to user', 'success');
    } catch (err) {
      alert(`Reply failed: ${formatError(err)}`);
    } finally {
      setReplyingToUser(false);
    }
  };

  const handleAdminStatusChange = async (newStatus) => {
    if (!selectedReqThread) return;
    try {
      const updated = await apiUpdateSupportStatus(selectedReqThread.id, newStatus);
      setSelectedReqThread(updated);
      await loadAdminRequests();
      if (onToast) onToast(`Status changed to ${newStatus}`, 'info');
    } catch (err) {
      alert(`Update failed: ${formatError(err)}`);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-black/60 backdrop-blur-xs">
      <div className="w-full max-w-4xl bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl border border-gray-200 dark:border-zinc-800 flex flex-col md:flex-row h-[85vh] max-h-[800px] overflow-hidden animate-in fade-in zoom-in-95 duration-200">
        {/* Left Tabs Bar */}
        <div className="w-full md:w-56 bg-gray-50/80 dark:bg-zinc-950/60 border-b md:border-b-0 md:border-r border-gray-200 dark:border-zinc-800 p-3 flex md:flex-col justify-between overflow-x-auto md:overflow-y-auto">
          <div className="space-y-1 w-full flex md:flex-col gap-1 md:gap-0">
            <div className="hidden md:block px-3 py-2 text-[11px] font-bold uppercase tracking-wider text-gray-400 dark:text-zinc-500">
              User Settings
            </div>
            {[
              { id: 'profile', label: 'Profile', icon: User },
              { id: 'general', label: 'General', icon: SettingsIcon },
              { id: 'security', label: 'Security', icon: Shield },
              { id: 'data', label: 'Data Controls', icon: Database },
            ].map((t) => {
              const Icon = t.icon;
              return (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => setActiveTab(t.id)}
                  className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-medium transition whitespace-nowrap ${
                    activeTab === t.id
                      ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 font-semibold'
                      : 'text-gray-600 dark:text-zinc-400 hover:bg-gray-100 dark:hover:bg-zinc-800/60'
                  }`}
                >
                  <Icon className="w-4 h-4 flex-shrink-0" />
                  <span>{t.label}</span>
                </button>
              );
            })}

            {currentUser?.role === 'admin' && (
              <>
                <div className="hidden md:block px-3 pt-4 pb-1 text-[11px] font-bold uppercase tracking-wider text-purple-600 dark:text-purple-400">
                  Admin Panel
                </div>
                {[
                  { id: 'branding', label: 'Company Branding', icon: Building },
                  { id: 'users', label: 'Users', icon: Users },
                  { id: 'requests', label: 'Requests Inbox', icon: MessageSquare },
                  { id: 'resets', label: 'Password Resets', icon: KeyRound },
                  { id: 'audit', label: 'Audit Log', icon: FileClock },
                ].map((t) => {
                  const Icon = t.icon;
                  return (
                    <button
                      key={t.id}
                      type="button"
                      onClick={() => setActiveTab(t.id)}
                      className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-medium transition whitespace-nowrap ${
                        activeTab === t.id
                          ? 'bg-purple-500/15 text-purple-700 dark:text-purple-300 font-semibold'
                          : 'text-gray-600 dark:text-zinc-400 hover:bg-gray-100 dark:hover:bg-zinc-800/60'
                      }`}
                    >
                      <Icon className="w-4 h-4 flex-shrink-0" />
                      <span>{t.label}</span>
                    </button>
                  );
                })}
              </>
            )}
          </div>

          <div className="hidden md:flex items-center gap-2 px-3 py-2 text-[11px] text-gray-400 dark:text-zinc-500">
            <span>{branding?.company_name || 'Enterprise'} v1.0.0</span>
          </div>
        </div>

        {/* Right Content Area */}
        <div className="flex-1 flex flex-col h-full overflow-hidden bg-white dark:bg-zinc-900">
          {/* Header */}
          <div className="px-6 py-4 border-b border-gray-100 dark:border-zinc-800 flex items-center justify-between">
            <h2 className="text-base font-bold text-gray-900 dark:text-white capitalize">
              {activeTab === 'branding' ? 'Company Branding & Appearance' : activeTab}
            </h2>
            <button
              type="button"
              onClick={onClose}
              className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-zinc-300 hover:bg-gray-100 dark:hover:bg-zinc-800 transition"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Tab Body */}
          <div className="flex-1 overflow-y-auto p-6 scrollbar-thin">
            {/* TAB: PROFILE */}
            {activeTab === 'profile' && (
              <form onSubmit={handleSaveProfile} className="max-w-md space-y-5">
                {profileMsg.text && (
                  <div
                    className={`p-3 rounded-xl text-xs flex items-center gap-2 ${
                      profileMsg.type === 'success'
                        ? 'bg-emerald-50 dark:bg-emerald-950/50 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-900'
                        : 'bg-red-50 dark:bg-red-950/50 text-red-700 dark:text-red-300 border border-red-200 dark:border-red-900'
                    }`}
                  >
                    <AlertCircle className="w-4 h-4 flex-shrink-0" />
                    <span>{profileMsg.text}</span>
                  </div>
                )}

                <div>
                  <label className="block text-xs font-semibold text-gray-700 dark:text-zinc-300 uppercase mb-2">
                    Avatar Color
                  </label>
                  <div className="flex items-center gap-3">
                    <div
                      className="w-12 h-12 rounded-2xl flex items-center justify-center text-white font-bold text-base shadow-sm"
                      style={{ backgroundColor: avatarColor }}
                    >
                      {(displayName || username || currentUser?.email || 'U').slice(0, 2).toUpperCase()}
                    </div>
                    <div className="flex items-center gap-2">
                      {AVATAR_COLORS.map((c) => (
                        <button
                          key={c}
                          type="button"
                          onClick={() => setAvatarColor(c)}
                          className="w-7 h-7 rounded-full transition flex items-center justify-center ring-offset-2 dark:ring-offset-zinc-900 focus:outline-none"
                          style={{
                            backgroundColor: c,
                            outline: avatarColor === c ? '2px solid #10b981' : 'none',
                          }}
                        >
                          {avatarColor === c && <Check className="w-3.5 h-3.5 text-white" />}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-gray-700 dark:text-zinc-300 uppercase mb-1">
                    Display Name
                  </label>
                  <input
                    type="text"
                    required
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    placeholder="Your name"
                    className="w-full px-3.5 py-2.5 text-xs bg-gray-50 dark:bg-zinc-800 border border-gray-200 dark:border-zinc-700 rounded-xl focus:outline-none focus:ring-2 focus:ring-emerald-500 text-gray-900 dark:text-white"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-gray-700 dark:text-zinc-300 uppercase mb-1">
                    Username
                  </label>
                  <input
                    type="text"
                    required
                    pattern="^[a-zA-Z0-9_.]+$"
                    minLength={3}
                    maxLength={30}
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    placeholder="username"
                    className="w-full px-3.5 py-2.5 text-xs bg-gray-50 dark:bg-zinc-800 border border-gray-200 dark:border-zinc-700 rounded-xl focus:outline-none focus:ring-2 focus:ring-emerald-500 text-gray-900 dark:text-white"
                  />
                  <span className="text-[10px] text-gray-400 mt-1 block">
                    3-30 characters: letters, numbers, underscore, dot.
                  </span>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-gray-700 dark:text-zinc-300 uppercase mb-1">
                    Email Address
                  </label>
                  <input
                    type="email"
                    readOnly
                    disabled
                    value={currentUser?.email || ''}
                    className="w-full px-3.5 py-2.5 text-xs bg-gray-100 dark:bg-zinc-800/40 border border-gray-200 dark:border-zinc-700/60 rounded-xl text-gray-500 cursor-not-allowed"
                  />
                </div>

                <div className="pt-2">
                  <button
                    type="submit"
                    disabled={profileSaving}
                    className="px-5 py-2.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-xs font-semibold flex items-center gap-2 shadow-sm transition disabled:opacity-50"
                  >
                    {profileSaving && <span className="animate-spin rounded-full h-3 w-3 border-2 border-white border-t-transparent" />}
                    Save Changes
                  </button>
                </div>
              </form>
            )}

            {/* TAB: GENERAL */}
            {activeTab === 'general' && (
              <div className="max-w-md space-y-6">
                <div>
                  <label className="block text-xs font-semibold text-gray-700 dark:text-zinc-300 uppercase mb-2">
                    Theme Appearance
                  </label>
                  <div className="grid grid-cols-3 gap-3">
                    {[
                      { id: 'light', label: 'Light', icon: Sun },
                      { id: 'dark', label: 'Dark', icon: Moon },
                      { id: 'system', label: 'System', icon: Laptop },
                    ].map((t) => {
                      const Icon = t.icon;
                      const isSel = themePref === t.id;
                      return (
                        <button
                          key={t.id}
                          type="button"
                          onClick={() => handleThemeChange(t.id)}
                          className={`p-3.5 rounded-xl border flex flex-col items-center gap-2 transition ${
                            isSel
                              ? 'border-emerald-500 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300'
                              : 'border-gray-200 dark:border-zinc-700 hover:bg-gray-50 dark:hover:bg-zinc-800/60 text-gray-600 dark:text-zinc-400'
                          }`}
                        >
                          <Icon className="w-5 h-5" />
                          <span className="text-xs font-medium">{t.label}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              </div>
            )}

            {/* TAB: SECURITY */}
            {activeTab === 'security' && (
              <form onSubmit={handleChangePassword} className="max-w-md space-y-4">
                {pwMsg.text && (
                  <div
                    className={`p-3 rounded-xl text-xs flex items-center gap-2 ${
                      pwMsg.type === 'success'
                        ? 'bg-emerald-50 dark:bg-emerald-950/50 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-900'
                        : 'bg-red-50 dark:bg-red-950/50 text-red-700 dark:text-red-300 border border-red-200 dark:border-red-900'
                    }`}
                  >
                    <AlertCircle className="w-4 h-4 flex-shrink-0" />
                    <span>{pwMsg.text}</span>
                  </div>
                )}

                <div>
                  <label className="block text-xs font-semibold text-gray-700 dark:text-zinc-300 uppercase mb-1">
                    Current Password
                  </label>
                  <div className="relative">
                    <input
                      type={showCurrentPw ? 'text' : 'password'}
                      required
                      value={currentPw}
                      onChange={(e) => setCurrentPw(e.target.value)}
                      placeholder="••••••••"
                      className="w-full pl-3.5 pr-10 py-2.5 text-xs bg-gray-50 dark:bg-zinc-800 border border-gray-200 dark:border-zinc-700 rounded-xl focus:outline-none focus:ring-2 focus:ring-emerald-500 text-gray-900 dark:text-white"
                    />
                    <button
                      type="button"
                      onClick={() => setShowCurrentPw(!showCurrentPw)}
                      className="absolute right-3 top-2.5 text-gray-400 hover:text-gray-600 dark:hover:text-zinc-300"
                    >
                      {showCurrentPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-gray-700 dark:text-zinc-300 uppercase mb-1">
                    New Password
                  </label>
                  <div className="relative">
                    <input
                      type={showNewPw ? 'text' : 'password'}
                      required
                      minLength={8}
                      value={newPw}
                      onChange={(e) => setNewPw(e.target.value)}
                      placeholder="Minimum 8 characters"
                      className="w-full pl-3.5 pr-10 py-2.5 text-xs bg-gray-50 dark:bg-zinc-800 border border-gray-200 dark:border-zinc-700 rounded-xl focus:outline-none focus:ring-2 focus:ring-emerald-500 text-gray-900 dark:text-white"
                    />
                    <button
                      type="button"
                      onClick={() => setShowNewPw(!showNewPw)}
                      className="absolute right-3 top-2.5 text-gray-400 hover:text-gray-600 dark:hover:text-zinc-300"
                    >
                      {showNewPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-gray-700 dark:text-zinc-300 uppercase mb-1">
                    Confirm New Password
                  </label>
                  <input
                    type="password"
                    required
                    value={confirmPw}
                    onChange={(e) => setConfirmPw(e.target.value)}
                    placeholder="Repeat new password"
                    className="w-full px-3.5 py-2.5 text-xs bg-gray-50 dark:bg-zinc-800 border border-gray-200 dark:border-zinc-700 rounded-xl focus:outline-none focus:ring-2 focus:ring-emerald-500 text-gray-900 dark:text-white"
                  />
                </div>

                <div className="pt-2">
                  <button
                    type="submit"
                    disabled={pwSaving}
                    className="px-5 py-2.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-xs font-semibold flex items-center gap-2 shadow-sm transition disabled:opacity-50"
                  >
                    {pwSaving && <span className="animate-spin rounded-full h-3 w-3 border-2 border-white border-t-transparent" />}
                    Update Password
                  </button>
                </div>
              </form>
            )}

            {/* TAB: DATA */}
            {activeTab === 'data' && (
              <div className="max-w-md space-y-6">
                <div className="p-4 rounded-xl border border-gray-200 dark:border-zinc-800 bg-gray-50/50 dark:bg-zinc-800/40 space-y-3">
                  <h4 className="text-xs font-bold text-gray-900 dark:text-white">Export Chat History</h4>
                  <p className="text-xs text-gray-500 dark:text-zinc-400">
                    Download a full JSON copy of all your conversations and messages.
                  </p>
                  <button
                    type="button"
                    onClick={handleExportChats}
                    className="px-4 py-2 bg-white dark:bg-zinc-800 border border-gray-300 dark:border-zinc-700 hover:bg-gray-50 dark:hover:bg-zinc-700 text-gray-800 dark:text-zinc-200 rounded-xl text-xs font-semibold flex items-center gap-2 shadow-xs transition"
                  >
                    <Download className="w-3.5 h-3.5 text-emerald-500" />
                    Export All Chats (JSON)
                  </button>
                </div>

                <div className="p-4 rounded-xl border border-red-200 dark:border-red-950/60 bg-red-50/40 dark:bg-red-950/20 space-y-3">
                  <h4 className="text-xs font-bold text-red-700 dark:text-red-400">Delete All Conversations</h4>
                  <p className="text-xs text-red-600/80 dark:text-red-400/80">
                    Permanently delete all your conversation history. Documents uploaded will remain intact.
                  </p>
                  <button
                    type="button"
                    onClick={handleDeleteAllChats}
                    className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-xl text-xs font-semibold flex items-center gap-2 shadow-xs transition"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                    Delete All My Chats
                  </button>
                </div>
              </div>
            )}

            {/* TAB: BRANDING (ADMIN) */}
            {activeTab === 'branding' && currentUser?.role === 'admin' && (
              <form onSubmit={handleSaveBranding} className="max-w-xl space-y-5">
                {brandingMsg.text && (
                  <div
                    className={`p-3 rounded-xl text-xs flex items-center gap-2 ${
                      brandingMsg.type === 'success'
                        ? 'bg-emerald-50 dark:bg-emerald-950/50 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-900'
                        : 'bg-red-50 dark:bg-red-950/50 text-red-700 dark:text-red-300 border border-red-200 dark:border-red-900'
                    }`}
                  >
                    <AlertCircle className="w-4 h-4 flex-shrink-0" />
                    <span>{brandingMsg.text}</span>
                  </div>
                )}

                <div>
                  <label className="block text-xs font-semibold text-gray-700 dark:text-zinc-300 uppercase mb-1">
                    Company Name
                  </label>
                  <input
                    type="text"
                    required
                    value={companyName}
                    onChange={(e) => setCompanyName(e.target.value)}
                    placeholder="e.g. Acme Corporation"
                    className="w-full px-3.5 py-2.5 text-xs bg-gray-50 dark:bg-zinc-800 border border-gray-200 dark:border-zinc-700 rounded-xl focus:outline-none focus:ring-2 focus:ring-emerald-500 text-gray-900 dark:text-white"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-gray-700 dark:text-zinc-300 uppercase mb-1">
                    Tagline / Subtitle
                  </label>
                  <input
                    type="text"
                    value={tagline}
                    onChange={(e) => setTagline(e.target.value)}
                    placeholder="e.g. Enterprise RAG Intelligence & Multimodal Assistant"
                    className="w-full px-3.5 py-2.5 text-xs bg-gray-50 dark:bg-zinc-800 border border-gray-200 dark:border-zinc-700 rounded-xl focus:outline-none focus:ring-2 focus:ring-emerald-500 text-gray-900 dark:text-white"
                  />
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs font-semibold text-gray-700 dark:text-zinc-300 uppercase mb-1">
                      Accent Color
                    </label>
                    <div className="flex items-center gap-2">
                      <input
                        type="color"
                        value={accentColor}
                        onChange={(e) => setAccentColor(e.target.value)}
                        className="w-9 h-9 p-0.5 rounded-xl border border-gray-200 dark:border-zinc-700 cursor-pointer bg-transparent"
                      />
                      <input
                        type="text"
                        value={accentColor}
                        onChange={(e) => setAccentColor(e.target.value)}
                        className="flex-1 px-3 py-2 text-xs bg-gray-50 dark:bg-zinc-800 border border-gray-200 dark:border-zinc-700 rounded-xl focus:outline-none text-gray-900 dark:text-white"
                      />
                    </div>
                  </div>

                  <div>
                    <label className="block text-xs font-semibold text-gray-700 dark:text-zinc-300 uppercase mb-1">
                      Company Logo (max 1 MB)
                    </label>
                    <input
                      type="file"
                      ref={logoInputRef}
                      accept="image/png,image/jpeg,image/svg+xml"
                      onChange={handleLogoFileChange}
                      className="hidden"
                    />
                    <button
                      type="button"
                      onClick={() => logoInputRef.current?.click()}
                      className="w-full py-2 px-3 border border-dashed border-gray-300 dark:border-zinc-700 hover:border-emerald-500 rounded-xl text-xs text-gray-600 dark:text-zinc-300 flex items-center justify-center gap-1.5 transition"
                    >
                      <Upload className="w-3.5 h-3.5" />
                      {logoFile ? logoFile.name : 'Choose Logo Image'}
                    </button>
                  </div>
                </div>

                {/* Live Preview Card */}
                <div className="p-4 rounded-xl border border-gray-200 dark:border-zinc-800 bg-gray-50/70 dark:bg-zinc-800/50 space-y-2">
                  <span className="text-[10px] font-bold text-gray-400 dark:text-zinc-500 uppercase tracking-wider block">
                    Live Preview (Sidebar / Header Header)
                  </span>
                  <div className="flex items-center gap-3 p-3 bg-white dark:bg-zinc-900 rounded-xl border border-gray-200/60 dark:border-zinc-700/60 shadow-xs">
                    {logoPreview ? (
                      <img src={logoPreview} alt="Company Logo" className="w-8 h-8 rounded-lg object-contain bg-gray-50 dark:bg-zinc-800 p-0.5" />
                    ) : (
                      <div className="w-8 h-8 rounded-lg flex items-center justify-center text-white shadow-xs" style={{ backgroundColor: accentColor }}>
                        <Sparkles className="w-4 h-4" />
                      </div>
                    )}
                    <div>
                      <h4 className="text-sm font-bold text-gray-900 dark:text-white leading-none">
                        {companyName || 'Company Name'}
                      </h4>
                      <p className="text-[10px] text-gray-400 dark:text-zinc-500 mt-1">
                        {tagline || 'Assistant Tagline'}
                      </p>
                    </div>
                  </div>
                </div>

                <div className="pt-2">
                  <button
                    type="submit"
                    disabled={brandingSaving}
                    className="px-5 py-2.5 bg-purple-600 hover:bg-purple-700 text-white rounded-xl text-xs font-semibold flex items-center gap-2 shadow-sm transition disabled:opacity-50"
                  >
                    {brandingSaving && <span className="animate-spin rounded-full h-3 w-3 border-2 border-white border-t-transparent" />}
                    Save Branding Settings
                  </button>
                </div>
              </form>
            )}

            {/* TAB: USERS (ADMIN) */}
            {activeTab === 'users' && currentUser?.role === 'admin' && (
              <div className="space-y-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="relative flex-1 max-w-sm">
                    <Search className="w-3.5 h-3.5 absolute left-3 top-3 text-gray-400" />
                    <input
                      type="text"
                      value={userSearch}
                      onChange={(e) => {
                        setUserSearch(e.target.value);
                        setUserPage(0);
                      }}
                      placeholder="Search users by name, username, email..."
                      className="w-full pl-9 pr-3.5 py-2 text-xs bg-gray-50 dark:bg-zinc-800 border border-gray-200 dark:border-zinc-700 rounded-xl focus:outline-none focus:ring-2 focus:ring-purple-500 text-gray-900 dark:text-white"
                    />
                  </div>
                  <button
                    type="button"
                    onClick={() => setShowCreateUserModal(true)}
                    className="px-3.5 py-2 bg-purple-600 hover:bg-purple-700 text-white text-xs font-semibold rounded-xl shadow-xs transition flex items-center gap-1.5"
                  >
                    + Add User
                  </button>
                </div>

                {/* Users Table */}
                <div className="border border-gray-200 dark:border-zinc-800 rounded-xl overflow-hidden">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-gray-50 dark:bg-zinc-800/60 border-b border-gray-200 dark:border-zinc-800 text-gray-500 dark:text-zinc-400 font-semibold uppercase text-[10px]">
                      <tr>
                        <th className="px-4 py-3">User</th>
                        <th className="px-3 py-3">Role</th>
                        <th className="px-3 py-3">Status</th>
                        <th className="px-3 py-3">Last Login</th>
                        <th className="px-4 py-3 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100 dark:divide-zinc-800">
                      {userLoading ? (
                        <tr>
                          <td colSpan={5} className="py-8 text-center text-gray-400">Loading users...</td>
                        </tr>
                      ) : userList.length === 0 ? (
                        <tr>
                          <td colSpan={5} className="py-8 text-center text-gray-400">No users found.</td>
                        </tr>
                      ) : (
                        userList.map((u) => {
                          const isSelf = u.id === currentUser.id;
                          return (
                            <tr key={u.id} className="hover:bg-gray-50/50 dark:hover:bg-zinc-800/40">
                              <td className="px-4 py-3">
                                <div className="flex items-center gap-2.5">
                                  <div
                                    className="w-7 h-7 rounded-lg text-white flex items-center justify-center font-bold text-[10px]"
                                    style={{ backgroundColor: u.avatar_color || '#10b981' }}
                                  >
                                    {(u.display_name || u.username || u.email).slice(0, 2).toUpperCase()}
                                  </div>
                                  <div>
                                    <p className="font-semibold text-gray-900 dark:text-white leading-tight">
                                      {u.display_name || u.username || 'User'}
                                    </p>
                                    <p className="text-[11px] text-gray-400">@{u.username || 'no-handle'} • {u.email}</p>
                                  </div>
                                </div>
                              </td>
                              <td className="px-3 py-3">
                                <button
                                  type="button"
                                  disabled={isSelf}
                                  onClick={() => handleToggleUserRole(u)}
                                  className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ${
                                    u.role === 'admin'
                                      ? 'bg-purple-100 dark:bg-purple-950/60 text-purple-700 dark:text-purple-300'
                                      : 'bg-emerald-100 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300'
                                  } ${!isSelf ? 'hover:opacity-80' : 'cursor-default'}`}
                                  title={isSelf ? 'Cannot demote self' : 'Click to toggle role'}
                                >
                                  {u.role}
                                </button>
                              </td>
                              <td className="px-3 py-3">
                                <button
                                  type="button"
                                  disabled={isSelf}
                                  onClick={() => handleToggleUserActive(u)}
                                  className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ${
                                    u.is_active
                                      ? 'bg-green-100 dark:bg-green-950/60 text-green-700 dark:text-green-300'
                                      : 'bg-red-100 dark:bg-red-950/60 text-red-700 dark:text-red-300'
                                  } ${!isSelf ? 'hover:opacity-80' : 'cursor-default'}`}
                                  title={isSelf ? 'Cannot disable self' : 'Click to toggle active status'}
                                >
                                  {u.is_active ? 'Active' : 'Disabled'}
                                </button>
                              </td>
                              <td className="px-3 py-3 text-[11px] text-gray-400">
                                {u.last_login_at ? new Date(u.last_login_at).toLocaleDateString() : 'Never'}
                              </td>
                              <td className="px-4 py-3 text-right space-x-1.5">
                                <button
                                  type="button"
                                  onClick={() => handleForceReset(u)}
                                  className="text-[11px] text-gray-500 hover:text-amber-600 dark:hover:text-amber-400 px-2 py-1 rounded hover:bg-gray-100 dark:hover:bg-zinc-800"
                                  title="Force password reset on next login"
                                >
                                  Force Reset
                                </button>
                              </td>
                            </tr>
                          );
                        })
                      )}
                    </tbody>
                  </table>
                </div>

                {/* Pagination */}
                <div className="flex items-center justify-between text-xs text-gray-500 pt-1">
                  <span>Showing {userList.length} of {userTotal} users</span>
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      disabled={userPage <= 0}
                      onClick={() => setUserPage((p) => p - 1)}
                      className="p-1 rounded border border-gray-200 dark:border-zinc-700 disabled:opacity-40"
                    >
                      <ChevronLeft className="w-4 h-4" />
                    </button>
                    <span className="px-2">Page {userPage + 1}</span>
                    <button
                      type="button"
                      disabled={(userPage + 1) * 20 >= userTotal}
                      onClick={() => setUserPage((p) => p + 1)}
                      className="p-1 rounded border border-gray-200 dark:border-zinc-700 disabled:opacity-40"
                    >
                      <ChevronRight className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                {/* Add User Modal */}
                {showCreateUserModal && (
                  <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60">
                    <div className="w-full max-w-md bg-white dark:bg-zinc-900 rounded-2xl p-6 border border-gray-200 dark:border-zinc-800 space-y-4 shadow-xl">
                      <div className="flex items-center justify-between">
                        <h3 className="text-sm font-bold text-gray-900 dark:text-white">Create New User</h3>
                        <button type="button" onClick={() => setShowCreateUserModal(false)} className="text-gray-400 hover:text-gray-600">
                          <X className="w-4 h-4" />
                        </button>
                      </div>
                      <form onSubmit={handleCreateUser} className="space-y-3">
                        <div>
                          <label className="block text-[11px] font-semibold text-gray-600 dark:text-zinc-400 uppercase">Username</label>
                          <input
                            type="text"
                            required
                            minLength={3}
                            maxLength={30}
                            pattern="^[a-zA-Z0-9_.]+$"
                            value={newUserData.username}
                            onChange={(e) => setNewUserData({ ...newUserData, username: e.target.value })}
                            className="w-full px-3 py-2 text-xs bg-gray-50 dark:bg-zinc-800 border border-gray-300 dark:border-zinc-700 rounded-xl text-gray-900 dark:text-white"
                          />
                        </div>
                        <div>
                          <label className="block text-[11px] font-semibold text-gray-600 dark:text-zinc-400 uppercase">Email Address</label>
                          <input
                            type="email"
                            required
                            value={newUserData.email}
                            onChange={(e) => setNewUserData({ ...newUserData, email: e.target.value })}
                            className="w-full px-3 py-2 text-xs bg-gray-50 dark:bg-zinc-800 border border-gray-300 dark:border-zinc-700 rounded-xl text-gray-900 dark:text-white"
                          />
                        </div>
                        <div>
                          <label className="block text-[11px] font-semibold text-gray-600 dark:text-zinc-400 uppercase">Initial Password</label>
                          <input
                            type="password"
                            required
                            minLength={8}
                            value={newUserData.password}
                            onChange={(e) => setNewUserData({ ...newUserData, password: e.target.value })}
                            className="w-full px-3 py-2 text-xs bg-gray-50 dark:bg-zinc-800 border border-gray-300 dark:border-zinc-700 rounded-xl text-gray-900 dark:text-white"
                          />
                        </div>
                        <div>
                          <label className="block text-[11px] font-semibold text-gray-600 dark:text-zinc-400 uppercase">Role</label>
                          <select
                            value={newUserData.role}
                            onChange={(e) => setNewUserData({ ...newUserData, role: e.target.value })}
                            className="w-full px-3 py-2 text-xs bg-gray-50 dark:bg-zinc-800 border border-gray-300 dark:border-zinc-700 rounded-xl text-gray-900 dark:text-white"
                          >
                            <option value="user">Regular User</option>
                            <option value="admin">Administrator</option>
                          </select>
                        </div>
                        <div className="pt-2 flex justify-end gap-2">
                          <button type="button" onClick={() => setShowCreateUserModal(false)} className="px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-100 rounded-lg">
                            Cancel
                          </button>
                          <button type="submit" className="px-4 py-1.5 text-xs font-semibold bg-purple-600 hover:bg-purple-700 text-white rounded-lg">
                            Create User
                          </button>
                        </div>
                      </form>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* TAB: REQUESTS INBOX (ADMIN) */}
            {activeTab === 'requests' && currentUser?.role === 'admin' && (
              <div className="space-y-4">
                {selectedReqThread ? (
                  /* Admin Thread Inspector */
                  <div className="space-y-4">
                    <div className="flex items-center justify-between pb-3 border-b border-gray-100 dark:border-zinc-800">
                      <button
                        type="button"
                        onClick={() => setSelectedReqThread(null)}
                        className="flex items-center gap-1 text-xs font-semibold text-gray-500 hover:text-gray-800 dark:hover:text-white"
                      >
                        <ChevronLeft className="w-4 h-4" />
                        Back to requests inbox
                      </button>
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-gray-500">Status:</span>
                        <select
                          value={selectedReqThread.status}
                          onChange={(e) => handleAdminStatusChange(e.target.value)}
                          className="px-2.5 py-1 text-xs bg-gray-50 dark:bg-zinc-800 border border-gray-300 dark:border-zinc-700 rounded-lg text-gray-900 dark:text-white"
                        >
                          <option value="open">Open</option>
                          <option value="in_progress">In Progress</option>
                          <option value="resolved">Resolved</option>
                          <option value="closed">Closed</option>
                        </select>
                      </div>
                    </div>

                    <div className="p-3.5 rounded-xl bg-gray-50 dark:bg-zinc-800/60 border border-gray-200 dark:border-zinc-700">
                      <div className="flex items-center justify-between text-xs font-bold text-gray-800 dark:text-zinc-200 mb-1">
                        <span>{selectedReqThread.user_email} • {selectedReqThread.subject}</span>
                        <span className="text-[10px] font-normal text-gray-400">{new Date(selectedReqThread.created_at).toLocaleString()}</span>
                      </div>
                      <p className="text-xs text-gray-700 dark:text-zinc-300 whitespace-pre-wrap">{selectedReqThread.message}</p>
                    </div>

                    {/* Messages */}
                    <div className="space-y-2.5 max-h-60 overflow-y-auto">
                      {(selectedReqThread.messages || []).map((m) => {
                        const isAdmin = m.sender_role === 'admin';
                        return (
                          <div
                            key={m.id}
                            className={`p-3 rounded-xl border text-xs ${
                              isAdmin
                                ? 'bg-purple-50/70 dark:bg-purple-950/30 border-purple-200 dark:border-purple-900/50 mr-4'
                                : 'bg-white dark:bg-zinc-800 border-gray-200 dark:border-zinc-700 ml-4'
                            }`}
                          >
                            <div className="flex items-center justify-between font-semibold mb-1">
                              <span className={isAdmin ? 'text-purple-700 dark:text-purple-300' : 'text-gray-800 dark:text-zinc-200'}>
                                {isAdmin ? 'Admin (You)' : 'User'}
                              </span>
                              <span className="text-[10px] text-gray-400 font-normal">
                                {new Date(m.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                              </span>
                            </div>
                            <p className="whitespace-pre-wrap text-gray-800 dark:text-zinc-200">{m.body}</p>
                          </div>
                        );
                      })}
                    </div>

                    {/* Reply box */}
                    <form onSubmit={handleAdminReplySubmit} className="pt-2 flex gap-2">
                      <input
                        type="text"
                        required
                        value={adminReplyText}
                        onChange={(e) => setAdminReplyText(e.target.value)}
                        placeholder="Reply to user (triggers a notification)..."
                        className="flex-1 px-3 py-2 text-xs bg-gray-50 dark:bg-zinc-800 border border-gray-300 dark:border-zinc-700 rounded-xl text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-purple-500"
                      />
                      <button
                        type="submit"
                        disabled={replyingToUser || !adminReplyText.trim()}
                        className="px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-xl text-xs font-semibold flex items-center gap-1.5 transition disabled:opacity-50"
                      >
                        <Send className="w-3.5 h-3.5" />
                        Reply
                      </button>
                    </form>
                  </div>
                ) : (
                  /* List */
                  <div className="space-y-3">
                    <div className="flex items-center gap-1.5">
                      {['', 'open', 'in_progress', 'resolved', 'closed'].map((st) => (
                        <button
                          key={st}
                          type="button"
                          onClick={() => setReqStatusFilter(st)}
                          className={`px-3 py-1 rounded-lg text-xs font-semibold capitalize transition ${
                            reqStatusFilter === st
                              ? 'bg-purple-100 dark:bg-purple-950/60 text-purple-700 dark:text-purple-300'
                              : 'text-gray-500 hover:bg-gray-100 dark:hover:bg-zinc-800'
                          }`}
                        >
                          {st || 'All'}
                        </button>
                      ))}
                    </div>

                    <div className="divide-y divide-gray-100 dark:divide-zinc-800 border border-gray-200 dark:border-zinc-800 rounded-xl overflow-hidden">
                      {reqLoading ? (
                        <div className="py-8 text-center text-xs text-gray-400">Loading inbox...</div>
                      ) : adminRequests.length === 0 ? (
                        <div className="py-8 text-center text-xs text-gray-400">No requests match this filter.</div>
                      ) : (
                        adminRequests.map((req) => (
                          <div
                            key={req.id}
                            onClick={async () => {
                              const full = await apiGetSupportRequest(req.id);
                              setSelectedReqThread(full);
                            }}
                            className="p-3.5 hover:bg-gray-50 dark:hover:bg-zinc-800/40 cursor-pointer flex items-center justify-between"
                          >
                            <div>
                              <div className="flex items-center gap-2 mb-1">
                                <span className="text-xs font-bold text-gray-900 dark:text-white">{req.subject}</span>
                                <span className="px-2 py-0.2 rounded-full text-[10px] font-bold uppercase bg-gray-100 dark:bg-zinc-800 text-gray-600 dark:text-zinc-400">
                                  {req.status}
                                </span>
                              </div>
                              <p className="text-[11px] text-gray-500 dark:text-zinc-400 line-clamp-1">
                                {req.user_email} • {req.message}
                              </p>
                              <span className="text-[10px] text-gray-400 block mt-1">
                                {new Date(req.created_at).toLocaleString()}
                              </span>
                            </div>
                            <span className="text-xs text-purple-600 dark:text-purple-400 font-medium">
                              Open Thread &rarr;
                            </span>
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* TAB: PASSWORD RESETS (ADMIN) */}
            {activeTab === 'resets' && currentUser?.role === 'admin' && (
              <div className="space-y-4">
                <p className="text-xs text-gray-500 dark:text-zinc-400">
                  When SMTP email delivery is disabled, pending user password resets require admin approval. Approving generates a one-time link to share with the user.
                </p>

                {approvedLinkData && (
                  <div className="p-4 rounded-xl border border-emerald-300 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950/40 space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold text-emerald-800 dark:text-emerald-300">
                        Single-Use Reset Link Generated for {approvedLinkData.email}
                      </span>
                      <button
                        type="button"
                        onClick={() => setApprovedLinkData(null)}
                        className="text-emerald-700 hover:text-emerald-900"
                      >
                        <X className="w-4 h-4" />
                      </button>
                    </div>
                    <div className="flex items-center gap-2">
                      <input
                        type="text"
                        readOnly
                        value={approvedLinkData.reset_url}
                        className="flex-1 px-3 py-1.5 text-xs bg-white dark:bg-zinc-900 border border-emerald-300 dark:border-emerald-700 rounded-lg font-mono text-gray-800 dark:text-zinc-200"
                      />
                      <button
                        type="button"
                        onClick={() => {
                          navigator.clipboard.writeText(approvedLinkData.reset_url);
                          if (onToast) onToast('Link copied to clipboard', 'success');
                        }}
                        className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-semibold flex items-center gap-1"
                      >
                        <Copy className="w-3.5 h-3.5" />
                        Copy
                      </button>
                    </div>
                    <p className="text-[10px] text-emerald-700 dark:text-emerald-400">
                      Share this URL with the user. It expires in 30 minutes and can only be used once.
                    </p>
                  </div>
                )}

                <div className="border border-gray-200 dark:border-zinc-800 rounded-xl overflow-hidden">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-gray-50 dark:bg-zinc-800/60 border-b border-gray-200 dark:border-zinc-800 text-[10px] font-semibold uppercase text-gray-500">
                      <tr>
                        <th className="px-4 py-3">Requester Email</th>
                        <th className="px-3 py-3">Requested At</th>
                        <th className="px-3 py-3">Status</th>
                        <th className="px-4 py-3 text-right">Action</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100 dark:divide-zinc-800">
                      {resetsLoading ? (
                        <tr><td colSpan={4} className="py-8 text-center text-gray-400">Loading reset requests...</td></tr>
                      ) : resetsList.length === 0 ? (
                        <tr><td colSpan={4} className="py-8 text-center text-gray-400">No pending password reset requests.</td></tr>
                      ) : (
                        resetsList.map((r) => (
                          <tr key={r.id}>
                            <td className="px-4 py-3 font-semibold text-gray-900 dark:text-white">{r.user_email}</td>
                            <td className="px-3 py-3 text-gray-400 text-[11px]">{new Date(r.created_at).toLocaleString()}</td>
                            <td className="px-3 py-3">
                              <span className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300">
                                {r.status}
                              </span>
                            </td>
                            <td className="px-4 py-3 text-right space-x-2">
                              <button
                                type="button"
                                onClick={() => handleApproveReset(r)}
                                className="px-3 py-1 rounded bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold"
                              >
                                Approve
                              </button>
                              <button
                                type="button"
                                onClick={() => handleRejectReset(r)}
                                className="px-3 py-1 rounded border border-gray-300 dark:border-zinc-700 text-gray-600 hover:bg-gray-100 dark:hover:bg-zinc-800 text-xs"
                              >
                                Reject
                              </button>
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* TAB: AUDIT LOG (ADMIN) */}
            {activeTab === 'audit' && currentUser?.role === 'admin' && (
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-500">Immutable system action logs</span>
                  <button
                    type="button"
                    onClick={loadAuditLogs}
                    className="p-1 text-gray-400 hover:text-gray-600 rounded"
                    title="Refresh log"
                  >
                    <RefreshCw className="w-3.5 h-3.5" />
                  </button>
                </div>
                <div className="border border-gray-200 dark:border-zinc-800 rounded-xl overflow-hidden max-h-[480px] overflow-y-auto">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-gray-50 dark:bg-zinc-800/60 border-b border-gray-200 dark:border-zinc-800 text-[10px] font-semibold uppercase text-gray-500 sticky top-0">
                      <tr>
                        <th className="px-3 py-2.5">Time</th>
                        <th className="px-3 py-2.5">Actor</th>
                        <th className="px-3 py-2.5">Action</th>
                        <th className="px-3 py-2.5">Target</th>
                        <th className="px-3 py-2.5">Details</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100 dark:divide-zinc-800/60">
                      {auditLoading ? (
                        <tr><td colSpan={5} className="py-8 text-center text-gray-400">Loading audit log...</td></tr>
                      ) : auditLogs.length === 0 ? (
                        <tr><td colSpan={5} className="py-8 text-center text-gray-400">No audit events recorded.</td></tr>
                      ) : (
                        auditLogs.map((log) => (
                          <tr key={log.id} className="hover:bg-gray-50/50 dark:hover:bg-zinc-800/30">
                            <td className="px-3 py-2 text-[11px] text-gray-400 whitespace-nowrap">
                              {new Date(log.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                            </td>
                            <td className="px-3 py-2 font-mono text-[11px] text-gray-700 dark:text-zinc-300">
                              {log.actor_email || `ID:${log.actor_id}`}
                            </td>
                            <td className="px-3 py-2 font-semibold text-gray-900 dark:text-white">
                              {log.action}
                            </td>
                            <td className="px-3 py-2 text-gray-500 text-[11px]">
                              {log.target || '-'}
                            </td>
                            <td className="px-3 py-2 text-gray-400 text-[11px] truncate max-w-xs" title={log.details}>
                              {log.details || '-'}
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
