import React, { useState, useEffect } from 'react';
import {
  X,
  MessageSquare,
  Send,
  HelpCircle,
  FileCheck,
  AlertTriangle,
  Lightbulb,
  CheckCircle,
  Clock,
  ChevronLeft,
} from 'lucide-react';
import {
  apiCreateSupportRequest,
  apiGetMySupportRequests,
  apiGetSupportRequest,
  apiReplySupportRequest,
  apiUpdateSupportStatus,
  formatError,
} from '../api';

export default function ContactAdminModal({
  isOpen,
  onClose,
  initialQuestion = '',
  conversationId = null,
  onToast = null,
}) {
  const [activeTab, setActiveTab] = useState(initialQuestion ? 'new' : 'my_requests');
  const [reqType, setReqType] = useState('question');
  const [subject, setSubject] = useState(initialQuestion ? `Question: ${initialQuestion.slice(0, 40)}...` : '');
  const [message, setMessage] = useState(initialQuestion || '');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // My requests list
  const [myRequests, setMyRequests] = useState([]);
  const [loadingRequests, setLoadingRequests] = useState(false);
  const [selectedRequest, setSelectedRequest] = useState(null);
  const [replyBody, setReplyBody] = useState('');
  const [replying, setReplying] = useState(false);

  useEffect(() => {
    if (initialQuestion) {
      setActiveTab('new');
      setSubject(`Question regarding document info`);
      setMessage(initialQuestion);
    }
  }, [initialQuestion]);

  useEffect(() => {
    if (isOpen) {
      loadMyRequests();
    }
  }, [isOpen]);

  const loadMyRequests = async () => {
    setLoadingRequests(true);
    try {
      const data = await apiGetMySupportRequests();
      setMyRequests(data || []);
    } catch (err) {
      console.error('Failed to load support requests:', err);
    } finally {
      setLoadingRequests(false);
    }
  };

  const handleSelectRequest = async (reqId) => {
    try {
      const full = await apiGetSupportRequest(reqId);
      setSelectedRequest(full);
    } catch (err) {
      console.error('Failed to load thread:', err);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!subject.trim() || !message.trim()) return;
    setLoading(true);
    setError('');
    try {
      await apiCreateSupportRequest({
        type: reqType,
        subject: subject.trim(),
        message: message.trim(),
        related_conversation_id: conversationId,
      });
      if (onToast) onToast('Support request submitted to admin', 'success');
      setSubject('');
      setMessage('');
      await loadMyRequests();
      setActiveTab('my_requests');
    } catch (err) {
      setError(formatError(err));
    } finally {
      setLoading(false);
    }
  };

  const handleSendReply = async (e) => {
    e.preventDefault();
    if (!replyBody.trim() || !selectedRequest) return;
    setReplying(true);
    try {
      const updated = await apiReplySupportRequest(selectedRequest.id, replyBody.trim());
      setSelectedRequest(updated);
      setReplyBody('');
      await loadMyRequests();
    } catch (err) {
      alert(`Reply failed: ${formatError(err)}`);
    } finally {
      setReplying(false);
    }
  };

  const handleCloseTicket = async () => {
    if (!selectedRequest) return;
    try {
      const updated = await apiUpdateSupportStatus(selectedRequest.id, 'closed');
      setSelectedRequest(updated);
      await loadMyRequests();
      if (onToast) onToast('Request closed', 'info');
    } catch (err) {
      alert(`Update failed: ${formatError(err)}`);
    }
  };

  if (!isOpen) return null;

  const getStatusBadge = (status) => {
    switch (status) {
      case 'open':
        return <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-100 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300">Open</span>;
      case 'in_progress':
        return <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-blue-100 dark:bg-blue-950/60 text-blue-700 dark:text-blue-300">In Progress</span>;
      case 'resolved':
        return <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-purple-100 dark:bg-purple-950/60 text-purple-700 dark:text-purple-300">Resolved</span>;
      default:
        return <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-gray-100 dark:bg-zinc-800 text-gray-600 dark:text-zinc-400">Closed</span>;
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs">
      <div className="w-full max-w-xl bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl border border-gray-200 dark:border-zinc-800 flex flex-col max-h-[85vh] overflow-hidden animate-in fade-in zoom-in-95 duration-200">
        {/* Header */}
        <div className="p-4 border-b border-gray-100 dark:border-zinc-800 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-xl bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 flex items-center justify-center">
              <MessageSquare className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-bold text-gray-900 dark:text-white leading-none">
                {selectedRequest ? 'Request Conversation' : 'Contact Administrator'}
              </h3>
              <p className="text-xs text-gray-500 dark:text-zinc-400 mt-1">
                {selectedRequest ? `ID #${selectedRequest.id} - ${selectedRequest.subject}` : 'Submit questions, document requests, or report issues'}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-zinc-300 hover:bg-gray-100 dark:hover:bg-zinc-800"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Tab selection (if not inspecting thread) */}
        {!selectedRequest && (
          <div className="flex border-b border-gray-100 dark:border-zinc-800 px-4 pt-2">
            <button
              type="button"
              onClick={() => setActiveTab('new')}
              className={`pb-2.5 px-3 text-xs font-semibold border-b-2 transition ${
                activeTab === 'new'
                  ? 'border-emerald-500 text-emerald-600 dark:text-emerald-400'
                  : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-zinc-300'
              }`}
            >
              New Request
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('my_requests')}
              className={`pb-2.5 px-3 text-xs font-semibold border-b-2 transition flex items-center gap-1.5 ${
                activeTab === 'my_requests'
                  ? 'border-emerald-500 text-emerald-600 dark:text-emerald-400'
                  : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-zinc-300'
              }`}
            >
              My Requests
              {myRequests.length > 0 && (
                <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-gray-100 dark:bg-zinc-800 font-bold">
                  {myRequests.length}
                </span>
              )}
            </button>
          </div>
        )}

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-4 scrollbar-thin">
          {selectedRequest ? (
            /* Thread View */
            <div className="flex flex-col h-full space-y-4">
              <div className="flex items-center justify-between pb-3 border-b border-gray-100 dark:border-zinc-800">
                <button
                  type="button"
                  onClick={() => setSelectedRequest(null)}
                  className="flex items-center gap-1 text-xs font-medium text-gray-500 hover:text-gray-800 dark:hover:text-white"
                >
                  <ChevronLeft className="w-4 h-4" />
                  Back to requests
                </button>
                <div className="flex items-center gap-2">
                  {getStatusBadge(selectedRequest.status)}
                  {selectedRequest.status !== 'closed' && (
                    <button
                      type="button"
                      onClick={handleCloseTicket}
                      className="text-xs px-2.5 py-1 rounded-lg border border-gray-300 dark:border-zinc-700 text-gray-600 dark:text-zinc-300 hover:bg-gray-100 dark:hover:bg-zinc-800"
                    >
                      Close request
                    </button>
                  )}
                </div>
              </div>

              {/* Messages list */}
              <div className="space-y-3 flex-1 overflow-y-auto pr-1">
                {/* Initial request */}
                <div className="p-3.5 rounded-xl bg-gray-50 dark:bg-zinc-800/60 border border-gray-200/60 dark:border-zinc-700/60">
                  <div className="flex items-center justify-between text-xs font-semibold text-gray-700 dark:text-zinc-300 mb-1">
                    <span>Original Request</span>
                    <span className="text-[10px] font-normal text-gray-400">
                      {new Date(selectedRequest.created_at).toLocaleString()}
                    </span>
                  </div>
                  <p className="text-xs text-gray-800 dark:text-zinc-200 whitespace-pre-wrap">
                    {selectedRequest.message}
                  </p>
                </div>

                {/* Replies */}
                {(selectedRequest.messages || []).map((msg) => {
                  const isAdmin = msg.sender_role === 'admin';
                  return (
                    <div
                      key={msg.id}
                      className={`p-3.5 rounded-xl border ${
                        isAdmin
                          ? 'bg-purple-50/70 dark:bg-purple-950/30 border-purple-200 dark:border-purple-900/50 ml-4'
                          : 'bg-white dark:bg-zinc-800 border-gray-200 dark:border-zinc-700 mr-4'
                      }`}
                    >
                      <div className="flex items-center justify-between text-xs font-semibold mb-1">
                        <span className={isAdmin ? 'text-purple-700 dark:text-purple-300' : 'text-gray-700 dark:text-zinc-300'}>
                          {isAdmin ? 'Administrator' : 'You'}
                        </span>
                        <span className="text-[10px] font-normal text-gray-400">
                          {new Date(msg.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                        </span>
                      </div>
                      <p className="text-xs text-gray-800 dark:text-zinc-200 whitespace-pre-wrap">
                        {msg.body}
                      </p>
                    </div>
                  );
                })}
              </div>

              {/* Reply box */}
              {selectedRequest.status !== 'closed' ? (
                <form onSubmit={handleSendReply} className="pt-2 flex gap-2">
                  <input
                    type="text"
                    required
                    value={replyBody}
                    onChange={(e) => setReplyBody(e.target.value)}
                    placeholder="Type your reply to admin..."
                    className="flex-1 px-3 py-2 text-xs bg-gray-50 dark:bg-zinc-800 border border-gray-200 dark:border-zinc-700 rounded-xl focus:outline-none focus:ring-2 focus:ring-emerald-500 text-gray-900 dark:text-white"
                  />
                  <button
                    type="submit"
                    disabled={replying || !replyBody.trim()}
                    className="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-xs font-semibold flex items-center gap-1.5 transition disabled:opacity-50"
                  >
                    <Send className="w-3.5 h-3.5" />
                    Reply
                  </button>
                </form>
              ) : (
                <p className="text-center text-xs text-gray-400 italic py-2">
                  This request has been closed.
                </p>
              )}
            </div>
          ) : activeTab === 'new' ? (
            /* New Request Form */
            <form onSubmit={handleSubmit} className="space-y-4">
              {error && (
                <div className="p-3 text-xs rounded-xl bg-red-50 dark:bg-red-950/50 text-red-600 dark:text-red-400 border border-red-200 dark:border-red-900">
                  {error}
                </div>
              )}

              <div>
                <label className="block text-xs font-semibold text-gray-700 dark:text-zinc-300 uppercase tracking-wider mb-1.5">
                  Request Type
                </label>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  {[
                    { id: 'question', label: 'Question', icon: HelpCircle },
                    { id: 'document_access', label: 'Doc Access', icon: FileCheck },
                    { id: 'issue', label: 'Issue', icon: AlertTriangle },
                    { id: 'feature', label: 'Feature', icon: Lightbulb },
                  ].map((t) => {
                    const Icon = t.icon;
                    return (
                      <button
                        key={t.id}
                        type="button"
                        onClick={() => setReqType(t.id)}
                        className={`p-2.5 rounded-xl border text-xs font-medium flex flex-col items-center gap-1.5 transition ${
                          reqType === t.id
                            ? 'bg-emerald-50 dark:bg-emerald-950/50 border-emerald-500 text-emerald-700 dark:text-emerald-300'
                            : 'border-gray-200 dark:border-zinc-700 text-gray-600 dark:text-zinc-400 hover:bg-gray-50 dark:hover:bg-zinc-800'
                        }`}
                      >
                        <Icon className="w-4 h-4" />
                        {t.label}
                      </button>
                    );
                  })}
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-gray-700 dark:text-zinc-300 uppercase tracking-wider mb-1">
                  Subject
                </label>
                <input
                  type="text"
                  required
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                  placeholder="Summary of what you need..."
                  className="w-full px-3.5 py-2.5 text-xs bg-gray-50 dark:bg-zinc-800 border border-gray-200 dark:border-zinc-700 rounded-xl focus:outline-none focus:ring-2 focus:ring-emerald-500 text-gray-900 dark:text-white"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-gray-700 dark:text-zinc-300 uppercase tracking-wider mb-1">
                  Message Details
                </label>
                <textarea
                  required
                  rows={5}
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  placeholder="Describe your question or issue in detail..."
                  className="w-full px-3.5 py-2.5 text-xs bg-gray-50 dark:bg-zinc-800 border border-gray-200 dark:border-zinc-700 rounded-xl focus:outline-none focus:ring-2 focus:ring-emerald-500 text-gray-900 dark:text-white resize-none"
                />
              </div>

              <div className="pt-2 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={onClose}
                  className="px-4 py-2 text-xs font-medium text-gray-600 dark:text-zinc-400 hover:bg-gray-100 dark:hover:bg-zinc-800 rounded-xl transition"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={loading || !subject.trim() || !message.trim()}
                  className="px-5 py-2 text-xs font-semibold bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl shadow-sm transition disabled:opacity-50 flex items-center gap-1.5"
                >
                  {loading && <span className="animate-spin rounded-full h-3 w-3 border-2 border-white border-t-transparent" />}
                  Submit Request
                </button>
              </div>
            </form>
          ) : (
            /* My Requests List */
            <div className="space-y-2">
              {loadingRequests ? (
                <div className="py-12 text-center text-xs text-gray-400">Loading your requests...</div>
              ) : myRequests.length === 0 ? (
                <div className="py-12 text-center text-xs text-gray-400 dark:text-zinc-500">
                  You have not submitted any requests yet.
                </div>
              ) : (
                myRequests.map((req) => (
                  <div
                    key={req.id}
                    onClick={() => handleSelectRequest(req.id)}
                    className="p-3.5 rounded-xl border border-gray-200/80 dark:border-zinc-800 hover:bg-gray-50 dark:hover:bg-zinc-800/50 cursor-pointer transition flex items-center justify-between"
                  >
                    <div>
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-xs font-semibold text-gray-900 dark:text-white">
                          {req.subject}
                        </span>
                        {getStatusBadge(req.status)}
                      </div>
                      <p className="text-[11px] text-gray-500 dark:text-zinc-400 line-clamp-1">
                        {req.message}
                      </p>
                      <span className="text-[10px] text-gray-400 dark:text-zinc-500 mt-1 block">
                        {new Date(req.created_at).toLocaleDateString()}
                      </span>
                    </div>
                    <span className="text-xs text-emerald-600 dark:text-emerald-400 font-medium">
                      View Thread &rarr;
                    </span>
                  </div>
                ))
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
