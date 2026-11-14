import React, { useState, useEffect, useRef } from 'react';
import {
  Users,
  FileText,
  Database,
  MessageSquare,
  HardDrive,
  Trash2,
  Upload,
  RefreshCw,
  Search,
  Eye,
  CheckCircle,
  Clock,
  AlertCircle,
  ArrowLeft,
  X,
  ThumbsUp,
  ThumbsDown,
  BarChart2,
  HelpCircle,
  Activity,
  Cpu,
  Terminal,
} from 'lucide-react';
import {
  apiGetAdminStats,
  apiGetAdminDocuments,
  apiDeleteAdminDocument,
  apiGetAdminUsers,
  apiGetAdminUserConversations,
  apiUploadDocument,
  apiGetDocumentStatus,
  apiGetAnalytics,
  apiGetDiagnostics,
} from '../api';
import ErrorBoundary from './ErrorBoundary';

export default function AdminDashboard({ onBackToChat }) {
  const [activeTab, setActiveTab] = useState('overview'); // 'overview' | 'docs' | 'users' | 'history' | 'analytics' | 'diagnostics'
  const [stats, setStats] = useState(null);
  const [companyDocs, setCompanyDocs] = useState([]);
  const [users, setUsers] = useState([]);
  const [analytics, setAnalytics] = useState(null);
  const [diagnostics, setDiagnostics] = useState(null);
  const [loading, setLoading] = useState(true);

  // Upload state
  const [uploadStatus, setUploadStatus] = useState(null);
  const fileInputRef = useRef(null);

  // Chat History Viewer state
  const [selectedUserId, setSelectedUserId] = useState(null);
  const [userConversations, setUserConversations] = useState([]);
  const [selectedConversation, setSelectedConversation] = useState(null);

  const loadData = async () => {
    setLoading(true);
    try {
      const [statsData, docsData, usersData, analyticsData, diagData] = await Promise.all([
        apiGetAdminStats(),
        apiGetAdminDocuments(),
        apiGetAdminUsers(),
        apiGetAnalytics().catch((err) => {
          console.error('Failed to load analytics:', err);
          return null;
        }),
        apiGetDiagnostics().catch((err) => {
          console.error('Failed to load diagnostics:', err);
          return null;
        }),
      ]);
      setStats(statsData);
      setCompanyDocs(docsData);
      setUsers(usersData);
      if (analyticsData) setAnalytics(analyticsData);
      if (diagData) setDiagnostics(diagData);
    } catch (err) {
      console.error('Failed to load admin data:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  useEffect(() => {
    if (activeTab === 'history' && !selectedUserId && users.length > 0) {
      handleInspectUser(users[0].id);
    }
  }, [activeTab, users, selectedUserId]);

  // Handle Document Delete
  const handleDeleteDoc = async (docId, filename) => {
    if (!window.confirm(`Are you sure you want to delete "${filename}"? All vectors and extracted files will be deleted.`)) {
      return;
    }
    try {
      await apiDeleteAdminDocument(docId);
      setCompanyDocs((prev) => prev.filter((d) => d.id !== docId));
      loadData();
    } catch (err) {
      alert(`Delete failed: ${err.message}`);
    }
  };

  // Handle Admin Document Upload
  const handleAdminUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploadStatus({ filename: file.name, state: 'uploading', progress: 0 });

    try {
      const doc = await apiUploadDocument(file, null, (percent) => {
        setUploadStatus((prev) => (prev ? { ...prev, progress: percent } : { filename: file.name, state: 'uploading', progress: percent }));
      });
      setUploadStatus({ filename: file.name, state: 'processing', progress: 100 });

      // Poll until ready
      const checkInterval = setInterval(async () => {
        try {
          const statusRes = await apiGetDocumentStatus(doc.id);
          if (statusRes.status === 'ready') {
            clearInterval(checkInterval);
            setUploadStatus({ filename: file.name, state: 'ready' });
            loadData();
            setTimeout(() => setUploadStatus(null), 3500);
          } else if (statusRes.status === 'failed') {
            clearInterval(checkInterval);
            setUploadStatus({ filename: file.name, state: 'failed', error: statusRes.error_message });
          }
        } catch {
          clearInterval(checkInterval);
        }
      }, 1500);
    } catch (err) {
      setUploadStatus({ filename: file.name, state: 'failed', error: err.message });
      setTimeout(() => setUploadStatus(null), 5000);
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  // Load User Chat History
  const handleInspectUser = async (userId) => {
    setSelectedUserId(userId);
    setActiveTab('history');
    try {
      const convs = await apiGetAdminUserConversations(userId);
      setUserConversations(convs);
      setSelectedConversation(convs[0] || null);
    } catch (err) {
      alert(`Failed to load user chats: ${err.message}`);
    }
  };

  return (
    <div className="flex-1 flex flex-col h-screen bg-gray-50 dark:bg-zinc-950 overflow-hidden">
      {/* Top Bar */}
      <header className="h-16 border-b border-gray-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-6 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onBackToChat}
            className="p-2 rounded-xl text-gray-500 hover:bg-gray-100 dark:hover:bg-zinc-800 transition flex items-center gap-1.5 text-xs font-semibold"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Chat
          </button>
          <div className="h-4 w-px bg-gray-200 dark:border-zinc-800" />
          <h1 className="text-base font-bold text-gray-900 dark:text-white">
            Admin Management Console
          </h1>
        </div>

        {/* Tab Switcher */}
        <div className="flex items-center gap-1 bg-gray-100 dark:bg-zinc-800 p-1 rounded-xl text-xs font-medium">
          <button
            type="button"
            onClick={() => setActiveTab('overview')}
            className={`px-3 py-1.5 rounded-lg transition ${
              activeTab === 'overview'
                ? 'bg-white dark:bg-zinc-900 text-gray-900 dark:text-white shadow-sm'
                : 'text-gray-500 hover:text-gray-800 dark:hover:text-zinc-200'
            }`}
          >
            Overview
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('docs')}
            className={`px-3 py-1.5 rounded-lg transition ${
              activeTab === 'docs'
                ? 'bg-white dark:bg-zinc-900 text-gray-900 dark:text-white shadow-sm'
                : 'text-gray-500 hover:text-gray-800 dark:hover:text-zinc-200'
            }`}
          >
            Company Docs ({companyDocs.length})
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('users')}
            className={`px-3 py-1.5 rounded-lg transition ${
              activeTab === 'users'
                ? 'bg-white dark:bg-zinc-900 text-gray-900 dark:text-white shadow-sm'
                : 'text-gray-500 hover:text-gray-800 dark:hover:text-zinc-200'
            }`}
          >
            Users ({users.length})
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('history')}
            className={`px-3 py-1.5 rounded-lg transition ${
              activeTab === 'history'
                ? 'bg-white dark:bg-zinc-900 text-gray-900 dark:text-white shadow-sm'
                : 'text-gray-500 hover:text-gray-800 dark:hover:text-zinc-200'
            }`}
          >
            Chat Audits
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('analytics')}
            className={`px-3 py-1.5 rounded-lg transition flex items-center gap-1.5 ${
              activeTab === 'analytics'
                ? 'bg-white dark:bg-zinc-900 text-gray-900 dark:text-white shadow-sm'
                : 'text-gray-500 hover:text-gray-800 dark:hover:text-zinc-200'
            }`}
          >
            <BarChart2 className="w-3.5 h-3.5 text-emerald-500" />
            Analytics
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('diagnostics')}
            className={`px-3 py-1.5 rounded-lg transition flex items-center gap-1.5 ${
              activeTab === 'diagnostics'
                ? 'bg-white dark:bg-zinc-900 text-gray-900 dark:text-white shadow-sm'
                : 'text-gray-500 hover:text-gray-800 dark:hover:text-zinc-200'
            }`}
          >
            <Cpu className="w-3.5 h-3.5 text-blue-500" />
            Diagnostics
          </button>
          <button
            type="button"
            onClick={loadData}
            className="p-1.5 text-gray-500 hover:text-gray-800 dark:hover:text-zinc-200 rounded-lg"
            title="Refresh"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </header>

      {/* Main Content Area */}
      <div className="flex-1 overflow-y-auto p-6 max-w-6xl mx-auto w-full space-y-6">
        {/* Upload Notification */}
        {uploadStatus && (
          <div className="p-3 bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-xl flex items-center justify-between text-xs shadow-sm">
            <div className="flex items-center gap-2">
              {uploadStatus.state === 'uploading' && <Clock className="w-4 h-4 text-blue-500 animate-spin" />}
              {uploadStatus.state === 'processing' && <Clock className="w-4 h-4 text-amber-500 animate-pulse" />}
              {uploadStatus.state === 'ready' && <CheckCircle className="w-4 h-4 text-emerald-500" />}
              {uploadStatus.state === 'failed' && <AlertCircle className="w-4 h-4 text-red-500" />}
              <span className="font-semibold text-gray-800 dark:text-white">{uploadStatus.filename}:</span>
              <span className="text-gray-500 dark:text-gray-400 flex items-center gap-2">
                {uploadStatus.state === 'uploading' && (
                  <>
                    <span>Uploading document ({uploadStatus.progress ?? 0}%)...</span>
                    <span className="w-20 bg-gray-200 dark:bg-zinc-700 rounded-full h-1.5 overflow-hidden inline-block">
                      <span
                        className="bg-blue-600 h-1.5 block rounded-full transition-all duration-150"
                        style={{ width: `${uploadStatus.progress ?? 0}%` }}
                      />
                    </span>
                  </>
                )}
                {uploadStatus.state === 'processing' && 'Extracting text & images, computing BGE embeddings...'}
                {uploadStatus.state === 'ready' && 'Ingestion complete! Available to all company users.'}
                {uploadStatus.state === 'failed' && `Error: ${uploadStatus.error || 'Failed'}`}
              </span>
            </div>
            <button onClick={() => setUploadStatus(null)} className="text-gray-400 hover:text-gray-600">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        {/* ================= TAB 1: OVERVIEW STATS ================= */}
        {activeTab === 'overview' && (
          <div className="space-y-6">
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
              {[
                { title: 'Total Users', value: stats?.total_users ?? 0, icon: Users, color: 'text-blue-600 bg-blue-100 dark:bg-blue-950/60' },
                { title: 'Company Documents', value: stats?.total_company_docs ?? 0, icon: FileText, color: 'text-emerald-600 bg-emerald-100 dark:bg-emerald-950/60' },
                { title: 'ChromaDB Chunks', value: stats?.total_chunks ?? 0, icon: Database, color: 'text-purple-600 bg-purple-100 dark:bg-purple-950/60' },
                { title: 'Total Messages', value: stats?.total_messages ?? 0, icon: MessageSquare, color: 'text-amber-600 bg-amber-100 dark:bg-amber-950/60' },
                { title: 'Storage Used', value: `${stats?.storage_mb ?? 0} MB`, icon: HardDrive, color: 'text-rose-600 bg-rose-100 dark:bg-rose-950/60' },
              ].map((card, i) => (
                <div
                  key={i}
                  className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-2xl p-4 shadow-sm"
                >
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-xs font-semibold text-gray-500 dark:text-gray-400">
                      {card.title}
                    </span>
                    <div className={`p-2 rounded-xl ${card.color}`}>
                      <card.icon className="w-4 h-4" />
                    </div>
                  </div>
                  <p className="text-2xl font-bold text-gray-900 dark:text-white">
                    {card.value}
                  </p>
                </div>
              ))}
            </div>

            {/* Quick Actions Card */}
            <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-2xl p-6 shadow-sm flex items-center justify-between">
              <div>
                <h3 className="text-sm font-bold text-gray-900 dark:text-white">
                  Add Company Knowledge Base Documents
                </h3>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  Upload PDF, DOCX, TXT, PNG, or JPG files. They are automatically indexed for all users.
                </p>
              </div>
              <input
                ref={fileInputRef}
                type="file"
                onChange={handleAdminUpload}
                accept=".pdf,.docx,.txt,.png,.jpg,.jpeg"
                className="hidden"
              />
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="py-2.5 px-4 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-xs font-semibold flex items-center gap-2 shadow-sm transition"
              >
                <Upload className="w-4 h-4" />
                Upload Company Document
              </button>
            </div>
          </div>
        )}

        {/* ================= TAB 2: COMPANY DOCUMENTS ================= */}
        {activeTab === 'docs' && (
          <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-2xl shadow-sm overflow-hidden">
            <div className="p-4 border-b border-gray-200 dark:border-zinc-800 flex items-center justify-between">
              <h3 className="text-sm font-bold text-gray-900 dark:text-white">
                Company Knowledge Base Documents
              </h3>
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="py-1.5 px-3 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-xs font-semibold flex items-center gap-1.5 shadow-sm transition"
              >
                <Upload className="w-3.5 h-3.5" />
                Upload File
              </button>
            </div>

            <table className="w-full text-left text-xs text-gray-600 dark:text-zinc-300">
              <thead className="bg-gray-50 dark:bg-zinc-800/60 uppercase font-semibold text-[10px] text-gray-400 dark:text-zinc-400">
                <tr>
                  <th className="py-3 px-4">Filename</th>
                  <th className="py-3 px-4">Format</th>
                  <th className="py-3 px-4">Status</th>
                  <th className="py-3 px-4">Pages / Sections</th>
                  <th className="py-3 px-4">Chunks</th>
                  <th className="py-3 px-4">Uploaded</th>
                  <th className="py-3 px-4 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-zinc-800">
                {companyDocs.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="py-8 text-center text-gray-400">
                      No company documents uploaded yet. Upload a demo file above!
                    </td>
                  </tr>
                ) : (
                  companyDocs.map((d) => (
                    <tr key={d.id} className="hover:bg-gray-50/60 dark:hover:bg-zinc-800/40">
                      <td className="py-3 px-4 font-semibold text-gray-900 dark:text-white flex items-center gap-2">
                        <FileText className="w-3.5 h-3.5 text-emerald-500" />
                        <span className="truncate max-w-xs">{d.filename}</span>
                      </td>
                      <td className="py-3 px-4 uppercase font-bold text-[10px] text-gray-400">
                        {d.file_type}
                      </td>
                      <td className="py-3 px-4">
                        <span
                          className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ${
                            d.status === 'ready'
                              ? 'bg-emerald-100 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300'
                              : d.status === 'processing'
                              ? 'bg-amber-100 dark:bg-amber-950/60 text-amber-700 dark:text-amber-300'
                              : 'bg-red-100 dark:bg-red-950/60 text-red-700 dark:text-red-300'
                          }`}
                        >
                          {d.status}
                        </span>
                      </td>
                      <td className="py-3 px-4">{d.page_count}</td>
                      <td className="py-3 px-4 font-mono">{d.chunk_count}</td>
                      <td className="py-3 px-4 text-gray-400">
                        {new Date(d.uploaded_at).toLocaleDateString()}
                      </td>
                      <td className="py-3 px-4 text-right">
                        <button
                          type="button"
                          onClick={() => handleDeleteDoc(d.id, d.filename)}
                          className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-500/10 rounded-lg transition"
                          title="Delete Document"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}

        {/* ================= TAB 3: USERS LIST ================= */}
        {activeTab === 'users' && (
          <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-2xl shadow-sm overflow-hidden">
            <div className="p-4 border-b border-gray-200 dark:border-zinc-800">
              <h3 className="text-sm font-bold text-gray-900 dark:text-white">
                Registered Users & Activity Summary
              </h3>
            </div>
            <table className="w-full text-left text-xs text-gray-600 dark:text-zinc-300">
              <thead className="bg-gray-50 dark:bg-zinc-800/60 uppercase font-semibold text-[10px] text-gray-400 dark:text-zinc-400">
                <tr>
                  <th className="py-3 px-4">User ID</th>
                  <th className="py-3 px-4">Email</th>
                  <th className="py-3 px-4">Role</th>
                  <th className="py-3 px-4">Conversations</th>
                  <th className="py-3 px-4">User Docs</th>
                  <th className="py-3 px-4 text-right">Inspect History</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-zinc-800">
                {users.map((u) => (
                  <tr key={u.id} className="hover:bg-gray-50/60 dark:hover:bg-zinc-800/40">
                    <td className="py-3 px-4 font-mono">#{u.id}</td>
                    <td className="py-3 px-4 font-semibold text-gray-900 dark:text-white">
                      {u.email}
                    </td>
                    <td className="py-3 px-4">
                      <span
                        className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ${
                          u.role === 'admin'
                            ? 'bg-purple-100 dark:bg-purple-950/60 text-purple-700 dark:text-purple-300'
                            : 'bg-blue-100 dark:bg-blue-950/60 text-blue-700 dark:text-blue-300'
                        }`}
                      >
                        {u.role}
                      </span>
                    </td>
                    <td className="py-3 px-4">{u.chat_count}</td>
                    <td className="py-3 px-4">{u.doc_count}</td>
                    <td className="py-3 px-4 text-right">
                      <button
                        type="button"
                        onClick={() => handleInspectUser(u.id)}
                        className="py-1 px-3 bg-gray-100 dark:bg-zinc-800 hover:bg-emerald-600 hover:text-white rounded-lg text-xs font-medium transition"
                      >
                        View Chats
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* ================= TAB 4: CHAT AUDIT VIEWER ================= */}
        {activeTab === 'history' && (
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4 h-[580px]">
            {/* Column 1: Users List (Rule 5: list users, click a user, see chats & messages) */}
            <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-2xl p-3 overflow-y-auto space-y-1.5">
              <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-2 px-1">
                Users ({users.length})
              </h3>
              {users.map((u) => (
                <div
                  key={u.id}
                  onClick={() => handleInspectUser(u.id)}
                  className={`p-2.5 rounded-xl cursor-pointer text-xs transition ${
                    selectedUserId === u.id
                      ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 font-semibold border border-emerald-300 dark:border-emerald-800'
                      : 'bg-gray-50/60 dark:bg-zinc-800/40 hover:bg-gray-100 dark:hover:bg-zinc-800 text-gray-700 dark:text-zinc-300'
                  }`}
                >
                  <p className="truncate font-semibold">{u.email}</p>
                  <div className="flex items-center justify-between text-[10px] text-gray-400 mt-1">
                    <span className="uppercase font-bold">{u.role}</span>
                    <span>{u.chat_count} chats</span>
                  </div>
                </div>
              ))}
            </div>

            {/* Column 2: User Conversations */}
            <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-2xl p-3 overflow-y-auto space-y-1.5">
              <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-2 px-1">
                Chats {selectedUserId ? `(#${selectedUserId})` : ''} ({userConversations.length})
              </h3>
              {userConversations.length === 0 ? (
                <p className="text-xs text-gray-400 py-6 text-center">
                  {selectedUserId ? 'No chat history for this user.' : 'Select a user to inspect.'}
                </p>
              ) : (
                userConversations.map((c) => (
                  <div
                    key={c.id}
                    onClick={() => setSelectedConversation(c)}
                    className={`p-2.5 rounded-xl cursor-pointer text-xs transition ${
                      selectedConversation?.id === c.id
                        ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 font-semibold border border-emerald-300 dark:border-emerald-800'
                        : 'bg-gray-50/60 dark:bg-zinc-800/40 hover:bg-gray-100 dark:hover:bg-zinc-800 text-gray-700 dark:text-zinc-300'
                    }`}
                  >
                    <p className="truncate font-semibold">{c.title || 'Untitled'}</p>
                    <div className="flex items-center justify-between text-[10px] text-gray-400 mt-1">
                      <span>{c.messages?.length || 0} msgs</span>
                      <span>{new Date(c.updated_at).toLocaleDateString()}</span>
                    </div>
                  </div>
                ))
              )}
            </div>

            {/* Column 3 & 4: Transcript Audit View */}
            <div className="md:col-span-2 bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-2xl p-4 flex flex-col overflow-hidden">
              <div className="flex items-center justify-between pb-3 border-b border-gray-100 dark:border-zinc-800 mb-3">
                <h3 className="text-xs font-bold text-gray-900 dark:text-white truncate max-w-md">
                  Transcript: {selectedConversation?.title || 'No chat selected'}
                </h3>
                {selectedConversation?.active_doc_name && (
                  <span className="text-[10px] font-semibold text-emerald-600 bg-emerald-50 dark:bg-emerald-950/40 px-2 py-0.5 rounded-full border border-emerald-200 dark:border-emerald-900">
                    Doc: {selectedConversation.active_doc_name}
                  </span>
                )}
              </div>

              <div className="flex-1 overflow-y-auto space-y-3 pr-2">
                {!selectedConversation || selectedConversation.messages?.length === 0 ? (
                  <p className="text-xs text-gray-400 text-center py-10">
                    No messages recorded in this conversation.
                  </p>
                ) : (
                  selectedConversation.messages.map((m) => (
                    <div
                      key={m.id}
                      className={`p-3 rounded-2xl text-xs leading-relaxed space-y-1.5 ${
                        m.sender === 'user'
                          ? 'bg-emerald-50/80 dark:bg-emerald-950/40 text-emerald-900 dark:text-emerald-200 border border-emerald-200 dark:border-emerald-900'
                          : 'bg-gray-50 dark:bg-zinc-800 text-gray-800 dark:text-zinc-200 border border-gray-200 dark:border-zinc-700'
                      }`}
                    >
                      <div className="flex items-center justify-between text-[10px] font-semibold opacity-70">
                        <span className="uppercase tracking-wider">{m.sender}</span>
                        <span>{new Date(m.created_at).toLocaleString()}</span>
                      </div>
                      <p className="whitespace-pre-wrap">{m.content}</p>

                      {/* Display Sources if any */}
                      {m.sources && m.sources.length > 0 && (
                        <div className="pt-2 border-t border-gray-200/50 dark:border-zinc-700/50 flex flex-wrap gap-1">
                          <span className="text-[10px] font-bold text-gray-400 mr-1">Sources:</span>
                          {m.sources.map((s, si) => (
                            <span
                              key={si}
                              className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-700 text-gray-600 dark:text-zinc-300"
                            >
                              <FileText className="w-2.5 h-2.5 text-emerald-500" />
                              {s.filename} ({s.location_label})
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        )}

        {/* ================= TAB 5: ANALYTICS ================= */}
        {activeTab === 'analytics' && (
          <div className="space-y-6">
            {/* 1. Summary Cards */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
              <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 p-4 rounded-2xl shadow-sm">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-gray-500 dark:text-gray-400">Total Questions</span>
                  <div className="p-2 bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 rounded-xl">
                    <MessageSquare className="w-4 h-4" />
                  </div>
                </div>
                <div className="mt-3">
                  <div className="text-2xl font-bold text-gray-900 dark:text-white">
                    {analytics?.summary?.total_questions || 0}
                  </div>
                  <span className="text-[11px] text-gray-400">Total user queries asked</span>
                </div>
              </div>

              <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 p-4 rounded-2xl shadow-sm">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-gray-500 dark:text-gray-400">Thumbs-Up %</span>
                  <div className="p-2 bg-blue-50 dark:bg-blue-950/60 text-blue-600 rounded-xl">
                    <ThumbsUp className="w-4 h-4" />
                  </div>
                </div>
                <div className="mt-3">
                  <div className="text-2xl font-bold text-gray-900 dark:text-white">
                    {analytics?.summary?.thumbs_up_pct || 0}%
                  </div>
                  <span className="text-[11px] text-gray-400">
                    {analytics?.summary?.thumbs_up_count || 0} positive ratings
                  </span>
                </div>
              </div>

              <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 p-4 rounded-2xl shadow-sm">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-gray-500 dark:text-gray-400">Thumbs-Down</span>
                  <div className="p-2 bg-rose-50 dark:bg-rose-950/60 text-rose-600 rounded-xl">
                    <ThumbsDown className="w-4 h-4" />
                  </div>
                </div>
                <div className="mt-3">
                  <div className="text-2xl font-bold text-gray-900 dark:text-white">
                    {analytics?.summary?.thumbs_down_count || 0}
                  </div>
                  <span className="text-[11px] text-gray-400">Negative ratings flagged</span>
                </div>
              </div>

              <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 p-4 rounded-2xl shadow-sm">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-gray-500 dark:text-gray-400">Not Found Rate</span>
                  <div className="p-2 bg-amber-50 dark:bg-amber-950/60 text-amber-600 rounded-xl">
                    <HelpCircle className="w-4 h-4" />
                  </div>
                </div>
                <div className="mt-3">
                  <div className="text-2xl font-bold text-gray-900 dark:text-white">
                    {analytics?.summary?.not_found_rate || 0}%
                  </div>
                  <span className="text-[11px] text-gray-400">
                    {analytics?.summary?.not_found_count || 0} missing doc answers
                  </span>
                </div>
              </div>

              <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 p-4 rounded-2xl shadow-sm">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-gray-500 dark:text-gray-400">Average Latency</span>
                  <div className="p-2 bg-purple-50 dark:bg-purple-950/60 text-purple-600 rounded-xl">
                    <Clock className="w-4 h-4" />
                  </div>
                </div>
                <div className="mt-3">
                  <div className="text-2xl font-bold text-gray-900 dark:text-white">
                    {analytics?.summary?.avg_latency_ms
                      ? `${(analytics.summary.avg_latency_ms / 1000).toFixed(2)}s`
                      : '0.00s'}
                  </div>
                  <span className="text-[11px] text-gray-400">
                    {analytics?.summary?.avg_latency_ms
                      ? `${Math.round(analytics.summary.avg_latency_ms)} ms average`
                      : 'No latency recorded yet'}
                  </span>
                </div>
              </div>
            </div>

            {/* 2. 14-Day Daily Message Count Chart */}
            <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-2xl p-5 shadow-sm">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h3 className="text-sm font-bold text-gray-900 dark:text-white flex items-center gap-2">
                    <BarChart2 className="w-4 h-4 text-emerald-500" />
                    Daily Message Volume (Last 14 Days)
                  </h3>
                  <p className="text-xs text-gray-400 mt-0.5">Total conversation activity per day</p>
                </div>
                <span className="text-xs font-semibold text-gray-500 dark:text-zinc-400">
                  Total: {analytics?.daily_messages?.reduce((acc, d) => acc + d.count, 0) || 0} msgs
                </span>
              </div>

              {/* Bar Chart Container */}
              <div className="h-44 w-full flex items-end gap-2 sm:gap-3 pt-6 pb-2 border-b border-gray-100 dark:border-zinc-800">
                {(() => {
                  const items = analytics?.daily_messages || [];
                  const maxCount = Math.max(...items.map((d) => d.count), 1);
                  return items.map((item, idx) => {
                    const heightPct = Math.max((item.count / maxCount) * 100, item.count > 0 ? 8 : 2);
                    return (
                      <div key={idx} className="flex-1 flex flex-col items-center h-full justify-end group relative">
                        {/* Hover Tooltip */}
                        <div className="absolute -top-7 opacity-0 group-hover:opacity-100 transition-opacity bg-zinc-900 text-white text-[10px] py-0.5 px-1.5 rounded pointer-events-none whitespace-nowrap shadow z-10">
                          {item.count} msgs ({item.date})
                        </div>
                        {/* Bar */}
                        <div
                          style={{ height: `${heightPct}%` }}
                          className={`w-full rounded-t-md transition-all duration-300 ${
                            item.count > 0
                              ? 'bg-emerald-500 group-hover:bg-emerald-400 dark:bg-emerald-600 dark:group-hover:bg-emerald-500'
                              : 'bg-gray-100 dark:bg-zinc-800'
                          }`}
                        />
                      </div>
                    );
                  });
                })()}
              </div>

              {/* Date Labels */}
              <div className="flex justify-between gap-1 mt-2 text-[10px] text-gray-400 dark:text-zinc-500 font-mono">
                {analytics?.daily_messages?.map((item, idx) => (
                  <span key={idx} className="flex-1 text-center truncate">
                    {item.date}
                  </span>
                ))}
              </div>
            </div>

            {/* 3. Two Columns: Top 10 Questions & Missing Documents Questions */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Top 10 Questions */}
              <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-2xl shadow-sm overflow-hidden flex flex-col">
                <div className="p-4 border-b border-gray-200 dark:border-zinc-800">
                  <h3 className="text-sm font-bold text-gray-900 dark:text-white flex items-center gap-2">
                    <Activity className="w-4 h-4 text-emerald-500" />
                    Top 10 Questions Asked
                  </h3>
                  <p className="text-xs text-gray-400 mt-0.5">Most common questions submitted by employees</p>
                </div>
                <div className="flex-1 overflow-y-auto divide-y divide-gray-100 dark:divide-zinc-800">
                  {(!analytics?.top_questions || analytics.top_questions.length === 0) ? (
                    <div className="p-6 text-center text-xs text-gray-400">
                      No question logs recorded yet.
                    </div>
                  ) : (
                    analytics.top_questions.map((q, idx) => (
                      <div key={idx} className="p-3.5 flex items-start justify-between gap-3 hover:bg-gray-50/60 dark:hover:bg-zinc-800/40 transition">
                        <div className="flex items-start gap-2.5">
                          <span className="w-5 h-5 rounded-full bg-gray-100 dark:bg-zinc-800 text-[10px] font-bold text-gray-600 dark:text-zinc-400 flex items-center justify-center flex-shrink-0 mt-0.5">
                            {idx + 1}
                          </span>
                          <span className="text-xs text-gray-800 dark:text-zinc-200 font-medium">
                            {q.question}
                          </span>
                        </div>
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 flex-shrink-0 border border-emerald-200 dark:border-emerald-900">
                          {q.count} {q.count === 1 ? 'time' : 'times'}
                        </span>
                      </div>
                    ))
                  )}
                </div>
              </div>

              {/* Missing Documents Questions */}
              <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-2xl shadow-sm overflow-hidden flex flex-col">
                <div className="p-4 border-b border-gray-200 dark:border-zinc-800">
                  <h3 className="text-sm font-bold text-gray-900 dark:text-white flex items-center gap-2">
                    <HelpCircle className="w-4 h-4 text-amber-500" />
                    Unanswered Questions (Missing Knowledge)
                  </h3>
                  <p className="text-xs text-gray-400 mt-0.5">Answered with "I couldn't find that in the documents"</p>
                </div>
                <div className="flex-1 overflow-y-auto divide-y divide-gray-100 dark:divide-zinc-800">
                  {(!analytics?.missing_docs_questions || analytics.missing_docs_questions.length === 0) ? (
                    <div className="p-6 text-center text-xs text-gray-400">
                      Great job! No queries have failed knowledge lookup.
                    </div>
                  ) : (
                    analytics.missing_docs_questions.map((item, idx) => (
                      <div key={idx} className="p-3.5 flex items-start justify-between gap-3 hover:bg-gray-50/60 dark:hover:bg-zinc-800/40 transition">
                        <div className="space-y-1">
                          <p className="text-xs font-semibold text-gray-800 dark:text-zinc-200">
                            {item.question}
                          </p>
                          <p className="text-[10px] text-amber-600 dark:text-amber-400">
                            Missing document topic — consider uploading relevant policy/guide.
                          </p>
                        </div>
                        <span className="text-[10px] text-gray-400 font-mono flex-shrink-0">
                          {item.created_at ? new Date(item.created_at).toLocaleDateString() : ''}
                        </span>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>

            {/* 4. Thumbs-Down Answers Feedback List */}
            <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-2xl shadow-sm overflow-hidden">
              <div className="p-4 border-b border-gray-200 dark:border-zinc-800">
                <h3 className="text-sm font-bold text-gray-900 dark:text-white flex items-center gap-2">
                  <ThumbsDown className="w-4 h-4 text-rose-500" />
                  User Dislikes & Feedback Comments
                </h3>
                <p className="text-xs text-gray-400 mt-0.5">Auditing answers flagged with thumbs down and user comments</p>
              </div>

              {(!analytics?.thumbs_down_list || analytics.thumbs_down_list.length === 0) ? (
                <div className="p-8 text-center text-xs text-gray-400">
                  No thumbs-down feedback submitted yet.
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs text-gray-600 dark:text-zinc-300">
                    <thead className="bg-gray-50 dark:bg-zinc-800/60 uppercase font-semibold text-[10px] text-gray-400 dark:text-zinc-400">
                      <tr>
                        <th className="py-3 px-4">User</th>
                        <th className="py-3 px-4">User Question</th>
                        <th className="py-3 px-4">Assistant Answer</th>
                        <th className="py-3 px-4">User Comment</th>
                        <th className="py-3 px-4">Date</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100 dark:divide-zinc-800">
                      {analytics.thumbs_down_list.map((fb, idx) => (
                        <tr key={idx} className="hover:bg-gray-50/60 dark:hover:bg-zinc-800/40 align-top">
                          <td className="py-3 px-4 font-medium text-gray-900 dark:text-white whitespace-nowrap">
                            {fb.user_email}
                          </td>
                          <td className="py-3 px-4 max-w-xs font-semibold text-gray-800 dark:text-zinc-200">
                            {fb.question}
                          </td>
                          <td className="py-3 px-4 max-w-md text-gray-600 dark:text-zinc-400 line-clamp-3">
                            {fb.answer}
                          </td>
                          <td className="py-3 px-4 max-w-xs">
                            {fb.comment ? (
                              <span className="p-1.5 rounded-lg bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300 border border-rose-200 dark:border-rose-900 text-[11px] block">
                                "{fb.comment}"
                              </span>
                            ) : (
                              <span className="text-gray-400 text-[11px] italic">No comment provided</span>
                            )}
                          </td>
                          <td className="py-3 px-4 text-gray-400 whitespace-nowrap font-mono text-[11px]">
                            {fb.created_at ? new Date(fb.created_at).toLocaleString() : ''}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Diagnostics Tab */}
        {activeTab === 'diagnostics' && (
          <ErrorBoundary title="Failed to load diagnostics">
            <div className="space-y-6">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="bg-white dark:bg-zinc-900 p-5 rounded-2xl border border-gray-200 dark:border-zinc-800 shadow-sm">
                  <span className="text-xs font-semibold uppercase tracking-wider text-gray-400">Build Version</span>
                  <div className="text-2xl font-bold text-gray-900 dark:text-white mt-2">
                    v{diagnostics?.build_version || '1.0.0'}
                  </div>
                  <div className="text-xs text-gray-400 mt-1">
                    Server time: {diagnostics?.server_time ? new Date(diagnostics.server_time).toLocaleString() : 'N/A'}
                  </div>
                </div>

                <div className="bg-white dark:bg-zinc-900 p-5 rounded-2xl border border-gray-200 dark:border-zinc-800 shadow-sm">
                  <span className="text-xs font-semibold uppercase tracking-wider text-gray-400">System Memory</span>
                  <div className="text-2xl font-bold text-gray-900 dark:text-white mt-2">
                    {diagnostics?.memory?.percent ?? 0}%
                  </div>
                  <div className="text-xs text-gray-400 mt-1">
                    Used: {diagnostics?.memory?.used_mb ?? 0} MB / {diagnostics?.memory?.total_mb ?? 0} MB
                  </div>
                </div>

                <div className="bg-white dark:bg-zinc-900 p-5 rounded-2xl border border-gray-200 dark:border-zinc-800 shadow-sm">
                  <span className="text-xs font-semibold uppercase tracking-wider text-gray-400">Active Streams & DB Repairs</span>
                  <div className="text-2xl font-bold text-gray-900 dark:text-white mt-2">
                    {diagnostics?.active_streams ?? 0} active
                  </div>
                  <div className="text-xs text-gray-400 mt-1">
                    Normalized records: {diagnostics?.rows_normalized_count ?? 0}
                  </div>
                </div>
              </div>

              {/* Database Counts */}
              <div className="bg-white dark:bg-zinc-900 p-5 rounded-2xl border border-gray-200 dark:border-zinc-800 shadow-sm">
                <h3 className="text-sm font-bold text-gray-900 dark:text-white mb-3">Database Statistics</h3>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-center">
                  <div className="p-3 bg-gray-50 dark:bg-zinc-800/50 rounded-xl">
                    <span className="text-xs text-gray-400">Users</span>
                    <div className="text-xl font-bold text-gray-900 dark:text-white mt-1">{diagnostics?.counts?.users ?? 0}</div>
                  </div>
                  <div className="p-3 bg-gray-50 dark:bg-zinc-800/50 rounded-xl">
                    <span className="text-xs text-gray-400">Documents</span>
                    <div className="text-xl font-bold text-gray-900 dark:text-white mt-1">{diagnostics?.counts?.documents ?? 0}</div>
                  </div>
                  <div className="p-3 bg-gray-50 dark:bg-zinc-800/50 rounded-xl">
                    <span className="text-xs text-gray-400">Conversations</span>
                    <div className="text-xl font-bold text-gray-900 dark:text-white mt-1">{diagnostics?.counts?.conversations ?? 0}</div>
                  </div>
                  <div className="p-3 bg-gray-50 dark:bg-zinc-800/50 rounded-xl">
                    <span className="text-xs text-gray-400">Messages</span>
                    <div className="text-xl font-bold text-gray-900 dark:text-white mt-1">{diagnostics?.counts?.messages ?? 0}</div>
                  </div>
                </div>
              </div>

              {/* Recent Error Logs */}
              <div className="bg-white dark:bg-zinc-900 p-5 rounded-2xl border border-gray-200 dark:border-zinc-800 shadow-sm">
                <h3 className="text-sm font-bold text-gray-900 dark:text-white mb-2 flex items-center gap-2">
                  <Terminal className="w-4 h-4 text-amber-500" />
                  Recent Errors & Warnings (Sanitized)
                </h3>
                <div className="bg-zinc-950 text-zinc-200 font-mono text-xs p-4 rounded-xl max-h-64 overflow-y-auto space-y-1">
                  {diagnostics?.error_logs && diagnostics.error_logs.length > 0 ? (
                    diagnostics.error_logs.map((log, idx) => (
                      <div key={idx} className="whitespace-pre-wrap break-all text-amber-300/90 font-mono text-[11px] leading-tight">
                        {log}
                      </div>
                    ))
                  ) : (
                    <div className="text-zinc-500 italic">No recent error or warning logs recorded.</div>
                  )}
                </div>
              </div>
            </div>
          </ErrorBoundary>
        )}
      </div>
    </div>
  );
}
