import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, Image, Smile, Send, Clock, CheckCheck, Megaphone, History } from 'lucide-react'
import { Link } from 'react-router-dom'
import { format } from 'date-fns'
import api from '../api/client'
import toast from 'react-hot-toast'
import DataTable from '../components/ui/DataTable'
import StatusBadge from '../components/ui/StatusBadge'

const TEMPLATES = [
  {
    category: 'Promotions',
    name: 'Flash Sale Announcement',
    text: '🔥 Big sale happening NOW at {shop_name}!\n\nHi {first_name}, don\'t miss out — up to 40% OFF on selected items today only.\n\nShop before midnight 👋',
  },
  {
    category: 'Promotions',
    name: 'Weekend Offer',
    text: '🎉 Weekend Special at {shop_name}!\n\nHi {first_name}, enjoy 25% OFF all weekend. Limited stock — grab yours now!',
  },
  {
    category: 'Reminders',
    name: 'Restock Alert',
    text: '📦 Back in stock at {shop_name}!\n\nHi {first_name}, the item you were interested in is back. Get it before it sells out again.',
  },
  {
    category: 'Updates',
    name: 'New Arrivals',
    text: '✨ New arrivals at {shop_name}!\n\nHi {first_name}, we just added fresh new products. Come check them out today!',
  },
]

const TAGS = [
  { label: '+ Customer Name', tag: '{first_name}' },
  { label: '+ Shop Name',     tag: '{shop_name}'  },
  { label: "+ Today's Date",  tag: '{today_date}' },
]

const TAG_COLORS = [
  'bg-blue-100 text-blue-700 hover:bg-blue-200',
  'bg-violet-100 text-violet-700 hover:bg-violet-200',
  'bg-emerald-100 text-emerald-700 hover:bg-emerald-200',
]

const MAX_CHARS = 1024

function LivePreview({ message }) {
  const now = new Date()
  const timeStr = `${now.getHours()}:${String(now.getMinutes()).padStart(2, '0')}`
  const preview = message
    .replace(/{first_name}/g, 'Rahul')
    .replace(/{shop_name}/g, "Kofi's Store")
    .replace(/{today_date}/g, new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }))

  return (
    <div className="rounded-2xl overflow-hidden border border-border shadow-sm">
      {/* Phone status bar */}
      <div className="bg-gray-900 text-white px-4 py-2 flex items-center justify-between text-xs">
        <span className="font-semibold">9:41</span>
        <div className="flex items-center gap-1">
          <span>▪▪▪</span>
          <span>WiFi</span>
          <span>⬛</span>
        </div>
      </div>
      {/* WhatsApp header */}
      <div className="bg-emerald-600 text-white px-3 py-2 flex items-center gap-3">
        <div className="w-8 h-8 rounded-full bg-emerald-400 flex items-center justify-center text-xs font-bold">KS</div>
        <div>
          <p className="text-xs font-semibold leading-tight">Kofi's Store</p>
          <p className="text-[10px] opacity-75">Business Account</p>
        </div>
      </div>
      {/* Chat area */}
      <div className="bg-[#ECE5DD] px-3 py-4 min-h-[180px]">
        <div className="text-center mb-3">
          <span className="text-[10px] bg-white/70 text-gray-500 px-2 py-0.5 rounded-full">Today</span>
        </div>
        {message ? (
          <div className="bg-white rounded-lg rounded-tl-none px-3 py-2 max-w-[85%] shadow-sm">
            <p className="text-xs text-gray-800 whitespace-pre-wrap leading-relaxed">{preview}</p>
            <div className="flex items-center justify-end gap-1 mt-1">
              <span className="text-[9px] text-gray-400">{timeStr}</span>
              <CheckCheck size={10} className="text-blue-500" />
            </div>
          </div>
        ) : (
          <p className="text-xs text-center text-gray-400 mt-10">Your message will appear here</p>
        )}
      </div>
      {/* Input bar */}
      <div className="bg-[#F0F0F0] px-2 py-2 flex items-center gap-2">
        <div className="flex-1 bg-white rounded-full px-3 py-1.5 text-xs text-gray-400">Message</div>
        <div className="w-7 h-7 bg-emerald-500 rounded-full flex items-center justify-center">
          <Send size={12} className="text-white" />
        </div>
      </div>
    </div>
  )
}

