import React, { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  Send,
  Paperclip,
  Square,
  Sparkles,
  FileText,
  X,
  ExternalLink,
  CheckCircle,
  Clock,
  AlertCircle,
  Image as ImageIcon,
  ImageOff,
  Maximize2,
  ThumbsUp,
  ThumbsDown,
  Menu,
} from 'lucide-react';
import {
  apiStreamChatMessage,
  apiUploadDocument,
  apiGetDocumentStatus,
  apiUpdateFilter,
  apiRemoveAttachment,
  apiClearAllAttachments,
  apiCreateConversation,
  apiSubmitFeedback,
  getAuthToken,
} from '../api';

export default function ChatArea({
  conversation,
  isLoadingConversation,
  onRefreshConversation,
  onConversationDone,
  onConversationCreated,
  currentUser,
  onToggleMobileSidebar = null,
}) {
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [statusText, setStatusText] = useState('');
  const [activeDocFilter, setActiveDocFilter] = useState(null);
  const [attachedDocs, setAttachedDocs] = useState([]);

  // Feedback and Comments
  const [openCommentBoxId, setOpenCommentBoxId] = useState(null);
  const [commentInputs, setCommentInputs] = useState({});

  // Toast Notifications
  const [toasts, setToasts] = useState([]);
  const addToast = (message, type = 'info', duration = 4000) => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, message, type }]);
    if (duration > 0) {
      setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
      }, duration);
    }
  };

  // Upload state
  const [uploadStatus, setUploadStatus] = useState(null);
  const fileInputRef = useRef(null);

  // Excerpt Modal
  const [selectedSource, setSelectedSource] = useState(null);
  // Image Lightbox Modal
  const [lightboxImage, setLightboxImage] = useState(null);

  const buildImageUrl = (url) => {
    if (!url) return '';
    return url;
  };

  const abortControllerRef = useRef(null);
  const messagesEndRef = useRef(null);
  const scrollContainerRef = useRef(null);
  const prevConvIdRef = useRef(conversation?.id || null);

  // Sync state when conversation changes
  useEffect(() => {
    if (conversation) {
      // Rule 4: If conversation transitioned from null to newly created id, DO NOT wipe messages!
      if (prevConvIdRef.current === null && conversation.id) {
        prevConvIdRef.current = conversation.id;
        return;
      }
      if (prevConvIdRef.current !== conversation.id) {
        prevConvIdRef.current = conversation.id;
        setMessages(conversation.messages || []);
        setStatusText('');
        if (conversation.attached_documents && conversation.attached_documents.length > 0) {
          setAttachedDocs(conversation.attached_documents);
          setActiveDocFilter({
            id: conversation.attached_documents[conversation.attached_documents.length - 1].id,
            name: conversation.attached_documents[conversation.attached_documents.length - 1].filename,
          });
        } else if (conversation.active_doc_id) {
          setAttachedDocs([
            { id: conversation.active_doc_id, filename: conversation.active_doc_name || 'Attached Document' },
          ]);
          setActiveDocFilter({
            id: conversation.active_doc_id,
            name: conversation.active_doc_name || 'Attached Document',
          });
        } else {
          setAttachedDocs([]);
          setActiveDocFilter(null);
        }
      }
    } else {
      // Rule 4: activeConversation is null -> immediately clear messages, filter, input and scroll to top
      prevConvIdRef.current = null;
      setMessages([]);
      setActiveDocFilter(null);
      setAttachedDocs([]);
      setInputValue('');
      setStatusText('');
      if (scrollContainerRef.current) {
        scrollContainerRef.current.scrollTop = 0;
      }
    }
  }, [conversation]);

  // Scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isStreaming, statusText]);

  // Scroll to bottom after loading conversation finishes
  useEffect(() => {
    if (!isLoadingConversation && messages.length > 0) {
      const timer = setTimeout(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
      }, 50);
      return () => clearTimeout(timer);
    }
  }, [isLoadingConversation]);

  // Handle Feedback
  const handleRating = async (messageId, currentRating, targetRating) => {
    // One rating per user per message (a second click updates it, a click on the same rating removes it)
    const newRating = currentRating === targetRating ? null : targetRating;

    setMessages((prev) =>
      prev.map((m) =>
        m.id === messageId
          ? {
              ...m,
              feedback: newRating
                ? { ...(m.feedback || {}), rating: newRating }
                : null,
            }
          : m
      )
    );

    if (newRating === 'down') {
      setOpenCommentBoxId(messageId);
      setCommentInputs((prev) => ({ ...prev, [messageId]: '' }));
    } else {
      setOpenCommentBoxId(null);
    }

    try {
      await apiSubmitFeedback(
        messageId,
        newRating,
        newRating ? (commentInputs[messageId] || null) : null
      );
    } catch (err) {
      console.error('Failed to submit feedback:', err);
      addToast(`Feedback failed: ${err.message}`, 'error');
    }
  };

  const handleCommentSubmit = async (messageId) => {
    const comment = (commentInputs[messageId] || '').trim();
    setOpenCommentBoxId(null);
    setMessages((prev) =>
      prev.map((m) =>
        m.id === messageId
          ? {
              ...m,
              feedback: { ...(m.feedback || { rating: 'down' }), comment },
            }
          : m
      )
    );
    try {
      await apiSubmitFeedback(messageId, 'down', comment);
      addToast('Feedback saved. Thank you!', 'success', 3000);
    } catch (err) {
      console.error('Failed to submit comment:', err);
      addToast(`Failed to submit comment: ${err.message}`, 'error');
    }
  };

  // Handle Remove Single Attachment
  const handleRemoveAttachment = async (docId) => {
    if (!conversation?.id) {
      setAttachedDocs((prev) => prev.filter((d) => d.id !== docId));
      return;
    }
    try {
      await apiRemoveAttachment(conversation.id, docId);
      setAttachedDocs((prev) => {
        const remaining = prev.filter((d) => d.id !== docId);
        if (remaining.length === 0) {
          setActiveDocFilter(null);
        } else {
          setActiveDocFilter({
            id: remaining[remaining.length - 1].id,
            name: remaining[remaining.length - 1].filename,
          });
        }
        return remaining;
      });
      if (onRefreshConversation) onRefreshConversation();
    } catch (err) {
      console.error('Failed to remove attachment:', err);
    }
  };

  // Handle Clear All Attachments
  const handleClearAllAttachments = async () => {
    if (!conversation?.id) {
      setAttachedDocs([]);
      setActiveDocFilter(null);
      return;
    }
    try {
      await apiClearAllAttachments(conversation.id);
      setAttachedDocs([]);
      setActiveDocFilter(null);
      if (onRefreshConversation) onRefreshConversation();
    } catch (err) {
      console.error('Failed to clear attachments:', err);
    }
  };

  // Handle Remove Filter
  const handleRemoveFilter = async () => {
    await handleClearAllAttachments();
  };

  // Handle File Upload
  const handleFileUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploadStatus({ filename: file.name, state: 'uploading', progress: 0 });
    addToast(`Uploading "${file.name}"...`, 'info', 3000);

    try {
      let targetConv = conversation;
      if (!targetConv || !targetConv.id) {
        targetConv = await apiCreateConversation('Document Chat');
        if (onConversationCreated) onConversationCreated(targetConv);
      }

      const doc = await apiUploadDocument(file, targetConv.id, (percent) => {
        setUploadStatus((prev) => (prev ? { ...prev, progress: percent } : { filename: file.name, state: 'uploading', progress: percent }));
      });
      setUploadStatus({ filename: file.name, state: 'processing', progress: 100 });
      addToast(`Processing and indexing "${file.name}"...`, 'info', 4000);

      // Poll status until ready
      const checkInterval = setInterval(async () => {
        try {
          const statusRes = await apiGetDocumentStatus(doc.id);
          if (statusRes.status === 'ready') {
            clearInterval(checkInterval);
            setUploadStatus({ filename: file.name, state: 'ready' });
            addToast(`Document "${file.name}" ready! Added to conversation.`, 'success', 5000);
            setAttachedDocs((prev) => {
              if (prev.some((p) => p.id === doc.id)) return prev;
              return [...prev, { id: doc.id, filename: doc.filename, file_type: doc.file_type }];
            });
            setActiveDocFilter({ id: doc.id, name: doc.filename });
            if (onRefreshConversation) onRefreshConversation();
            setTimeout(() => setUploadStatus(null), 4000);
          } else if (statusRes.status === 'failed') {
            clearInterval(checkInterval);
            setUploadStatus({ filename: file.name, state: 'failed', error: statusRes.error_message });
            addToast(`Processing failed: ${statusRes.error_message || 'Error'}`, 'error', 6000);
          }
        } catch {
          clearInterval(checkInterval);
        }
      }, 1500);
    } catch (err) {
      setUploadStatus({ filename: file.name, state: 'failed', error: err.message });
      addToast(`Upload failed: ${err.message}`, 'error', 6000);
      setTimeout(() => setUploadStatus(null), 6000);
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  // Handle Send Message
  const handleSendMessage = async (e, customText = null, extraPayload = {}) => {
    e?.preventDefault();
    const text = (customText !== null ? customText : inputValue).trim();
    if (!text || isStreaming) return;

    if (customText === null) {
      setInputValue('');
    }

    // Append user message immediately
    const userMsg = {
      id: `usr_${Date.now()}`,
      sender: 'user',
      content: text,
      created_at: new Date().toISOString(),
    };

    // Temporary placeholder assistant message
    const assistantMsgId = `ast_${Date.now()}`;
    const placeholderAssistantMsg = {
      id: assistantMsgId,
      sender: 'assistant',
      content: '',
      sources: [],
      images: [],
      meta: null,
      created_at: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMsg, placeholderAssistantMsg]);
    setIsStreaming(true);
    setStatusText('Thinking...');

    abortControllerRef.current = new AbortController();

    try {
      let targetConv = conversation;
      if (!targetConv || !targetConv.id) {
        targetConv = await apiCreateConversation('New Chat');
        if (onConversationCreated) onConversationCreated(targetConv);
      }

      await apiStreamChatMessage(
        targetConv.id,
        text,
        (token) => {
          setStatusText('');
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsgId
                ? { ...m, content: m.content + token }
                : m
            )
          );
        },
        (sources, images, doneData) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsgId
                ? {
                    ...m,
                    id: doneData?.message_id || m.id,
                    sources: sources || [],
                    images: images || [],
                    meta: doneData?.meta || m.meta,
                    latency_ms: doneData?.latency_ms,
                  }
                : m
            )
          );
          setIsStreaming(false);
          setStatusText('');
          if (onConversationDone) {
            onConversationDone(doneData);
          }
          onRefreshConversation();
        },
        (error) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsgId
                ? { ...m, content: m.content + `\n\n[Error: ${error}]` }
                : m
            )
          );
          setIsStreaming(false);
          setStatusText('');
        },
        (statusMsg) => {
          setStatusText(statusMsg);
        },
        abortControllerRef.current.signal,
        extraPayload
      );
    } catch (err) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantMsgId
            ? { ...m, content: `Error: ${err.message}` }
            : m
        )
      );
      setIsStreaming(false);
      setStatusText('');
    }
  };

  const handleStopStreaming = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      setIsStreaming(false);
      setStatusText('');
    }
  };

  // Open PDF at specific page
  const handleOpenPdfPage = (docId, page) => {
    const url = `/api/documents/${docId}/file#page=${page || 1}`;
    window.open(url, '_blank', 'noopener,noreferrer');
  };

  return (
    <div className="flex-1 flex flex-col h-[100dvh] bg-white dark:bg-zinc-950 overflow-hidden relative">
      {/* Top Header */}
      <header className="h-14 border-b border-gray-200 dark:border-zinc-800 flex items-center justify-between px-3 sm:px-6 bg-white/80 dark:bg-zinc-950/80 backdrop-blur z-10">
        <div className="flex items-center gap-2 sm:gap-3 overflow-hidden">
          {onToggleMobileSidebar && (
            <button
              type="button"
              onClick={onToggleMobileSidebar}
              className="p-2 -ml-1 rounded-lg text-gray-500 hover:text-gray-700 dark:text-zinc-400 dark:hover:text-zinc-200 hover:bg-gray-100 dark:hover:bg-zinc-800 md:hidden"
              aria-label="Open sidebar"
            >
              <Menu className="w-5 h-5" />
            </button>
          )}
          <span className="font-semibold text-sm text-gray-800 dark:text-zinc-200 truncate">
            {conversation?.title || 'New Conversation'}
          </span>

          {/* Active Attachments / Filter Badge */}
          {attachedDocs.length > 0 || (uploadStatus && uploadStatus.state === 'uploading') ? (
            <div className="flex items-center gap-1.5 overflow-x-auto whitespace-nowrap scrollbar-none py-1 max-w-[200px] sm:max-w-xl">
              {uploadStatus && uploadStatus.state === 'uploading' && (
                <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-blue-100 dark:bg-blue-950/60 text-blue-800 dark:text-blue-300 border border-blue-300 dark:border-blue-800 animate-pulse">
                  <Clock className="w-3 h-3 flex-shrink-0 animate-spin text-blue-600 dark:text-blue-400" />
                  <span className="truncate max-w-[130px]">{uploadStatus.filename}</span>
                  <span className="font-bold text-blue-700 dark:text-blue-200">
                    {uploadStatus.progress ?? 0}%
                  </span>
                </div>
              )}
              {attachedDocs.map((d) => (
                <div
                  key={d.id}
                  className="flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-100 dark:bg-emerald-950/60 text-emerald-800 dark:text-emerald-300 border border-emerald-300 dark:border-emerald-800"
                >
                  <FileText className="w-3 h-3 flex-shrink-0" />
                  <span className="truncate max-w-[140px]">{d.filename}</span>
                  <button
                    type="button"
                    onClick={() => handleRemoveAttachment(d.id)}
                    className="hover:bg-emerald-200 dark:hover:bg-emerald-900 rounded-full p-0.5 transition text-emerald-700 dark:text-emerald-300"
                    title={`Remove ${d.filename}`}
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
              ))}
              {attachedDocs.length > 0 && (
                <button
                  type="button"
                  onClick={handleClearAllAttachments}
                  className="text-xs text-gray-500 hover:text-red-600 dark:text-zinc-400 dark:hover:text-red-400 font-medium px-2 py-0.5 underline transition"
                  title="Clear all attachments and return to company scope"
                >
                  Clear all
                </button>
              )}
            </div>
          ) : (
            <span className="text-xs text-gray-400 dark:text-zinc-500 hidden sm:inline">
              Scope: Company Knowledge Base (All Docs)
            </span>
          )}
        </div>
      </header>

      {/* Messages Feed */}
      <div ref={scrollContainerRef} className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-6">
        {isLoadingConversation ? (
          <div className="max-w-3xl mx-auto space-y-6 animate-pulse py-6">
            <div className="flex gap-3 justify-end">
              <div className="w-1/2 h-12 bg-gray-200 dark:bg-zinc-800 rounded-2xl rounded-br-none" />
            </div>
            <div className="flex gap-3 justify-start">
              <div className="w-8 h-8 rounded-xl bg-gray-200 dark:bg-zinc-800 flex-shrink-0" />
              <div className="w-3/4 space-y-2.5">
                <div className="h-4 bg-gray-200 dark:bg-zinc-800 rounded w-full" />
                <div className="h-4 bg-gray-200 dark:bg-zinc-800 rounded w-5/6" />
                <div className="h-4 bg-gray-200 dark:bg-zinc-800 rounded w-2/3" />
              </div>
            </div>
            <div className="flex gap-3 justify-end">
              <div className="w-1/3 h-10 bg-gray-200 dark:bg-zinc-800 rounded-2xl rounded-br-none" />
            </div>
            <div className="flex gap-3 justify-start">
              <div className="w-8 h-8 rounded-xl bg-gray-200 dark:bg-zinc-800 flex-shrink-0" />
              <div className="w-2/3 space-y-2.5">
                <div className="h-4 bg-gray-200 dark:bg-zinc-800 rounded w-full" />
                <div className="h-4 bg-gray-200 dark:bg-zinc-800 rounded w-4/5" />
              </div>
            </div>
          </div>
        ) : messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center p-8 max-w-lg mx-auto">
            <div className="w-12 h-12 rounded-2xl bg-emerald-100 dark:bg-emerald-950/60 flex items-center justify-center text-emerald-600 dark:text-emerald-400 mb-4 shadow-sm">
              <Sparkles className="w-6 h-6" />
            </div>
            <h3 className="text-lg font-bold text-gray-900 dark:text-white mb-2">
              How can I help you today?
            </h3>
            <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed mb-6">
              I can answer questions about the company documents you have access to.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 w-full text-xs">
              {[
                'Show me the executive organizational chart',
                'What is the remote work and attendance policy?',
                'Summarize our conversation so far',
                'What documents are available?',
              ].map((suggestion, i) => (
                <button
                  key={i}
                  type="button"
                  onClick={() => setInputValue(suggestion)}
                  className="p-3 text-left rounded-xl border border-gray-200 dark:border-zinc-800 bg-gray-50/50 dark:bg-zinc-900/50 hover:bg-gray-100 dark:hover:bg-zinc-800 text-gray-700 dark:text-zinc-300 transition"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((msg, idx) => {
            const isLastAssistant = msg.sender === 'assistant' && idx === messages.length - 1;
            return (
              <div
                key={msg.id}
                className={`flex gap-3 max-w-3xl mx-auto ${
                  msg.sender === 'user' ? 'justify-end' : 'justify-start'
                }`}
              >
                {msg.sender === 'assistant' && (
                  <div className="w-8 h-8 rounded-xl bg-emerald-600 text-white flex items-center justify-center flex-shrink-0 shadow-sm mt-0.5">
                    <Sparkles className="w-4 h-4" />
                  </div>
                )}

                <div className="max-w-[85%] space-y-3">
                  <div
                    className={`p-4 rounded-2xl text-sm leading-relaxed ${
                      msg.sender === 'user'
                        ? 'bg-emerald-600 text-white rounded-br-none shadow-sm'
                        : 'bg-gray-100/80 dark:bg-zinc-900 border border-gray-200/80 dark:border-zinc-800 text-gray-800 dark:text-zinc-200 rounded-bl-none'
                    }`}
                  >
                    {/* Render User Plaintext or Assistant Markdown */}
                    {msg.sender === 'user' ? (
                      <div className="whitespace-pre-wrap">{msg.content}</div>
                    ) : (
                      <div className="text-sm leading-relaxed text-gray-800 dark:text-zinc-200">
                        {msg.content ? (
                          <ReactMarkdown
                            remarkPlugins={[remarkGfm]}
                            components={{
                              p: ({ node, ...props }) => <p className="mb-2.5 last:mb-0 leading-relaxed" {...props} />,
                              ul: ({ node, ...props }) => <ul className="list-disc pl-5 mb-2.5 space-y-1" {...props} />,
                              ol: ({ node, ...props }) => <ol className="list-decimal pl-5 mb-2.5 space-y-1" {...props} />,
                              li: ({ node, ...props }) => <li className="pl-1" {...props} />,
                              table: ({ node, ...props }) => (
                                <div className="overflow-x-auto my-3 rounded-lg border border-gray-200 dark:border-zinc-800">
                                  <table className="min-w-full divide-y divide-gray-200 dark:divide-zinc-800 text-xs text-left" {...props} />
                                </div>
                              ),
                              thead: ({ node, ...props }) => <thead className="bg-gray-100 dark:bg-zinc-800/80 font-semibold text-gray-900 dark:text-white" {...props} />,
                              th: ({ node, ...props }) => <th className="px-3 py-2" {...props} />,
                              td: ({ node, ...props }) => <td className="px-3 py-2 border-t border-gray-200 dark:border-zinc-800" {...props} />,
                              code: ({ node, inline, ...props }) =>
                                inline ? (
                                  <code className="bg-gray-200/70 dark:bg-zinc-800 text-emerald-700 dark:text-emerald-400 px-1.5 py-0.5 rounded text-xs font-mono" {...props} />
                                ) : (
                                  <pre className="bg-zinc-900 text-zinc-100 p-3 rounded-xl overflow-x-auto text-xs font-mono my-2.5 border border-zinc-800"><code {...props} /></pre>
                                ),
                              blockquote: ({ node, ...props }) => (
                                <blockquote className="border-l-4 border-emerald-500 pl-3 italic my-2 text-gray-600 dark:text-zinc-400" {...props} />
                              ),
                              strong: ({ node, ...props }) => <strong className="font-semibold text-gray-900 dark:text-white" {...props} />,
                            }}
                          >
                            {msg.content}
                          </ReactMarkdown>
                        ) : (
                          <span className="flex items-center gap-2 text-gray-400 dark:text-zinc-500 text-xs py-1">
                            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-ping" />
                            {statusText || 'Thinking...'}
                          </span>
                        )}

                        {/* Blinking cursor while streaming */}
                        {isStreaming && isLastAssistant && msg.content && (
                          <span className="inline-block w-1.5 h-4 ml-1 bg-emerald-500 animate-pulse align-middle" />
                        )}
                      </div>
                    )}

                    {/* Inline Extracted Images */}
                    {msg.images && msg.images.length > 0 && (
                      <div className="mt-4 pt-3 border-t border-gray-200/60 dark:border-zinc-800 space-y-2">
                        <span className="text-xs font-semibold text-gray-500 dark:text-gray-400 flex items-center gap-1.5 mb-2">
                          <ImageIcon className="w-3.5 h-3.5" />
                          Relevant Visual Figures:
                        </span>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                          {msg.images.map((imgItem, i) => {
                            const rawUrl = typeof imgItem === 'string' ? imgItem : imgItem.url;
                            const fullUrl = buildImageUrl(rawUrl);
                            const filename = typeof imgItem === 'object' && imgItem.filename ? imgItem.filename : (rawUrl ? rawUrl.split('/').pop().split('?')[0] : 'figure.png');
                            const captionLabel = typeof imgItem === 'object' && (imgItem.location_label || imgItem.page)
                              ? `${filename} (${imgItem.location_label || 'page ' + imgItem.page})`
                              : filename;
                            const subCaption = typeof imgItem === 'object' && imgItem.caption ? imgItem.caption : '';

                            return (
                              <div
                                key={i}
                                className="group rounded-xl overflow-hidden border border-gray-200 dark:border-zinc-700 bg-white dark:bg-zinc-950 p-2.5 shadow-sm hover:shadow-md transition flex flex-col justify-between"
                              >
                                <div
                                  className="relative cursor-pointer overflow-hidden rounded-lg bg-gray-50 dark:bg-zinc-900 flex items-center justify-center min-h-[160px]"
                                  onClick={() => setLightboxImage({ url: fullUrl, label: captionLabel, caption: subCaption })}
                                >
                                  <img
                                    src={fullUrl}
                                    alt={captionLabel}
                                    className="w-full h-auto max-h-[300px] object-contain rounded-lg transition-transform duration-200 group-hover:scale-105"
                                    onError={(e) => {
                                      e.currentTarget.style.display = 'none';
                                      const fallback = e.currentTarget.parentElement?.querySelector('.img-fallback');
                                      if (fallback) fallback.classList.remove('hidden');
                                    }}
                                  />
                                  <div className="img-fallback hidden py-10 px-4 text-center text-xs text-gray-400 dark:text-zinc-500 flex flex-col items-center gap-1">
                                    <ImageOff className="w-6 h-6 text-gray-300 dark:text-zinc-600 mb-1" />
                                    <span>Image preview unavailable</span>
                                  </div>
                                  <div className="absolute top-2 right-2 p-1.5 bg-black/50 text-white rounded-lg opacity-0 group-hover:opacity-100 transition shadow">
                                    <Maximize2 className="w-3.5 h-3.5" />
                                  </div>
                                </div>
                                <div className="mt-2 text-center">
                                  <p className="text-xs font-medium text-gray-700 dark:text-zinc-300 truncate" title={captionLabel}>
                                    {captionLabel}
                                  </p>
                                  {subCaption && (
                                    <p className="text-[11px] text-gray-400 dark:text-zinc-500 truncate mt-0.5" title={subCaption}>
                                      {subCaption}
                                    </p>
                                  )}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Clarification Buttons */}
                  {msg.meta?.type === 'clarification' && Array.isArray(msg.meta?.options) && msg.meta.options.length > 0 && (
                    <div className="flex flex-wrap gap-2 pt-1">
                      {msg.meta.options.map((opt, i) => {
                        const isClickable = !isStreaming && idx === messages.length - 1;
                        return (
                          <button
                            key={i}
                            type="button"
                            disabled={!isClickable}
                            onClick={() => handleSendMessage(null, opt.label, { selected_option: opt })}
                            className={`px-3 py-1.5 rounded-xl text-xs font-medium border transition ${
                              isClickable
                                ? 'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border-emerald-300 dark:border-emerald-700 hover:bg-emerald-100 dark:hover:bg-emerald-900/60 shadow-sm cursor-pointer'
                                : 'bg-gray-100 dark:bg-zinc-800 text-gray-400 dark:text-zinc-500 border-gray-200 dark:border-zinc-700 cursor-not-allowed opacity-60'
                            }`}
                          >
                            {opt.label}
                          </button>
                        );
                      })}
                    </div>
                  )}

                  {/* Show More Images Button */}
                  {msg.meta?.has_more && msg.meta?.next_offset && (
                    <div className="pt-1.5">
                      <button
                        type="button"
                        disabled={isStreaming}
                        onClick={() => handleSendMessage(null, "show more", { offset: msg.meta.next_offset })}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-gray-100 dark:bg-zinc-800 hover:bg-emerald-50 dark:hover:bg-emerald-950/40 text-emerald-700 dark:text-emerald-400 border border-gray-200 dark:border-zinc-700 transition disabled:opacity-50"
                      >
                        <ImageIcon className="w-3.5 h-3.5" />
                        Show more
                      </button>
                    </div>
                  )}

                  {/* Clickable Source Chips */}
                  {msg.sources && msg.sources.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 pt-1">
                      <span className="text-[11px] font-semibold text-gray-400 dark:text-zinc-500 self-center mr-1">
                        Sources:
                      </span>
                      {msg.sources.map((src, i) => (
                        <button
                          key={i}
                          type="button"
                          onClick={() => setSelectedSource(src)}
                          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium bg-gray-100 dark:bg-zinc-800/80 text-gray-700 dark:text-zinc-300 border border-gray-200/80 dark:border-zinc-700/80 hover:bg-emerald-50 dark:hover:bg-emerald-950/40 hover:text-emerald-700 dark:hover:text-emerald-300 hover:border-emerald-300 dark:hover:border-emerald-800 transition"
                        >
                          <FileText className="w-3 h-3 text-emerald-500" />
                          <span className="truncate max-w-[150px]">{src.filename}</span>
                          <span className="text-[10px] opacity-70">({src.location_label})</span>
                        </button>
                      ))}
                    </div>
                  )}

                  {/* Feedback Controls (Assistant messages only, excluding errors, clarifications and in-progress streaming) */}
                  {(() => {
                    const isClarification = msg.meta?.type === 'clarification';
                    const isError =
                      msg.content &&
                      (msg.content.startsWith('[Error:') ||
                        msg.content.startsWith('Error:') ||
                        msg.content.includes('\n\n[Error:'));
                    const isFinished =
                      msg.sender === 'assistant' &&
                      !isStreaming &&
                      !isError &&
                      !isClarification &&
                      msg.content &&
                      msg.id &&
                      !msg.id.startsWith('ast_');

                    if (!isFinished) return null;

                    return (
                      <div className="pt-1 space-y-2">
                        <div className="flex items-center gap-1.5">
                          <button
                            type="button"
                            onClick={() =>
                              handleRating(msg.id, msg.feedback?.rating, 'up')
                            }
                            className={`p-1.5 rounded-lg text-xs flex items-center gap-1 transition ${
                              msg.feedback?.rating === 'up'
                                ? 'bg-emerald-100 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 font-semibold ring-1 ring-emerald-500/30'
                                : 'text-gray-400 hover:text-gray-600 dark:hover:text-zinc-300 hover:bg-gray-100 dark:hover:bg-zinc-800/60'
                            }`}
                            title={
                              msg.feedback?.rating === 'up'
                                ? 'Remove rating'
                                : 'Helpful answer'
                            }
                          >
                            <ThumbsUp className="w-3.5 h-3.5" />
                            {msg.feedback?.rating === 'up' && (
                              <span className="text-[10px]">Helpful</span>
                            )}
                          </button>

                          <button
                            type="button"
                            onClick={() =>
                              handleRating(msg.id, msg.feedback?.rating, 'down')
                            }
                            className={`p-1.5 rounded-lg text-xs flex items-center gap-1 transition ${
                              msg.feedback?.rating === 'down'
                                ? 'bg-rose-100 dark:bg-rose-950/60 text-rose-700 dark:text-rose-300 font-semibold ring-1 ring-rose-500/30'
                                : 'text-gray-400 hover:text-gray-600 dark:hover:text-zinc-300 hover:bg-gray-100 dark:hover:bg-zinc-800/60'
                            }`}
                            title={
                              msg.feedback?.rating === 'down'
                                ? 'Remove rating'
                                : 'Not helpful'
                            }
                          >
                            <ThumbsDown className="w-3.5 h-3.5" />
                            {msg.feedback?.rating === 'down' && (
                              <span className="text-[10px]">Not helpful</span>
                            )}
                          </button>

                          {msg.latency_ms && (
                            <span className="text-[10px] text-gray-400 dark:text-zinc-500 font-mono ml-2">
                              {(msg.latency_ms / 1000).toFixed(1)}s
                            </span>
                          )}
                        </div>

                        {/* Optional comment box for thumbs-down */}
                        {(openCommentBoxId === msg.id ||
                          (msg.feedback?.rating === 'down' &&
                            msg.feedback?.comment)) && (
                          <div className="p-3 rounded-xl bg-gray-50 dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 space-y-2 max-w-sm">
                            <label className="text-[11px] font-semibold text-gray-700 dark:text-zinc-300 block">
                              What could be improved? (optional)
                            </label>
                            <textarea
                              rows={2}
                              value={
                                commentInputs[msg.id] ??
                                (msg.feedback?.comment || '')
                              }
                              onChange={(e) =>
                                setCommentInputs((prev) => ({
                                  ...prev,
                                  [msg.id]: e.target.value,
                                }))
                              }
                              placeholder="e.g. Missing company policy info, inaccurate facts..."
                              className="w-full p-2 bg-white dark:bg-zinc-800 border border-gray-200 dark:border-zinc-700 rounded-lg text-xs text-gray-800 dark:text-white focus:outline-none focus:ring-1 focus:ring-emerald-500 resize-none"
                            />
                            <div className="flex justify-end gap-1.5">
                              <button
                                type="button"
                                onClick={() => setOpenCommentBoxId(null)}
                                className="px-2.5 py-1 text-[11px] text-gray-500 hover:text-gray-700 rounded-lg transition"
                              >
                                Close
                              </button>
                              <button
                                type="button"
                                onClick={() => handleCommentSubmit(msg.id)}
                                className="px-3 py-1 bg-emerald-600 hover:bg-emerald-700 text-white text-[11px] font-semibold rounded-lg shadow-sm transition"
                              >
                                Save Comment
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })()}
                </div>
              </div>
            );
          })
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Upload Status Banner */}
      {uploadStatus && (
        <div className="px-6 py-2 bg-gray-50 dark:bg-zinc-900 border-t border-gray-200 dark:border-zinc-800 flex items-center justify-between text-xs animate-fadeIn">
          <div className="flex items-center gap-2">
            {uploadStatus.state === 'uploading' && <Clock className="w-3.5 h-3.5 text-blue-500 animate-spin" />}
            {uploadStatus.state === 'processing' && <Clock className="w-3.5 h-3.5 text-amber-500 animate-pulse" />}
            {uploadStatus.state === 'ready' && <CheckCircle className="w-3.5 h-3.5 text-emerald-500" />}
            {uploadStatus.state === 'failed' && <AlertCircle className="w-3.5 h-3.5 text-red-500" />}
            <span className="font-medium text-gray-700 dark:text-zinc-300">
              {uploadStatus.filename}:
            </span>
            <span className="text-gray-500 dark:text-zinc-400 flex items-center gap-2">
              {uploadStatus.state === 'uploading' && (
                <>
                  <span>Uploading to server ({uploadStatus.progress ?? 0}%)...</span>
                  <span className="w-20 bg-gray-200 dark:bg-zinc-700 rounded-full h-1.5 overflow-hidden inline-block">
                    <span
                      className="bg-blue-600 h-1.5 block rounded-full transition-all duration-150"
                      style={{ width: `${uploadStatus.progress ?? 0}%` }}
                    />
                  </span>
                </>
              )}
              {uploadStatus.state === 'processing' && 'Extracting text, OCR & indexing in vector store...'}
              {uploadStatus.state === 'ready' && 'Document ready! Chat is now filtered to this document.'}
              {uploadStatus.state === 'failed' && (uploadStatus.error || 'Ingestion failed')}
            </span>
          </div>
          <button
            type="button"
            onClick={() => setUploadStatus(null)}
            className="text-gray-400 hover:text-gray-600"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Input Box Footer */}
      <footer className="p-4 bg-white dark:bg-zinc-950 border-t border-gray-200 dark:border-zinc-800">
        <form onSubmit={handleSendMessage} className="max-w-3xl mx-auto flex items-end gap-2">
          {/* File Upload Paperclip */}
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileUpload}
            className="hidden"
            accept=".pdf,.docx,.txt,.png,.jpg,.jpeg"
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={isStreaming}
            className="p-3 text-gray-500 hover:text-emerald-600 hover:bg-gray-100 dark:hover:bg-zinc-800 rounded-2xl transition disabled:opacity-40"
            title="Upload document (PDF, DOCX, TXT, PNG, JPG)"
          >
            <Paperclip className="w-5 h-5" />
          </button>

          {/* Text Input */}
          <div className="flex-1 relative">
            <textarea
              rows={1}
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSendMessage();
                }
              }}
              placeholder="Ask questions about company documents, or upload a document..."
              className="w-full py-3 pl-4 pr-12 bg-gray-50 dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-2xl text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500 text-gray-900 dark:text-white resize-none"
            />
          </div>

          {/* Send or Stop */}
          {isStreaming ? (
            <button
              type="button"
              onClick={handleStopStreaming}
              className="p-3 bg-red-600 hover:bg-red-700 text-white rounded-2xl shadow transition flex-shrink-0"
              title="Stop streaming"
            >
              <Square className="w-4 h-4 fill-current" />
            </button>
          ) : (
            <button
              type="submit"
              disabled={!inputValue.trim()}
              className="p-3 bg-emerald-600 hover:bg-emerald-700 disabled:bg-gray-200 dark:disabled:bg-zinc-800 text-white rounded-2xl shadow transition flex-shrink-0 disabled:text-gray-400"
              title="Send message"
            >
              <Send className="w-4 h-4" />
            </button>
          )}
        </form>
      </footer>

      {/* Floating Toast Notifications */}
      {toasts.length > 0 && (
        <div className="fixed bottom-24 right-6 z-50 flex flex-col gap-2 pointer-events-none">
          {toasts.map((toast) => (
            <div
              key={toast.id}
              className={`pointer-events-auto p-3 rounded-xl shadow-xl border text-xs flex items-center gap-2.5 max-w-sm animate-slideIn ${
                toast.type === 'error'
                  ? 'bg-rose-50 dark:bg-rose-950/90 text-rose-800 dark:text-rose-200 border-rose-200 dark:border-rose-900'
                  : toast.type === 'success'
                  ? 'bg-emerald-50 dark:bg-emerald-950/90 text-emerald-800 dark:text-emerald-200 border-emerald-200 dark:border-emerald-900'
                  : 'bg-white dark:bg-zinc-900 text-gray-800 dark:text-white border-gray-200 dark:border-zinc-800'
              }`}
            >
              {toast.type === 'error' && <AlertCircle className="w-4 h-4 text-rose-500 flex-shrink-0" />}
              {toast.type === 'success' && <CheckCircle className="w-4 h-4 text-emerald-500 flex-shrink-0" />}
              {toast.type === 'info' && <Clock className="w-4 h-4 text-blue-500 flex-shrink-0 animate-spin" />}
              <span className="flex-1 leading-snug">{toast.message}</span>
              <button
                type="button"
                onClick={() => setToasts((prev) => prev.filter((t) => t.id !== toast.id))}
                className="text-gray-400 hover:text-gray-600 dark:hover:text-zinc-200 p-0.5"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Source Excerpt Modal */}
      {selectedSource && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-white dark:bg-zinc-900 rounded-2xl max-w-lg w-full p-6 shadow-2xl border border-gray-200 dark:border-zinc-800 space-y-4 animate-scaleUp">
            <div className="flex items-center justify-between border-b border-gray-100 dark:border-zinc-800 pb-3">
              <div className="flex items-center gap-2">
                <FileText className="w-4 h-4 text-emerald-500" />
                <h4 className="text-sm font-bold text-gray-900 dark:text-white truncate max-w-xs">
                  {selectedSource.filename}
                </h4>
              </div>
              <button
                type="button"
                onClick={() => setSelectedSource(null)}
                className="text-gray-400 hover:text-gray-600 p-1"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs text-gray-500">
                <span>Location: <strong className="text-gray-700 dark:text-zinc-300">{selectedSource.location_label}</strong></span>
                <span className="uppercase text-[10px] font-bold px-2 py-0.5 rounded bg-gray-100 dark:bg-zinc-800 text-gray-600 dark:text-zinc-400">
                  {selectedSource.file_type || 'Document'}
                </span>
              </div>
              <div className="p-3.5 rounded-xl bg-gray-50 dark:bg-zinc-800/60 border border-gray-200 dark:border-zinc-700 text-xs text-gray-700 dark:text-zinc-300 leading-relaxed max-h-60 overflow-y-auto">
                <p className="whitespace-pre-wrap">{selectedSource.excerpt}</p>
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              {selectedSource.file_type === 'pdf' && (
                <button
                  type="button"
                  onClick={() => handleOpenPdfPage(selectedSource.doc_id, selectedSource.page)}
                  className="px-3.5 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-xs font-semibold flex items-center gap-1.5 shadow transition"
                >
                  <ExternalLink className="w-3.5 h-3.5" />
                  Open PDF at {selectedSource.location_label}
                </button>
              )}
              <button
                type="button"
                onClick={() => setSelectedSource(null)}
                className="px-3.5 py-2 bg-gray-100 dark:bg-zinc-800 hover:bg-gray-200 text-gray-700 dark:text-zinc-300 rounded-xl text-xs font-medium transition"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
      {/* Lightbox Modal */}
      {lightboxImage && (
        <div
          className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex flex-col items-center justify-center p-4"
          onClick={() => setLightboxImage(null)}
        >
          <div
            className="relative max-w-4xl max-h-[90vh] bg-zinc-950 rounded-2xl p-4 border border-zinc-800 shadow-2xl flex flex-col items-center animate-scaleUp overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="w-full flex items-center justify-between pb-3 border-b border-zinc-800 mb-3">
              <div className="flex items-center gap-2 text-zinc-200 text-xs font-semibold truncate pr-4">
                <ImageIcon className="w-4 h-4 text-emerald-400" />
                <span className="truncate">{lightboxImage.label || 'Image Preview'}</span>
              </div>
              <button
                type="button"
                onClick={() => setLightboxImage(null)}
                className="text-zinc-400 hover:text-white p-1 rounded-lg hover:bg-zinc-800 transition"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="flex-1 overflow-auto flex items-center justify-center max-h-[70vh]">
              <img
                src={lightboxImage.url}
                alt={lightboxImage.label}
                className="max-w-full max-h-[70vh] object-contain rounded-lg"
                onError={(e) => {
                  e.currentTarget.style.display = 'none';
                  const fallback = e.currentTarget.parentElement?.querySelector('.lightbox-fallback');
                  if (fallback) fallback.classList.remove('hidden');
                }}
              />
              <div className="lightbox-fallback hidden py-16 text-center text-sm text-zinc-400">
                <ImageOff className="w-10 h-10 mx-auto text-zinc-600 mb-2" />
                Unable to display full resolution image
              </div>
            </div>

            {lightboxImage.caption && (
              <p className="text-xs text-zinc-400 text-center mt-3 max-w-xl line-clamp-2 px-2">
                {lightboxImage.caption}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
