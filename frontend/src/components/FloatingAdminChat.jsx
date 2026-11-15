import React, { useState, useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  MessageSquare,
  X,
  Send,
  Paperclip,
  Sparkles,
  CheckCircle,
  Clock,
  AlertCircle,
  Plus,
  Image as ImageIcon,
  ImageOff,
} from 'lucide-react';
import {
  apiCreateConversation,
  apiStreamChatMessage,
  apiUploadDocument,
  apiGetDocumentStatus,
  getAuthToken,
  buildFileUrl,
} from '../api';

export default function FloatingAdminChat() {
  const [isOpen, setIsOpen] = useState(false);
  const [conversation, setConversation] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [statusText, setStatusText] = useState('');
  const [uploadStatus, setUploadStatus] = useState(null);

  const fileInputRef = useRef(null);
  const messagesEndRef = useRef(null);
  const chatScrollRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isStreaming, statusText]);

  const buildImageUrl = (url) => {
    if (!url) return '';
    return buildFileUrl(url);
  };

  // Rule 4: New Chat in FloatingAdminChat immediately resets state without API call
  const handleNewChat = () => {
    setConversation(null);
    setMessages([]);
    setInput('');
    setStatusText('');
    if (chatScrollRef.current) {
      chatScrollRef.current.scrollTop = 0;
    }
  };

  // Handle Admin File Upload (Goes to scope=company, does NOT lock conversation)
  const handleAdminFileUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploadStatus({ filename: file.name, state: 'uploading' });

    try {
      // NOTE: Admin upload does NOT pass conversation_id, so it goes to scope=company without locking!
      const doc = await apiUploadDocument(file);
      setUploadStatus({ filename: file.name, state: 'processing' });

      const checkInterval = setInterval(async () => {
        try {
          const statusRes = await apiGetDocumentStatus(doc.id);
          if (statusRes.status === 'ready') {
            clearInterval(checkInterval);
            setUploadStatus({ filename: file.name, state: 'ready' });
            setTimeout(() => setUploadStatus(null), 3000);
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
      setTimeout(() => setUploadStatus(null), 4000);
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleSendMessage = async (e) => {
    e?.preventDefault();
    const text = input.trim();
    if (!text || isStreaming) return;

    setInput('');
    const userMsg = { id: `u_${Date.now()}`, sender: 'user', content: text };
    const assistantMsgId = `a_${Date.now()}`;
    const assistantPlaceholder = { id: assistantMsgId, sender: 'assistant', content: '' };

    setMessages((prev) => [...prev, userMsg, assistantPlaceholder]);
    setIsStreaming(true);
    setStatusText('Thinking...');

    try {
      let targetConv = conversation;
      if (!targetConv || !targetConv.id) {
        targetConv = await apiCreateConversation('Admin Floating Panel Chat');
        setConversation(targetConv);
      }

      await apiStreamChatMessage(
        targetConv.id,
        text,
        (token) => {
          setStatusText('');
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsgId ? { ...m, content: m.content + token } : m
            )
          );
        },
        (sources, images, doneData) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsgId ? { ...m, sources: sources || [], images: images || [] } : m
            )
          );
          setIsStreaming(false);
          setStatusText('');
          if (doneData?.conversation_id && (!conversation || !conversation.id)) {
            setConversation({ id: doneData.conversation_id, title: doneData.title });
          }
        },
        (err) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsgId ? { ...m, content: m.content + `\n[Error: ${err}]` } : m
            )
          );
          setIsStreaming(false);
          setStatusText('');
        },
        (statusMsg) => {
          setStatusText(statusMsg);
        }
      );
    } catch (err) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantMsgId ? { ...m, content: `Error: ${err.message}` } : m
        )
      );
      setIsStreaming(false);
      setStatusText('');
    }
  };

  return (
    <>
      {/* Floating Trigger Button */}
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="fixed bottom-6 right-6 w-14 h-14 rounded-full bg-emerald-600 hover:bg-emerald-700 text-white shadow-2xl flex items-center justify-center transition-transform hover:scale-110 z-40"
        title="Open Admin RAG Assistant"
      >
        {isOpen ? <X className="w-6 h-6" /> : <MessageSquare className="w-6 h-6" />}
      </button>

      {/* Floating Chat Panel */}
      {isOpen && (
        <div className="fixed bottom-24 right-6 w-96 h-[520px] bg-white dark:bg-zinc-900 rounded-3xl border border-gray-200 dark:border-zinc-800 shadow-2xl flex flex-col overflow-hidden z-40 animate-slideUp">
          {/* Header */}
          <div className="p-3.5 border-b border-gray-200 dark:border-zinc-800 bg-emerald-600 text-white flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Sparkles className="w-4 h-4" />
              <div>
                <h3 className="text-xs font-bold leading-tight">Admin Assistant</h3>
                <span className="text-[10px] opacity-80">Global Company Scope</span>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleNewChat}
                className="p-1 hover:bg-emerald-700 rounded-lg text-white transition text-[11px] flex items-center gap-1 font-medium"
                title="Start new floating chat session"
              >
                <Plus className="w-3.5 h-3.5" />
                New Chat
              </button>
              <button onClick={() => setIsOpen(false)} className="hover:opacity-75 p-1">
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Upload Status Banner */}
          {uploadStatus && (
            <div className="px-3 py-1.5 bg-gray-50 dark:bg-zinc-800 border-b border-gray-200 dark:border-zinc-700 flex items-center gap-1.5 text-[10px]">
              {uploadStatus.state === 'uploading' && <Clock className="w-3 h-3 text-blue-500 animate-spin" />}
              {uploadStatus.state === 'processing' && <Clock className="w-3 h-3 text-amber-500 animate-pulse" />}
              {uploadStatus.state === 'ready' && <CheckCircle className="w-3 h-3 text-emerald-500" />}
              {uploadStatus.state === 'failed' && <AlertCircle className="w-3 h-3 text-red-500" />}
              <span className="truncate font-semibold">{uploadStatus.filename}:</span>
              <span className="text-gray-500 truncate">
                {uploadStatus.state === 'ready' ? 'Indexed in Company KB!' : uploadStatus.state}
              </span>
            </div>
          )}

          {/* Messages Feed */}
          <div ref={chatScrollRef} className="flex-1 overflow-y-auto p-3 space-y-3">
            {messages.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-center p-4">
                <Sparkles className="w-8 h-8 text-emerald-500 mb-2 opacity-60" />
                <p className="text-xs font-semibold text-gray-700 dark:text-zinc-300">
                  Admin Knowledge Panel
                </p>
                <p className="text-[11px] text-gray-400 mt-1">
                  Upload files or test company-scope queries. Uploaded files here become instantly available to all company users.
                </p>
              </div>
            ) : (
              messages.map((m, idx) => {
                const isLastAssistant = m.sender === 'assistant' && idx === messages.length - 1;
                return (
                  <div
                    key={m.id}
                    className={`flex ${m.sender === 'user' ? 'justify-end' : 'justify-start'}`}
                  >
                    <div
                      className={`max-w-[85%] p-2.5 rounded-2xl text-xs leading-relaxed ${
                        m.sender === 'user'
                          ? 'bg-emerald-600 text-white rounded-br-none'
                          : 'bg-gray-100 dark:bg-zinc-800 text-gray-800 dark:text-zinc-200 rounded-bl-none border border-gray-200/60 dark:border-zinc-700/60'
                      }`}
                    >
                      {m.sender === 'user' ? (
                        <p className="whitespace-pre-wrap">{m.content}</p>
                      ) : (
                        <div>
                          {m.content ? (
                            <ReactMarkdown
                              remarkPlugins={[remarkGfm]}
                              components={{
                                p: ({ node, ...props }) => <p className="mb-1.5 last:mb-0" {...props} />,
                                ul: ({ node, ...props }) => <ul className="list-disc pl-4 mb-1.5" {...props} />,
                                ol: ({ node, ...props }) => <ol className="list-decimal pl-4 mb-1.5" {...props} />,
                                li: ({ node, ...props }) => <li className="pl-0.5" {...props} />,
                                code: ({ node, inline, ...props }) =>
                                  inline ? (
                                    <code className="bg-gray-200 dark:bg-zinc-700 px-1 rounded font-mono text-[11px]" {...props} />
                                  ) : (
                                    <pre className="bg-zinc-950 p-2 rounded text-[11px] font-mono my-1 overflow-x-auto"><code {...props} /></pre>
                                  ),
                              }}
                            >
                              {m.content}
                            </ReactMarkdown>
                          ) : (
                            <span className="flex items-center gap-1.5 text-gray-400">
                              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-ping" />
                              {statusText || 'Thinking...'}
                            </span>
                          )}
                          {isStreaming && isLastAssistant && m.content && (
                            <span className="inline-block w-1 h-3 ml-1 bg-emerald-500 animate-pulse align-middle" />
                          )}

                          {/* Extracted Images */}
                          {m.images && m.images.length > 0 && (
                            <div className="mt-2.5 pt-2 border-t border-gray-200/60 dark:border-zinc-800 space-y-2">
                              <span className="text-[10px] font-semibold text-gray-500 dark:text-gray-400 flex items-center gap-1">
                                <ImageIcon className="w-3 h-3" />
                                Visual Figures:
                              </span>
                              <div className="space-y-2">
                                {m.images.map((imgItem, i) => {
                                  const rawUrl = typeof imgItem === 'string' ? imgItem : imgItem.url;
                                  const fullUrl = buildImageUrl(rawUrl);
                                  const filename = typeof imgItem === 'object' && imgItem.filename ? imgItem.filename : (rawUrl ? rawUrl.split('/').pop().split('?')[0] : 'figure.png');
                                  const captionLabel = typeof imgItem === 'object' && (imgItem.location_label || imgItem.page)
                                    ? `${filename} (${imgItem.location_label || 'page ' + imgItem.page})`
                                    : filename;

                                  return (
                                    <div key={i} className="rounded-lg overflow-hidden border border-gray-200 dark:border-zinc-700 bg-white dark:bg-zinc-950 p-1.5">
                                      <a href={fullUrl} target="_blank" rel="noopener noreferrer">
                                        <img
                                          src={fullUrl}
                                          alt={captionLabel}
                                          className="w-full h-auto max-h-40 object-contain rounded"
                                          onError={(e) => {
                                            e.currentTarget.style.display = 'none';
                                            const fb = e.currentTarget.parentElement?.querySelector('.admin-img-fb');
                                            if (fb) fb.classList.remove('hidden');
                                          }}
                                        />
                                        <div className="admin-img-fb hidden py-4 text-center text-[10px] text-gray-400">
                                          <ImageOff className="w-4 h-4 mx-auto mb-0.5 text-gray-300" />
                                          Image unavailable
                                        </div>
                                      </a>
                                      <p className="text-[10px] text-gray-500 dark:text-zinc-400 text-center truncate mt-1">
                                        {captionLabel}
                                      </p>
                                    </div>
                                  );
                                })}
                              </div>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Input Footer */}
          <div className="p-2 border-t border-gray-200 dark:border-zinc-800 bg-gray-50/50 dark:bg-zinc-900/50">
            <form onSubmit={handleSendMessage} className="flex items-center gap-1.5">
              <input
                type="file"
                ref={fileInputRef}
                onChange={handleAdminFileUpload}
                className="hidden"
                accept=".pdf,.docx,.txt,.png,.jpg,.jpeg"
              />
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={isStreaming}
                className="p-2 text-gray-500 hover:text-emerald-600 rounded-xl transition"
                title="Upload to Company KB (No Chat Lock)"
              >
                <Paperclip className="w-4 h-4" />
              </button>
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Ask company assistant..."
                className="flex-1 py-2 px-3 bg-white dark:bg-zinc-800 border border-gray-200 dark:border-zinc-700 rounded-xl text-xs focus:outline-none focus:ring-2 focus:ring-emerald-500 text-gray-900 dark:text-white"
              />
              <button
                type="submit"
                disabled={!input.trim() || isStreaming}
                className="p-2 bg-emerald-600 hover:bg-emerald-700 disabled:opacity-40 text-white rounded-xl transition"
              >
                <Send className="w-4 h-4" />
              </button>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