export default function Broadcasts() {
  const qc = useQueryClient()
  const textareaRef = useRef(null)

  const [activeTab, setActiveTab] = useState('new') // 'new' | 'history'
  const [historyPage, setHistoryPage] = useState(1)

  const [templateDropOpen, setTemplateDropOpen] = useState(false)
  const [selectedTemplate, setSelectedTemplate] = useState(null)
  const [message, setMessage] = useState('')
  const [sendMode, setSendMode] = useState('now') // 'now' | 'later'
  const [scheduledAt, setScheduledAt] = useState('')
  const [broadcastName, setBroadcastName] = useState('')

  const { data: clients = [] } = useQuery({
    queryKey: ['clients'],
    queryFn: () => api.get('/clients').then(r => r.data?.data?.clients || []),
    placeholderData: [],
  })

  const { data: historyData, isLoading: historyLoading } = useQuery({
    queryKey: ['broadcasts-history', historyPage],
    queryFn: () => api.get('/broadcasts', { params: { page: historyPage, page_size: 15 } }).then(r => r.data?.data || {}),
  })

  const recipientCount = clients.length

  const sendMutation = useMutation({
    mutationFn: () => api.post('/broadcasts', {
      name: broadcastName || selectedTemplate?.name || 'New Broadcast',
      template_text: message,
      channel: 'whatsapp',
      scheduled_at: sendMode === 'later' ? scheduledAt : null,
    }),
    onSuccess: () => {
      toast.success('Broadcast queued successfully!')
      qc.invalidateQueries(['broadcasts-history'])
      setMessage('')
      setSelectedTemplate(null)
      setBroadcastName('')
      setActiveTab('history')
    },
    onError: (e) => toast.error(e?.response?.data?.detail || 'Failed to send broadcast'),
  })

  function pickTemplate(t) {
    setSelectedTemplate(t)
    setMessage(t.text)
    setTemplateDropOpen(false)
  }

  function insertTag(tag) {
    const el = textareaRef.current
    if (!el) return
    const start = el.selectionStart
    const end   = el.selectionEnd
    const newMsg = message.slice(0, start) + tag + message.slice(end)
    setMessage(newMsg)
    setTimeout(() => {
      el.focus()
      el.selectionStart = el.selectionEnd = start + tag.length
    }, 0)
  }

  const examplePreview = message
    .replace(/{first_name}/g, 'Rahul')
    .replace(/{shop_name}/g, "Kofi's Store")
    .replace(/{today_date}/g, new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }))

  const charCount    = message.length
  const msgLenLabel  = charCount > 0
    ? charCount <= 160 ? 'Short'
    : charCount <= 480 ? 'Medium'
    : 'Long'
    : '—'

  return (
    <div style={{ animation: 'fadeIn 0.3s ease-out' }}>

      {/* ── Top Header Bar ──────────────────────────────────────── */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-text-primary">Broadcasts</h1>
          <p className="text-sm text-text-secondary">Send and track WhatsApp campaigns</p>
        </div>
      </div>

      {/* ── Tabs ──────────────────────────────────────────────── */}
      <div className="flex bg-gray-100 p-1 rounded-xl w-fit mb-6">
        <button
          onClick={() => setActiveTab('new')}
          className={`flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium transition-all ${
            activeTab === 'new'
              ? 'bg-white text-gray-900 shadow-sm'
              : 'text-gray-500 hover:text-gray-700'
          }`}
        >
          <Megaphone size={16} /> New Broadcast
        </button>
        <button
          onClick={() => setActiveTab('history')}
          className={`flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium transition-all ${
            activeTab === 'history'
              ? 'bg-white text-gray-900 shadow-sm'
              : 'text-gray-500 hover:text-gray-700'
          }`}
        >
          <History size={16} /> History
        </button>
      </div>

      {activeTab === 'new' ? (
        <>
          <div className="flex justify-end mb-4">
            <div className="flex items-center gap-3">
              <button
                className="px-4 py-2 text-sm font-medium border border-border rounded-lg hover:bg-bg-raised text-text-secondary transition-colors"
                onClick={() => toast('Saved as draft')}
              >
                Save as Draft
              </button>
              <button
                id="send-broadcast-btn"
                className="flex items-center gap-2 px-4 py-2 text-sm font-semibold text-white rounded-lg transition-colors disabled:opacity-50"
                style={{ background: '#10B981' }}
                disabled={!message || sendMutation.isPending}
                onClick={() => sendMutation.mutate()}
              >
                <Send size={14} />
                {sendMutation.isPending ? 'Sending…' : `Send to ${recipientCount.toLocaleString()} people`}
              </button>
            </div>
          </div>

      {/* ── Two-column layout ────────────────────────────────────── */}
      <div className="flex gap-5">

        {/* ── LEFT / CENTER: Composer ──────────────────────────── */}
        <div className="flex-1 min-w-0 space-y-5">

          {/* Step 1 — Template */}
          <div className="card space-y-3">
            <div>
              <p className="text-sm font-semibold text-text-primary flex items-center gap-2">
                <span className="text-blue-500">📋</span> Start with a template
                <span className="text-xs font-normal text-text-muted">(optional)</span>
              </p>
              <p className="text-xs text-text-secondary mt-0.5">
                Pick a ready-made message to save time, or write your own below
              </p>
            </div>

            {/* Template dropdown */}
            <div className="relative">
              <button
                onClick={() => setTemplateDropOpen(o => !o)}
                className="w-full flex items-center justify-between px-4 py-3 border border-border rounded-lg bg-bg-input text-sm hover:border-accent transition-colors"
              >
                <div className="flex items-center gap-2">
                  {selectedTemplate && (
                    <span className="text-xs bg-violet-100 text-violet-700 px-2 py-0.5 rounded-full font-medium">
                      {selectedTemplate.category}
                    </span>
                  )}
                  <span className="text-text-secondary">
                    {selectedTemplate ? selectedTemplate.name : 'Select a template…'}
                  </span>
                </div>
                <ChevronDown size={14} className={`text-text-muted transition-transform ${templateDropOpen ? 'rotate-180' : ''}`} />
              </button>
              {templateDropOpen && (
                <div className="absolute z-20 top-full left-0 right-0 mt-1 bg-white border border-border rounded-xl shadow-lg overflow-hidden">
                  {TEMPLATES.map((t, i) => (
                    <button
                      key={i}
                      onClick={() => pickTemplate(t)}
                      className="w-full text-left px-4 py-3 hover:bg-bg-raised border-b border-border last:border-0 transition-colors"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-medium text-text-primary">{t.name}</span>
                        <span className="text-xs text-text-muted bg-bg-raised px-2 py-0.5 rounded-full">{t.category}</span>
                      </div>
                      <p className="text-xs text-text-secondary mt-0.5 truncate">{t.text.slice(0, 60)}…</p>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Step 2 — Message */}
          <div className="card space-y-3">
            <div className="flex items-center justify-between">
              <p className="text-sm font-semibold text-text-primary">Your message</p>
              <span className="text-xs text-text-muted">{charCount} / {MAX_CHARS}</span>
            </div>
            <p className="text-xs text-text-secondary -mt-2">Write clearly and keep it short — customers read this on their phone</p>

            <textarea
              ref={textareaRef}
              rows={6}
              maxLength={MAX_CHARS}
              value={message}
              onChange={e => setMessage(e.target.value)}
              placeholder="Hi {first_name}, here's a special offer just for you…"
              className="w-full bg-bg-input border border-border rounded-lg px-4 py-3 text-sm text-text-primary placeholder-text-muted focus:outline-none focus:border-accent resize-none transition-colors"
            />

            <div className="flex items-center gap-3 text-xs text-text-muted">
              <button className="flex items-center gap-1 hover:text-text-primary transition-colors">
                <Image size={13} /> Add image
              </button>
              <button className="flex items-center gap-1 hover:text-text-primary transition-colors">
                <Smile size={13} /> Emoji
              </button>
            </div>

            {/* Personalisation tags */}
            <div className="border-t border-border pt-3">
              <p className="text-xs text-text-secondary mb-2">
                <span className="font-medium">Personalise your message</span> — tap a tag to add it automatically
              </p>
              <div className="flex flex-wrap gap-2">
                {TAGS.map((t, i) => (
                  <button
                    key={i}
                    onClick={() => insertTag(t.tag)}
                    className={`text-xs font-medium px-3 py-1 rounded-full transition-colors ${TAG_COLORS[i % TAG_COLORS.length]}`}
                  >
                    {t.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Example preview */}
            {message && (
              <div className="bg-emerald-50 border border-emerald-100 rounded-lg px-4 py-2.5 text-xs text-text-secondary leading-relaxed">
                <span className="font-medium text-emerald-700">Example: </span>
                {examplePreview}
              </div>
            )}
          </div>

          {/* Step 3 — Who receives this */}
          <div className="card space-y-3">
            <div>
              <p className="text-sm font-semibold text-text-primary flex items-center gap-2">
                <span className="text-violet-500">👥</span> Who should receive this?
              </p>
              <p className="text-xs text-text-secondary mt-0.5">Choose which customers will get this message</p>
            </div>

            <div className="flex items-center justify-between px-4 py-3 border border-border rounded-lg bg-bg-input hover:border-accent transition-colors cursor-pointer">
              <div className="flex items-center gap-3">
                <div className="w-7 h-7 rounded-full bg-blue-100 flex items-center justify-center">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#4F46E5" strokeWidth="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
                </div>
                <div>
                  <p className="text-sm font-medium text-text-primary">All Clients</p>
                  <p className="text-xs text-text-secondary">Everyone in your contact list</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-text-primary">{recipientCount.toLocaleString()} people</span>
                <ChevronDown size={14} className="text-text-muted" />
              </div>
            </div>

            <p className="text-xs text-text-secondary flex items-center gap-1.5">
              <span className="text-emerald-500">↗</span>
              This message will be sent to approximately <strong>{recipientCount.toLocaleString()} people</strong>.
              WhatsApp may limit delivery if your quality rating is low.
            </p>
          </div>

          {/* Step 4 — When */}
          <div className="card space-y-4">
            <div>
              <p className="text-sm font-semibold text-text-primary flex items-center gap-2">
                <span className="text-amber-500">📅</span> When should it be sent?
              </p>
              <p className="text-xs text-text-secondary mt-0.5">Send it now or pick a time that works better for your customers</p>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <button
                onClick={() => setSendMode('now')}
                className={`flex items-center gap-3 px-4 py-3 rounded-xl border-2 transition-all text-left ${
                  sendMode === 'now'
                    ? 'border-text-primary bg-gray-900 text-white'
                    : 'border-border bg-white hover:border-accent'
                }`}
              >
                <Send size={16} className={sendMode === 'now' ? 'text-white' : 'text-text-secondary'} />
                <div>
                  <p className={`text-sm font-semibold ${sendMode === 'now' ? 'text-white' : 'text-text-primary'}`}>
                    Send Now
                  </p>
                  <p className={`text-xs ${sendMode === 'now' ? 'text-gray-300' : 'text-text-secondary'}`}>
                    Goes out immediately
                  </p>
                </div>
                {sendMode === 'now' && (
                  <div className="ml-auto w-4 h-4 rounded-full border-2 border-white flex items-center justify-center">
                    <div className="w-2 h-2 rounded-full bg-white" />
                  </div>
                )}
              </button>

              <button
                onClick={() => setSendMode('later')}
                className={`flex items-center gap-3 px-4 py-3 rounded-xl border-2 transition-all text-left ${
                  sendMode === 'later'
                    ? 'border-text-primary bg-gray-900 text-white'
                    : 'border-border bg-white hover:border-accent'
                }`}
              >
                <Clock size={16} className={sendMode === 'later' ? 'text-white' : 'text-text-secondary'} />
                <div>
                  <p className={`text-sm font-semibold ${sendMode === 'later' ? 'text-white' : 'text-text-primary'}`}>
                    Schedule for Later
                  </p>
                  <p className={`text-xs ${sendMode === 'later' ? 'text-gray-300' : 'text-text-secondary'}`}>
                    Choose a date and time
                  </p>
                </div>
              </button>
            </div>

            {sendMode === 'later' && (
              <input
                type="datetime-local"
                value={scheduledAt}
                onChange={e => setScheduledAt(e.target.value)}
                className="w-full bg-bg-input border border-border rounded-lg px-3 py-2.5 text-sm text-text-primary focus:outline-none focus:border-accent"
              />
            )}
          </div>

          {/* Step 5 — Ready to send */}
          <div className="card !py-4 flex items-center justify-between">
            <div>
              <p className="text-sm font-semibold text-text-primary">Ready to send?</p>
              <p className="text-xs text-text-secondary">
                {recipientCount.toLocaleString()} customers will receive this message on WhatsApp right away.
              </p>
            </div>
            <button
              id="send-broadcast-final-btn"
              className="flex items-center gap-2 px-5 py-2.5 text-sm font-semibold text-white rounded-xl transition-colors disabled:opacity-50"
              style={{ background: '#111827' }}
              disabled={!message || sendMutation.isPending}
              onClick={() => sendMutation.mutate()}
            >
              <Send size={14} /> Send Broadcast
            </button>
          </div>
        </div>

        {/* ── RIGHT PANEL: Preview + Summary ───────────────────── */}
        <div className="w-72 shrink-0 space-y-4">

          {/* Live Preview */}
          <div className="card !p-4 space-y-3">
            <div>
              <p className="text-sm font-semibold text-text-primary">Live Preview</p>
              <p className="text-xs text-text-secondary">See exactly what your customer will receive</p>
            </div>
            <LivePreview message={message} />
          </div>

          {/* Broadcast Summary */}
          <div className="card !p-4 space-y-3">
            <p className="text-sm font-semibold text-text-primary">Broadcast Summary</p>
            <div className="space-y-2 text-xs">
              <div className="flex justify-between">
                <span className="text-text-secondary">Recipients</span>
                <span className="font-semibold text-text-primary">{recipientCount.toLocaleString()} people</span>
              </div>
              <div className="flex justify-between">
                <span className="text-text-secondary">Audience</span>
                <span className="font-semibold text-text-primary">All Clients</span>
              </div>
              <div className="flex justify-between">
                <span className="text-text-secondary">Sending</span>
                <span className="font-semibold text-text-primary capitalize">
                  {sendMode === 'now' ? 'Immediately' : scheduledAt ? new Date(scheduledAt).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : 'Scheduled'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-text-secondary">Message length</span>
                <span className={`font-semibold ${charCount > 480 ? 'text-danger' : 'text-text-primary'}`}>
                  {charCount > 0 ? `${charCount} characters` : '—'}
                </span>
              </div>
            </div>

            {/* Quality warning */}
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-700 leading-relaxed">
              <span className="font-semibold">⚠ Sending quality is low.</span>{' '}
              Avoid sending too often. Give customers value, not just ads.
            </div>
          </div>
        </div>
        </div>
      </>
      ) : (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
          <DataTable
            columns={[
              {
                key: 'name',
                label: 'Campaign Name',
                render: b => (
                  <Link to={`/broadcasts/${b.id}`} className="font-semibold text-gray-900 hover:text-emerald-600 transition-colors">
                    {b.name || 'Untitled Campaign'}
                  </Link>
                )
              },
              {
                key: 'status',
                label: 'Status',
                render: b => <StatusBadge status={b.status} />
              },
              {
                key: 'created_at',
                label: 'Date',
                render: b => b.created_at ? format(new Date(b.created_at), 'd MMM yyyy, h:mm a') : '—'
              },
              {
                key: 'total_recipients',
                label: 'Recipients',
                render: b => <span className="text-gray-500">{b.total_recipients || 0}</span>
              },
              {
                key: 'stats',
                label: 'Delivery Stats',
                render: b => {
                  const tot = Math.max(b.total_recipients || 1, 1)
                  const deliv = Math.round(((b.delivered_count || 0) / tot) * 100)
                  const read = Math.round(((b.read_count || 0) / tot) * 100)
                  return (
                    <div className="flex items-center gap-4 text-xs font-medium">
                      <span className="text-blue-600 flex items-center gap-1"><CheckCheck size={12}/>{deliv}% Deliv</span>
                      <span className="text-emerald-600 flex items-center gap-1"><CheckCheck size={12}/>{read}% Read</span>
                    </div>
                  )
                }
              }
            ]}
            data={historyData?.broadcasts || []}
            isLoading={historyLoading}
            emptyMessage="No broadcasts have been sent yet."
            pagination={{
              page: historyPage,
              totalPages: historyData?.total_pages || 1,
              onPageChange: setHistoryPage,
              totalItems: historyData?.total || 0,
            }}
          />
        </div>
      )}
    </div>
  )
}
