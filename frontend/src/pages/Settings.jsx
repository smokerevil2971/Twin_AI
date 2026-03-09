import { useState, useRef } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  Building2, Phone, Globe, Upload, ImageIcon, X, Check,
  Wifi, WifiOff, RefreshCw, Bell, Lock, LogOut,
  Trash2, ShieldAlert, ChevronDown, Shield,
} from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import api from '../api/client'

const LANGUAGES = ['English','Hindi','French','Arabic','Swahili']

function SectionCard({ title, description, icon: Icon, children }) {
  return (
    <div className="bg-white rounded-2xl border border-gray-100 overflow-hidden">
      <div className="px-6 py-4 border-b border-gray-50 flex items-center gap-3">
        <div className="w-8 h-8 rounded-xl bg-gray-50 flex items-center justify-center shrink-0"><Icon size={15} className="text-gray-500" /></div>
        <div>
          <h2 className="text-sm font-semibold text-gray-900">{title}</h2>
          <p className="text-xs text-gray-400">{description}</p>
        </div>
      </div>
      <div className="px-6 py-5">{children}</div>
    </div>
  )
}

function FieldLabel({ children, hint }) {
  return (
    <div className="mb-1.5">
      <label className="text-xs font-medium text-gray-600 block">{children}</label>
      {hint && <p className="text-[11px] text-gray-400 mt-0.5">{hint}</p>}
    </div>
  )
}

function Toggle({ checked, onChange, label, description }) {
  return (
    <div className="flex items-start justify-between gap-4 py-3.5 border-b border-gray-50 last:border-0">
      <div className="flex-1 min-w-0">
        <p className="text-sm text-gray-800">{label}</p>
        <p className="text-xs text-gray-400 mt-0.5 leading-relaxed">{description}</p>
      </div>
      <button role="switch" aria-checked={checked} onClick={() => onChange(!checked)}
        className={`relative shrink-0 mt-0.5 w-11 h-6 rounded-full transition-colors duration-200 focus:outline-none ${checked ? 'bg-gray-900' : 'bg-gray-200'}`}>
        <span className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow-sm transition-transform duration-200 ${checked ? 'translate-x-5' : 'translate-x-0'}`} />
      </button>
    </div>
  )
}

function QualityPill({ rating }) {
  const config = {
    good: { label:'Good',              bg:'bg-emerald-50', text:'text-emerald-700', dot:'bg-emerald-400', border:'border-emerald-100', tip:'Your account is in good standing. Keep sending helpful messages!' },
    fair: { label:'Fair',              bg:'bg-amber-50',   text:'text-amber-700',   dot:'bg-amber-400',   border:'border-amber-100',   tip:'Your rating is average. Try to personalise messages more and reduce broadcast frequency.' },
    poor: { label:'Poor — Action Needed', bg:'bg-red-50', text:'text-red-700',    dot:'bg-red-400',     border:'border-red-100',     tip:'Too many customers are marking your messages as spam. Reduce broadcasts immediately.' },
  }[rating]
  return (
    <div className={`flex items-start gap-3 px-4 py-3.5 rounded-xl ${config.bg} border ${config.border}`}>
      <div className="flex items-center gap-2 shrink-0 mt-0.5">
        <span className={`w-2.5 h-2.5 rounded-full ${config.dot} animate-pulse`} />
        <span className={`text-xs font-semibold ${config.text}`}>{config.label}</span>
      </div>
      <p className={`text-xs ${config.text} opacity-80 leading-relaxed`}>{config.tip}</p>
    </div>
  )
}

function SaveToast({ show }) {
  return (
    <div className={`fixed bottom-6 left-1/2 -translate-x-1/2 flex items-center gap-2 bg-gray-900 text-white text-xs px-4 py-2.5 rounded-full shadow-lg transition-all duration-300 z-50 ${show ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-2 pointer-events-none'}`}>
      <Check size={13} className="text-emerald-400" /> Changes saved successfully
    </div>
  )
}

function DeleteModal({ onClose, onConfirm }) {
  const [confirmation, setConfirmation] = useState('')
  const confirmed = confirmation.toLowerCase() === 'delete'
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/20 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-sm mx-4 p-6">
        <div className="flex items-start gap-3 mb-5">
          <div className="w-10 h-10 rounded-full bg-red-50 flex items-center justify-center shrink-0"><ShieldAlert size={18} className="text-red-500" /></div>
          <div>
            <h3 className="text-sm font-semibold text-gray-900 mb-1">Delete your account?</h3>
            <p className="text-xs text-gray-500 leading-relaxed">This will permanently delete your business data, all clients, conversations, and broadcasts. <strong className="text-gray-700">This cannot be undone.</strong></p>
          </div>
        </div>
        <div className="mb-4">
          <label className="text-xs font-medium text-gray-600 block mb-1.5">Type <span className="font-mono bg-gray-100 px-1 py-0.5 rounded text-red-500">delete</span> to confirm</label>
          <input type="text" value={confirmation} onChange={e => setConfirmation(e.target.value)} placeholder="delete"
            className="w-full px-3.5 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-1 focus:ring-red-200" />
        </div>
        <div className="flex gap-2">
          <button onClick={onClose} className="flex-1 px-4 py-2.5 text-sm text-gray-600 bg-gray-50 border border-gray-100 rounded-xl hover:bg-gray-100 transition-colors">Cancel</button>
          <button disabled={!confirmed} onClick={onConfirm} className="flex-1 px-4 py-2.5 text-sm text-white bg-red-500 rounded-xl hover:bg-red-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">Delete Account</button>
        </div>
      </div>
    </div>
  )
}

