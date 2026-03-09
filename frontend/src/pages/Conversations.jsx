import { useState, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  Search, Flag, CheckCheck, Paperclip, Send, Smile,
  Phone, Bot, AlertCircle, CheckCircle2, MoreHorizontal,
} from 'lucide-react'
import api from '../api/client'

// ─── Helpers ──────────────────────────────────────────────────────────────────

const AVATAR_COLORS = {
  A:'bg-violet-100 text-violet-600', B:'bg-blue-100 text-blue-600',
  C:'bg-emerald-100 text-emerald-600', D:'bg-amber-100 text-amber-600',
  E:'bg-rose-100 text-rose-600', F:'bg-sky-100 text-sky-600',
  G:'bg-indigo-100 text-indigo-600', H:'bg-orange-100 text-orange-600',
}
function initials(name) { return (name||'?').split(' ').map(w=>w[0]).join('').toUpperCase().slice(0,2) }
function avatarColor(name) { return AVATAR_COLORS[(name||'A')[0]?.toUpperCase()] || 'bg-gray-100 text-gray-600' }

function fmtTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const now = new Date()
  const diff = now - d
  if (diff < 86400000) return d.toLocaleTimeString([], { hour:'2-digit', minute:'2-digit' })
  if (diff < 604800000) return d.toLocaleDateString([], { weekday:'short' })
  return d.toLocaleDateString([], { day:'numeric', month:'short' })
}

// ─── Conversation List ────────────────────────────────────────────────────────

// Map UI tabs to API query params
function tabToParams(tab) {
  if (tab === 'Flagged')  return { flagged: true }
  if (tab === 'Resolved') return { resolved: true }
  return { resolved: false }  // All / Unread → only non-resolved
}

function ConvoList({ conversations, selectedId, onSelect, search, onSearch, tab, onTab }) {
  const filtered = conversations.filter(c => {
    const s = search.toLowerCase()
    return (c.name||c.client_phone||'').toLowerCase().includes(s) || (c.message||'').toLowerCase().includes(s)
  })

  return (
    <div className="flex flex-col h-full border-r border-gray-100 bg-white w-72 shrink-0">
      <div className="px-4 pt-5 pb-3 border-b border-gray-100">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-gray-800">Conversations</h2>
          <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">{filtered.length}</span>
        </div>
        <div className="relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input type="text" value={search} onChange={e => onSearch(e.target.value)} placeholder="Search conversations..."
            className="w-full pl-8 pr-3 py-2 text-sm bg-gray-50 border border-gray-100 rounded-lg text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-gray-200 focus:bg-white transition" />
        </div>
      </div>
      <div className="px-4 py-2 flex gap-1 border-b border-gray-100">
        {['All','Flagged','Resolved'].map(t => (
          <button key={t} onClick={() => onTab(t)}
            className={`text-xs px-3 py-1 rounded-full transition-colors ${tab===t ? 'bg-gray-900 text-white' : 'text-gray-500 hover:bg-gray-50'}`}>
            {t}
          </button>
        ))}
      </div>
      <div className="flex-1 overflow-y-auto">
        {filtered.length === 0 ? (
          <div className="py-10 text-center text-xs text-gray-400">No conversations found</div>
        ) : filtered.map(conv => {
          const isSelected = conv.id === selectedId
          const name = conv.name || conv.client_phone || 'Unknown'
          return (
            <button key={conv.id} onClick={() => onSelect(conv.id)}
              className={`w-full flex items-start gap-3 px-4 py-3.5 border-b border-gray-50 transition-colors text-left relative hover:bg-gray-50 ${isSelected ? 'bg-gray-50' : 'bg-white'}`}>
              {isSelected && <div className="absolute left-0 top-3 bottom-3 w-0.5 bg-emerald-500 rounded-r" />}
              <div className="relative shrink-0">
                <div className={`w-9 h-9 rounded-full flex items-center justify-center text-xs font-semibold ${avatarColor(name)}`}>{initials(name)}</div>
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between mb-0.5">
                  <span className="text-sm font-medium text-gray-700 truncate">{name}</span>
                  <span className="text-xs text-gray-400 shrink-0 ml-2">{fmtTime(conv.created_at)}</span>
                </div>
                <div className="flex items-center justify-between gap-1">
                  <p className="text-xs text-gray-400 truncate">{conv.message}</p>
                  {conv.flagged && <Flag size={11} className="text-red-400 fill-red-100 shrink-0" />}
                </div>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ─── Chat Window ──────────────────────────────────────────────────────────────

function ChatWindow({ conversation, messages, isLoadingMessages, onResolve, resolved }) {
  const [input, setInput] = useState('')
  const [showResolved, setShowResolved] = useState(false)
  const bottomRef = useRef(null)
  const name = conversation.name || conversation.client_phone || 'Unknown'

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  function handleSend() { const t = input.trim(); if (!t) return; setInput('') }
  function handleKeyDown(e) { if (e.key==='Enter' && !e.shiftKey) { e.preventDefault(); handleSend() } }
  function handleResolveClick() {
    onResolve()
    setShowResolved(true)
    setTimeout(() => setShowResolved(false), 3000)
  }

  return (
    <div className="flex flex-col flex-1 h-full bg-white min-w-0">
      {/* Header */}
      <div className="h-16 px-5 flex items-center justify-between border-b border-gray-100 shrink-0">
        <div className="flex items-center gap-3">
          <div className={`w-9 h-9 rounded-full ${avatarColor(name)} flex items-center justify-center text-xs font-semibold`}>{initials(name)}</div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold text-gray-900">{name}</h3>
              {conversation.flagged && <span className="flex items-center gap-1 text-xs text-red-500 bg-red-50 px-1.5 py-0.5 rounded"><Flag size={10} className="fill-red-200" /> Flagged</span>}
            </div>
            {conversation.client_phone && <p className="text-xs text-gray-400">{conversation.client_phone}</p>}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 px-2.5 py-1.5 bg-emerald-50 rounded-lg border border-emerald-100"><Bot size={12} className="text-emerald-600" /><span className="text-xs text-emerald-700">AI Active</span></div>
          <button className="p-2 rounded-lg hover:bg-gray-50 text-gray-400 transition-colors"><Phone size={15} /></button>
          <button className="p-2 rounded-lg hover:bg-gray-50 text-gray-400 transition-colors"><MoreHorizontal size={15} /></button>
          {!resolved ? (
            <button onClick={handleResolveClick} className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-900 text-white text-xs rounded-lg hover:bg-gray-700 transition-colors ml-1"><CheckCircle2 size={13} />Mark as Resolved</button>
          ) : (
            <div className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-50 text-emerald-700 text-xs rounded-lg border border-emerald-100 ml-1"><CheckCircle2 size={13} className="text-emerald-500" />Resolved</div>
          )}
        </div>
      </div>

      {showResolved && (
        <div className="mx-4 mt-3 flex items-center gap-2 text-xs text-emerald-700 bg-emerald-50 border border-emerald-100 px-3 py-2.5 rounded-lg">
          <CheckCircle2 size={13} className="text-emerald-500 shrink-0" />Conversation marked as resolved. The AI will stop sending automatic replies.
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-1" style={{ background: '#fafafa' }}>
        {isLoadingMessages ? (
          <div className="flex items-center justify-center py-10">
            <div className="w-5 h-5 border-2 border-gray-200 border-t-gray-500 rounded-full animate-spin" />
          </div>
        ) : messages.length === 0 ? (
          <div className="flex items-center justify-center py-10 text-xs text-gray-400">No messages</div>
        ) : <>
          <div className="flex items-center gap-3 my-3">
            <div className="flex-1 h-px bg-gray-200" /><span className="text-xs text-gray-400 shrink-0">Conversation</span><div className="flex-1 h-px bg-gray-200" />
          </div>
          {messages.map((msg, idx) => {
            const isClient = msg.sender === 'client'
            const isBot    = msg.sender === 'bot'
            const showAvatar = isClient && (idx===0 || messages[idx-1]?.sender !== 'client')
            return (
              <div key={msg.id} className={`flex ${isClient ? 'justify-start' : 'justify-end'} ${idx>0 && messages[idx-1]?.sender===msg.sender ? 'mt-1' : 'mt-3'}`}>
                {isClient && (
                  <div className="w-7 shrink-0 mr-2 mt-auto">
                    {showAvatar && <div className={`w-7 h-7 rounded-full ${avatarColor(name)} flex items-center justify-center text-xs font-semibold`}>{initials(name)}</div>}
                  </div>
                )}
                <div className={`max-w-[65%] ${!isClient ? 'items-end' : 'items-start'} flex flex-col`}>
                  {(isBot) && (idx===0 || messages[idx-1]?.sender!==msg.sender) && (
                    <span className="text-xs text-gray-400 mb-1 px-1">AI Assistant</span>
                  )}
                  <div className={`relative px-3.5 py-2.5 rounded-2xl text-sm leading-relaxed ${
                    isClient ? (msg.flagged ? 'bg-red-50 border border-red-100 text-gray-800 rounded-tl-sm' : 'bg-white border border-gray-100 text-gray-800 rounded-tl-sm shadow-sm')
                    : 'bg-emerald-500 text-white rounded-tr-sm'}`}>
                    {msg.flagged && isClient && <div className="flex items-center gap-1 mb-1.5 text-red-400"><AlertCircle size={11} /><span className="text-xs">Flagged message</span></div>}
                    {isBot && <div className="flex items-center gap-1 mb-1.5 opacity-75"><Bot size={11} /><span className="text-xs">AI Reply</span></div>}
                    <p>{msg.text}</p>
                    <div className={`flex items-center gap-1 mt-1.5 ${isClient ? 'justify-start' : 'justify-end'}`}>
                      <span className={`text-xs ${isClient ? 'text-gray-400' : 'text-white/60'}`}>{fmtTime(msg.time)}</span>
                      {!isClient && <CheckCheck size={12} className="text-white/80" />}
                    </div>
                  </div>
                </div>
              </div>
            )
          })}
        </>}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="shrink-0 border-t border-gray-100 px-4 py-3 bg-white">
        <div className="flex items-center gap-1.5 mb-2"><div className="w-1.5 h-1.5 rounded-full bg-amber-400" /><span className="text-xs text-gray-400">Manual reply — AI will pause for this conversation</span></div>
        <div className="flex items-end gap-2">
          <div className="flex-1 relative">
            <textarea value={input} onChange={e=>setInput(e.target.value)} onKeyDown={handleKeyDown} rows={2} placeholder="Type a message..."
              className="w-full px-3.5 py-2.5 text-sm bg-gray-50 border border-gray-100 rounded-xl text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-gray-200 focus:bg-white resize-none transition" />
          </div>
          <div className="flex flex-col gap-1.5 pb-0.5">
            <button className="p-2 rounded-lg hover:bg-gray-50 text-gray-400 hover:text-gray-500 transition-colors"><Paperclip size={16} /></button>
            <button className="p-2 rounded-lg hover:bg-gray-50 text-gray-400 hover:text-gray-500 transition-colors"><Smile size={16} /></button>
          </div>
          <button onClick={handleSend} disabled={!input.trim()} className="p-2.5 bg-gray-900 text-white rounded-xl hover:bg-gray-700 disabled:opacity-30 disabled:cursor-not-allowed transition-colors mb-0.5"><Send size={16} /></button>
        </div>
        <p className="text-xs text-gray-400 mt-1.5">Press <kbd className="text-xs bg-gray-100 px-1 py-0.5 rounded">Enter</kbd> to send · <kbd className="text-xs bg-gray-100 px-1 py-0.5 rounded">Shift+Enter</kbd> for new line</p>
      </div>
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function Conversations() {
  const qc = useQueryClient()
  const [selectedId, setSelectedId] = useState(null)
  const [search, setSearch]         = useState('')
  const [tab, setTab]               = useState('All')
  const [resolvedIds, setResolvedIds] = useState(new Set())

  // ── Data ──────────────────────────────────────────────────────────────────
  const { data: conversations = [], isLoading: listLoading } = useQuery({
    queryKey: ['conversations', tab],
    queryFn: () => api.get('/conversations', { params: tabToParams(tab) }).then(r => r.data?.data || []),
    placeholderData: [],
    refetchInterval: 30000,
  })

  const firstId = conversations[0]?.id || null
  const activeId = selectedId || firstId

  const { data: messages = [], isLoading: msgLoading } = useQuery({
    queryKey: ['messages', activeId],
    queryFn: () => api.get(`/conversations/${activeId}/messages`).then(r => r.data?.data || []),
    enabled: !!activeId,
    placeholderData: [],
  })

  // ── Resolve mutation ───────────────────────────────────────────────────────
  const resolveMutation = useMutation({
    mutationFn: (id) => api.patch(`/conversations/${id}/resolve`),
    onSuccess: (_, id) => {
      setResolvedIds(prev => new Set([...prev, id]))
      qc.invalidateQueries({ queryKey: ['conversations'] })
      toast.success('Conversation resolved')
    },
    onError: () => toast.error('Failed to resolve'),
  })

  const selected = conversations.find(c => c.id === activeId)

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-gray-50/60 -mx-8 -my-7">
      {/* Top Bar */}
      <div className="h-16 bg-white border-b border-gray-100 px-8 flex items-center shrink-0 sticky top-0 z-10">
        <div>
          <h1 className="text-base font-semibold text-gray-900">Conversations</h1>
          <p className="text-xs text-gray-400">Customer messages handled by you and your AI assistant</p>
        </div>
      </div>

      {/* Body: list + chat */}
      {listLoading ? (
        <div className="flex-1 flex items-center justify-center">
          <div className="w-7 h-7 border-2 border-gray-200 border-t-gray-500 rounded-full animate-spin" />
        </div>
      ) : (
        <div className="flex flex-1 overflow-hidden">
          <ConvoList
            conversations={conversations}
            selectedId={activeId}
            onSelect={setSelectedId}
            search={search}
            onSearch={setSearch}
            tab={tab}
            onTab={setTab}
          />
          {selected ? (
            <ChatWindow
              conversation={selected}
              messages={messages}
              isLoadingMessages={msgLoading}
              resolved={resolvedIds.has(selected.id) || selected.resolved}
              onResolve={() => resolveMutation.mutate(selected.id)}
            />
          ) : (
            <div className="flex-1 flex items-center justify-center text-sm text-gray-400">Select a conversation</div>
          )}
        </div>
      )}
    </div>
  )
}