function ChangePasswordModal({ onClose }) {
  const [current, setCurrent] = useState('')
  const [next, setNext]       = useState('')
  const [confirm, setConfirm] = useState('')
  const [apiError, setApiError] = useState('')
  const valid = current && next.length >= 8 && next === confirm

  const changePwMutation = useMutation({
    mutationFn: () => api.post('/auth/change-password', { current_password: current, new_password: next }),
    onSuccess: () => { toast.success('Password updated'); onClose() },
    onError: (err) => {
      const msg = err?.response?.data?.detail || 'Failed to update password'
      setApiError(msg)
    },
  })

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/20 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-sm mx-4 p-6">
        <div className="flex items-center justify-between mb-5">
          <div>
            <h3 className="text-sm font-semibold text-gray-900">Change Password</h3>
            <p className="text-xs text-gray-400 mt-0.5">Choose a strong password you haven't used before.</p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-gray-50 text-gray-400 transition-colors"><X size={15} /></button>
        </div>
        <div className="space-y-3 mb-5">
          {[
            { label:'Current password', value:current, set:setCurrent, placeholder:'Enter current password'  },
            { label:'New password',     value:next,    set:setNext,    placeholder:'At least 8 characters'   },
            { label:'Confirm new password', value:confirm, set:setConfirm, placeholder:'Type it again'       },
          ].map(({ label, value, set, placeholder }) => (
            <div key={label}>
              <label className="text-xs font-medium text-gray-600 block mb-1.5">{label}</label>
              <input type="password" value={value} onChange={e => { set(e.target.value); setApiError('') }} placeholder={placeholder}
                className="w-full px-3.5 py-2.5 bg-gray-50 border border-gray-100 rounded-xl text-sm text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-gray-200 focus:bg-white transition" />
            </div>
          ))}
          {next && confirm && next !== confirm && <p className="text-xs text-red-500">Passwords don't match.</p>}
          {apiError && <p className="text-xs text-red-500">{apiError}</p>}
        </div>
        <div className="flex gap-2">
          <button onClick={onClose} className="flex-1 px-4 py-2.5 text-sm text-gray-600 bg-gray-50 border border-gray-100 rounded-xl hover:bg-gray-100 transition-colors">Cancel</button>
          <button disabled={!valid || changePwMutation.isPending} onClick={() => changePwMutation.mutate()}
            className="flex-1 px-4 py-2.5 text-sm text-white bg-gray-900 rounded-xl hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-1.5">
            <Check size={13} /> {changePwMutation.isPending ? 'Saving…' : 'Update Password'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default function Settings() {
  const { logout } = useAuth()

  // ── Load tenant profile ───────────────────────────────────────────────────
  const { data: profile } = useQuery({
    queryKey: ['me'],
    queryFn: () => api.get('/auth/me').then(r => r.data?.data),
  })

  const [businessName, setBusinessName] = useState('')
  const [contactPhone, setContactPhone] = useState(
    () => localStorage.getItem('settings_phone') || '+91 98765 43210'
  )
  const [language, setLanguage] = useState(
    () => localStorage.getItem('settings_language') || 'English'
  )
  const [langOpen, setLangOpen]         = useState(false)
  const [logoFile, setLogoFile]         = useState(null)
  const [logoPreview, setLogoPreview]   = useState(null)
  const logoRef = useRef(null)

  // Sync business name from API once loaded
  const displayName = businessName || profile?.business_name || ''

  const [isConnected]  = useState(true)
  const [qualityRating] = useState('fair')
  const [reconnecting, setReconnecting] = useState(false)

  const [notifyBroadcastFail, setNotifyBroadcastFail] = useState(
    () => localStorage.getItem('notify_broadcast_fail') !== 'false'
  )
  const [notifyBotStuck, setNotifyBotStuck] = useState(
    () => localStorage.getItem('notify_bot_stuck') !== 'false'
  )
  const [notifyDailySummary, setNotifyDailySummary] = useState(
    () => localStorage.getItem('notify_daily_summary') === 'true'
  )

  const [showToast,    setShowToast]    = useState(false)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [showPasswordModal, setShowPasswordModal] = useState(false)

  // ── Mutations ────────────────────────────────────────────────────────────
  const saveMutation = useMutation({
    mutationFn: () => api.patch('/auth/me', { business_name: displayName }),
    onSuccess: () => { setShowToast(true); setTimeout(() => setShowToast(false), 2500) },
    onError: () => toast.error('Failed to save changes'),
  })

  const deleteMutation = useMutation({
    mutationFn: () => api.delete('/auth/account'),
    onSuccess: () => logout(),
    onError: () => toast.error('Failed to delete account'),
  })

  function handleLogoFile(e) {
    const f = e.target.files?.[0]; if (!f) return
    setLogoFile(f.name); setLogoPreview(URL.createObjectURL(f)); e.target.value = ''
  }
  function handleSave() {
    // Persist local-only settings to localStorage
    localStorage.setItem('settings_phone', contactPhone)
    localStorage.setItem('settings_language', language)
    localStorage.setItem('notify_broadcast_fail', String(notifyBroadcastFail))
    localStorage.setItem('notify_bot_stuck', String(notifyBotStuck))
    localStorage.setItem('notify_daily_summary', String(notifyDailySummary))
    // Persist business name to DB
    saveMutation.mutate()
  }
  function handleReconnect() { setReconnecting(true); setTimeout(() => setReconnecting(false), 2000) }

  return (
    <div className="flex-1 flex flex-col h-screen overflow-hidden bg-gray-50/60 -mx-8 -my-7">
      <div className="h-16 bg-white border-b border-gray-100 px-8 flex items-center shrink-0 sticky top-0 z-10">
        <div>
          <h1 className="text-base font-semibold text-gray-900">Settings</h1>
          <p className="text-xs text-gray-400">Manage your business info and preferences</p>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-8 py-6">
        <div className="max-w-2xl mx-auto space-y-5">

          {/* 1. Business Information */}
          <SectionCard title="Business Information" description="How your business appears to customers" icon={Building2}>
            <div className="space-y-5">
              <div>
                <FieldLabel hint="Used in your messages and account">Business Logo</FieldLabel>
                <div className="flex items-center gap-4">
                  <div className="w-16 h-16 rounded-2xl bg-gray-100 border border-gray-100 flex items-center justify-center overflow-hidden shrink-0">
                    {logoPreview ? <img src={logoPreview} alt="Logo" className="w-full h-full object-cover" /> : <ImageIcon size={22} className="text-gray-300" />}
                  </div>
                  <div className="flex-1">
                    <input ref={logoRef} type="file" accept=".jpg,.jpeg,.png,.webp,.svg" className="hidden" onChange={handleLogoFile} />
                    {logoFile ? (
                      <div className="flex items-center gap-2 bg-blue-50 border border-blue-100 px-3 py-2 rounded-xl">
                        <ImageIcon size={13} className="text-blue-500 shrink-0" />
                        <span className="text-xs text-blue-700 flex-1 truncate">{logoFile}</span>
                        <button onClick={() => { setLogoFile(null); setLogoPreview(null) }} className="text-blue-400 hover:text-blue-600 transition-colors shrink-0"><X size={12} /></button>
                      </div>
                    ) : (
                      <button onClick={() => logoRef.current?.click()}
                        className="flex items-center gap-2 px-3.5 py-2 border border-gray-200 border-dashed rounded-xl text-xs text-gray-500 hover:bg-gray-50 hover:border-gray-300 transition-colors">
                        <Upload size={13} className="text-gray-400" /> Upload logo
                      </button>
                    )}
                    <p className="text-[11px] text-gray-400 mt-1.5">PNG, JPG or SVG · Max 2 MB</p>
                  </div>
                </div>
              </div>
              <div>
                <FieldLabel hint="This is the name your customers see">Business Name</FieldLabel>
                <input type="text" value={displayName} onChange={e => setBusinessName(e.target.value)}
                  className="w-full px-3.5 py-2.5 bg-gray-50 border border-gray-100 rounded-xl text-sm text-gray-800 focus:outline-none focus:ring-1 focus:ring-gray-200 focus:bg-white transition" />
              </div>
              <div>
                <FieldLabel hint="Your main contact number (not your WhatsApp line)">Contact Phone</FieldLabel>
                <input type="tel" value={contactPhone} onChange={e => setContactPhone(e.target.value)}
                  className="w-full px-3.5 py-2.5 bg-gray-50 border border-gray-100 rounded-xl text-sm text-gray-800 focus:outline-none focus:ring-1 focus:ring-gray-200 focus:bg-white transition" />
              </div>
              <div>
                <FieldLabel hint="The language your AI assistant will use to reply to customers">Default Language</FieldLabel>
                <div className="relative">
                  <button onClick={() => setLangOpen(!langOpen)}
                    className="w-full flex items-center justify-between px-3.5 py-2.5 bg-gray-50 border border-gray-100 rounded-xl text-sm text-gray-700 hover:bg-white focus:outline-none focus:ring-1 focus:ring-gray-200 transition">
                    <div className="flex items-center gap-2"><Globe size={14} className="text-gray-400" /><span>{language}</span></div>
                    <ChevronDown size={13} className={`text-gray-400 transition-transform ${langOpen ? 'rotate-180' : ''}`} />
                  </button>
                  {langOpen && (
                    <div className="absolute left-0 right-0 top-full mt-1 bg-white border border-gray-100 rounded-xl shadow-lg z-20 overflow-hidden">
                      {LANGUAGES.map(lang => (
                        <button key={lang} onClick={() => { setLanguage(lang); setLangOpen(false) }}
                          className="w-full flex items-center justify-between px-4 py-2.5 text-sm text-left hover:bg-gray-50 transition-colors text-gray-700">
                          {lang}{language === lang && <Check size={13} className="text-emerald-500" />}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
              <div className="flex justify-end pt-1">
                <button onClick={handleSave} disabled={saveMutation.isPending}
                  className="flex items-center gap-1.5 px-5 py-2.5 text-sm text-white bg-gray-900 rounded-xl hover:bg-gray-700 disabled:opacity-60 transition-colors">
                  <Check size={14} /> {saveMutation.isPending ? 'Saving…' : 'Save Changes'}
                </button>
              </div>
            </div>
          </SectionCard>

          {/* 2. WhatsApp Configuration */}
          <SectionCard title="WhatsApp Configuration" description="Your connected WhatsApp Business number" icon={isConnected ? Wifi : WifiOff}>
            <div className="space-y-4">
              <div className="flex items-center justify-between py-3 border-b border-gray-50">
                <div>
                  <p className="text-xs text-gray-400 mb-0.5">Connected Number</p>
                  <p className="text-sm font-semibold text-gray-800">+91 98765 43210</p>
                </div>
                <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium ${isConnected ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-600'}`}>
                  <span className={`w-1.5 h-1.5 rounded-full ${isConnected ? 'bg-emerald-400' : 'bg-red-400'}`} />
                  {isConnected ? 'Connected' : 'Not Connected'}
                </div>
              </div>
              <div className="flex items-center justify-between py-3 border-b border-gray-50">
                <div>
                  <p className="text-sm text-gray-700">Reconnect WhatsApp</p>
                  <p className="text-xs text-gray-400 mt-0.5">Use this if your messages stop sending or the bot goes offline.</p>
                </div>
                <button onClick={handleReconnect} disabled={reconnecting}
                  className="flex items-center gap-1.5 px-4 py-2 text-xs font-medium text-gray-700 bg-gray-100 rounded-xl hover:bg-gray-200 disabled:opacity-60 transition-colors shrink-0 ml-4">
                  <RefreshCw size={13} className={reconnecting ? 'animate-spin' : ''} />
                  {reconnecting ? 'Reconnecting…' : 'Reconnect WhatsApp'}
                </button>
              </div>
              <div>
                <p className="text-xs font-medium text-gray-600 mb-2">WhatsApp Quality Rating</p>
                <QualityPill rating={qualityRating} />
                <p className="text-[11px] text-gray-400 mt-2 leading-relaxed">WhatsApp gives every business a quality rating based on how customers interact with your messages. A good rating means your messages keep getting delivered.</p>
              </div>
            </div>
          </SectionCard>

          {/* 3. Notifications */}
          <SectionCard title="Notification Preferences" description="Choose when you want to receive email alerts" icon={Bell}>
            <div>
              <Toggle checked={notifyBroadcastFail} onChange={setNotifyBroadcastFail}
                label="Alert me when a broadcast fails"
                description="You'll get an email if a large number of messages in a broadcast couldn't be delivered." />
              <Toggle checked={notifyBotStuck} onChange={setNotifyBotStuck}
                label="Alert me when the bot can't answer"
                description="You'll be notified when a customer asks something your AI assistant doesn't know how to answer." />
              <Toggle checked={notifyDailySummary} onChange={setNotifyDailySummary}
                label="Send me a daily performance summary"
                description="Receive a short email each morning summarising yesterday's message activity and customer replies." />
            </div>
          </SectionCard>

          {/* 4. Account */}
          <SectionCard title="Account" description="Manage your login and account access" icon={Shield}>
            <div className="space-y-2">
              <button onClick={() => setShowPasswordModal(true)}
                className="w-full flex items-center gap-3 px-4 py-3.5 rounded-xl hover:bg-gray-50 transition-colors group text-left border border-gray-100">
                <div className="w-8 h-8 rounded-xl bg-gray-50 flex items-center justify-center shrink-0 group-hover:bg-gray-100 transition-colors"><Lock size={14} className="text-gray-500" /></div>
                <div className="flex-1"><p className="text-sm text-gray-800">Change Password</p><p className="text-xs text-gray-400 mt-0.5">Update your login password</p></div>
                <ChevronDown size={13} className="text-gray-400 -rotate-90" />
              </button>
              <button onClick={logout}
                className="w-full flex items-center gap-3 px-4 py-3.5 rounded-xl hover:bg-gray-50 transition-colors group text-left border border-gray-100">
                <div className="w-8 h-8 rounded-xl bg-gray-50 flex items-center justify-center shrink-0 group-hover:bg-gray-100 transition-colors"><LogOut size={14} className="text-gray-500" /></div>
                <div className="flex-1"><p className="text-sm text-gray-800">Log Out</p><p className="text-xs text-gray-400 mt-0.5">Sign out of your account on this device</p></div>
                <ChevronDown size={13} className="text-gray-400 -rotate-90" />
              </button>
              <div className="pt-3 mt-2 border-t border-gray-50">
                <button onClick={() => setShowDeleteModal(true)} className="flex items-center gap-1.5 text-xs text-red-400 hover:text-red-600 transition-colors">
                  <Trash2 size={12} /> Delete my account and all data
                </button>
                <p className="text-[11px] text-gray-400 mt-1">This permanently deletes your business, clients, products, and all conversations. This cannot be reversed.</p>
              </div>
            </div>
          </SectionCard>

          <div className="pb-4" />
        </div>
      </div>

      <SaveToast show={showToast} />
      {showDeleteModal    && <DeleteModal onClose={() => setShowDeleteModal(false)} onConfirm={() => deleteMutation.mutate()} />}
      {showPasswordModal  && <ChangePasswordModal onClose={() => setShowPasswordModal(false)} />}
    </div>
  )
}
