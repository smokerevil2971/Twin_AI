import { useState, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Search, Upload, UserPlus, Pencil, Trash2,
  ChevronLeft, ChevronRight, X, Check,
  CheckCircle2, AlertCircle, Phone, Mail, Globe, Users, ChevronDown, Download, UserCheck,
} from 'lucide-react'
import api from '../api/client'
import toast from 'react-hot-toast'
import { format } from 'date-fns'
import clsx from 'clsx'

const ROWS = 10
const LANG_COLORS = {
  EN: 'bg-blue-50 text-blue-700',
  HI: 'bg-orange-50 text-orange-700',
  FR: 'bg-violet-50 text-violet-700',
  AR: 'bg-emerald-50 text-emerald-700',
}
const AVATAR_BG = [
  'bg-violet-100 text-violet-600','bg-blue-100 text-blue-600',
  'bg-emerald-100 text-emerald-600','bg-amber-100 text-amber-600',
  'bg-rose-100 text-rose-600','bg-sky-100 text-sky-600',
  'bg-indigo-100 text-indigo-600','bg-orange-100 text-orange-600',
]
function initials(name) { return (name||'').split(' ').map(w=>w[0]).join('').toUpperCase().slice(0,2) }
function avatarBg(id)   { return AVATAR_BG[(parseInt(id,10)||0) % AVATAR_BG.length] }

function Toggle({ value, onChange }) {
  return (
    <button
      onClick={onChange}
      className={`relative inline-flex w-9 h-5 rounded-full transition-colors focus:outline-none ${value ? 'bg-emerald-500' : 'bg-gray-200'}`}
    >
      <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow-sm transition-transform ${value ? 'translate-x-4' : 'translate-x-0'}`} />
    </button>
  )
}

function ClientModal({ client, onSave, onClose }) {
  const [name, setName]     = useState(client?.name || '')
  const [phone, setPhone]   = useState(client?.phone || '')
  const [email, setEmail]   = useState(client?.email || '')
  const [optedIn, setOptedIn] = useState(client?.opted_in ?? true)
  const [lang, setLang]     = useState(client?.language || 'EN')
  const valid = name.trim() && phone.trim()

  function submit(e) {
    e.preventDefault()
    if (!valid) return
    onSave({ name: name.trim(), phone: phone.trim(), email: email.trim(), opted_in: optedIn, language: lang })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/20 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden">
        <div className="px-6 pt-6 pb-4 border-b border-gray-100 flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold text-gray-900">{client ? 'Edit Client' : 'Add New Client'}</h2>
            <p className="text-xs text-gray-400 mt-0.5">{client ? "Update this client's details." : 'Add a new customer to your contact list.'}</p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-gray-50 text-gray-400 hover:text-gray-600 transition-colors"><X size={16} /></button>
        </div>
        <form onSubmit={submit} className="px-6 py-5 space-y-4">
          <div>
            <label className="text-xs font-medium text-gray-600 block mb-1.5">Full Name *</label>
            <input type="text" value={name} onChange={e=>setName(e.target.value)} placeholder="e.g. Rahul Sharma"
              className="w-full px-3.5 py-2.5 bg-gray-50 border border-gray-100 rounded-xl text-sm text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-gray-200 focus:bg-white transition" />
          </div>
          <div>
            <label className="text-xs font-medium text-gray-600 block mb-1.5">WhatsApp Number *</label>
            <div className="relative">
              <Phone size={13} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
              <input type="tel" value={phone} onChange={e=>setPhone(e.target.value)} placeholder="+91 98765 43210"
                className="w-full pl-9 pr-3.5 py-2.5 bg-gray-50 border border-gray-100 rounded-xl text-sm text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-gray-200 focus:bg-white transition" />
            </div>
          </div>
          <div>
            <label className="text-xs font-medium text-gray-600 block mb-1.5">Email Address</label>
            <div className="relative">
              <Mail size={13} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
              <input type="email" value={email} onChange={e=>setEmail(e.target.value)} placeholder="e.g. rahul@gmail.com"
                className="w-full pl-9 pr-3.5 py-2.5 bg-gray-50 border border-gray-100 rounded-xl text-sm text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-gray-200 focus:bg-white transition" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-medium text-gray-600 block mb-1.5"><Globe size={11} className="inline mr-1 text-gray-400" />Language</label>
              <select value={lang} onChange={e=>setLang(e.target.value)}
                className="w-full px-3.5 py-2.5 bg-gray-50 border border-gray-100 rounded-xl text-sm text-gray-700 focus:outline-none focus:ring-1 focus:ring-gray-200 focus:bg-white transition appearance-none cursor-pointer">
                <option value="EN">English</option><option value="HI">Hindi</option>
                <option value="FR">French</option><option value="AR">Arabic</option>
              </select>
            </div>
            <div>
              <label className="text-xs font-medium text-gray-600 block mb-1.5">Receives Messages?</label>
              <div className={`flex items-center gap-2.5 px-3.5 py-2.5 rounded-xl border cursor-pointer transition-colors ${optedIn ? 'bg-emerald-50 border-emerald-100' : 'bg-gray-50 border-gray-100'}`}
                onClick={() => setOptedIn(!optedIn)}>
                <Toggle value={optedIn} onChange={() => setOptedIn(!optedIn)} />
                <span className={`text-xs font-medium ${optedIn ? 'text-emerald-700' : 'text-gray-400'}`}>{optedIn ? 'Yes' : 'No'}</span>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2 pt-2">
            <button type="button" onClick={onClose}
              className="flex-1 px-4 py-2.5 text-sm text-gray-600 bg-gray-50 border border-gray-100 rounded-xl hover:bg-gray-100 transition-colors">Cancel</button>
            <button type="submit" disabled={!valid}
              className="flex-1 px-4 py-2.5 text-sm text-white bg-gray-900 rounded-xl hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-1.5">
              <Check size={14} /> {client ? 'Save Changes' : 'Add Client'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function DeleteConfirm({ name, onConfirm, onClose }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/20 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-sm mx-4 p-6">
        <div className="flex items-start gap-3 mb-5">
          <div className="w-9 h-9 rounded-full bg-red-50 flex items-center justify-center shrink-0"><Trash2 size={15} className="text-red-500" /></div>
          <div>
            <h3 className="text-sm font-semibold text-gray-900 mb-1">Remove this client?</h3>
            <p className="text-xs text-gray-500 leading-relaxed"><span className="font-medium text-gray-700">{name}</span> will be removed. This cannot be undone.</p>
          </div>
        </div>
        <div className="flex gap-2">
          <button onClick={onClose} className="flex-1 px-4 py-2.5 text-sm text-gray-600 bg-gray-50 border border-gray-100 rounded-xl hover:bg-gray-100 transition-colors">Keep Client</button>
          <button onClick={onConfirm} className="flex-1 px-4 py-2.5 text-sm text-white bg-red-500 rounded-xl hover:bg-red-600 transition-colors">Yes, Remove</button>
        </div>
      </div>
    </div>
  )
}

// ─── Bulk Opt-In Confirm Modal ─────────────────────────────────────────────────
function BulkOptInModal({ onConfirm, onClose, isPending }) {
  const [input, setInput] = useState('')
  const ready = input.trim().toLowerCase() === 'opt in all'
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/20 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-sm mx-4 p-6">
        <div className="flex items-start gap-3 mb-4">
          <div className="w-10 h-10 rounded-full bg-emerald-50 flex items-center justify-center shrink-0"><UserCheck size={18} className="text-emerald-600" /></div>
          <div>
            <h3 className="text-sm font-semibold text-gray-900 mb-1">Bulk Opt-In All Clients?</h3>
            <p className="text-xs text-gray-500 leading-relaxed">
              This will mark <strong className="text-gray-700">all your clients</strong> as opted-in to WhatsApp messages.
              Only do this if you have confirmed each customer has given consent.
            </p>
          </div>
        </div>
        <div className="mb-4">
          <label className="text-xs font-medium text-gray-600 block mb-1.5">Type <span className="font-mono bg-gray-100 px-1 py-0.5 rounded text-emerald-600">opt in all</span> to confirm</label>
          <input type="text" value={input} onChange={e => setInput(e.target.value)} placeholder="opt in all"
            className="w-full px-3.5 py-2.5 bg-gray-50 border border-gray-100 rounded-xl text-sm focus:outline-none focus:ring-1 focus:ring-emerald-200" />
        </div>
        <div className="flex gap-2">
          <button onClick={onClose} className="flex-1 px-4 py-2.5 text-sm text-gray-600 bg-gray-50 border border-gray-100 rounded-xl hover:bg-gray-100 transition-colors">Cancel</button>
          <button disabled={!ready || isPending} onClick={onConfirm}
            className="flex-1 px-4 py-2.5 text-sm text-white bg-emerald-600 rounded-xl hover:bg-emerald-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
            {isPending ? 'Processing…' : 'Opt In All'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default function Clients() {
  const qc = useQueryClient()
  const fileRef = useRef(null)
  const [search, setSearch] = useState('')
  const [tagFilter, setTagFilter] = useState('all')
  const [tagDropOpen, setTagDropOpen] = useState(false)
  const [page, setPage] = useState(1)
  const [showModal, setShowModal] = useState(false)
  const [editClient, setEditClient] = useState(null)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [uploadBanner, setUploadBanner] = useState(null)  // { msg, skipped: [] }
  const [showBulkModal, setShowBulkModal] = useState(false)

  const { data: clientsData = [], isLoading } = useQuery({
    queryKey: ['clients'],
    queryFn: () => api.get('/clients').then(r => r.data?.data?.clients || []),
    placeholderData: [],
  })

  const createMut = useMutation({
    mutationFn: d => api.post('/clients', d),
    onSuccess: () => { toast.success('Client added!'); qc.invalidateQueries(['clients']); setShowModal(false) },
    onError: e => toast.error(e?.response?.data?.detail || 'Failed to add client'),
  })
  const updateMut = useMutation({
    mutationFn: ({id,...d}) => api.patch(`/clients/${id}`, d),
    onSuccess: () => { toast.success('Client updated!'); qc.invalidateQueries(['clients']); setShowModal(false); setEditClient(null) },
    onError: e => toast.error(e?.response?.data?.detail || 'Failed to update'),
  })
  const deleteMut = useMutation({
    mutationFn: id => api.delete(`/clients/${id}`),
    onSuccess: () => { toast.success('Client removed'); qc.invalidateQueries(['clients']); setDeleteTarget(null) },
  })

  const bulkOptInMut = useMutation({
    mutationFn: () => api.post('/clients/bulk-opt-in', { confirmed: true }),
    onSuccess: (r) => {
      const count = r.data?.data?.opted_in_count ?? 0
      toast.success(`${count} client${count !== 1 ? 's' : ''} opted in`)
      qc.invalidateQueries(['clients'])
      setShowBulkModal(false)
    },
    onError: e => toast.error(e?.response?.data?.detail || 'Bulk opt-in failed'),
  })

  function handleSave(data) {
    if (editClient) updateMut.mutate({ id: editClient.id, ...data })
    else createMut.mutate(data)
  }
  function handleUpload(e) {
    const f = e.target.files?.[0]; if (!f) return
    const form = new FormData(); form.append('file', f)
    api.post('/clients/upload', form, { headers: { 'Content-Type': 'multipart/form-data' } })
      .then(r => {
        const summary = r.data?.data || {}
        const skipped = summary.skipped_records || []
        setUploadBanner({
          msg: `Imported from "${f.name}". ${summary.created ?? 0} added, ${summary.updated ?? 0} updated.`,
          skipped,
        })
        qc.invalidateQueries(['clients'])
        if (skipped.length === 0) setTimeout(() => setUploadBanner(null), 6000)
      })
      .catch(() => toast.error('Upload failed'))
    e.target.value = ''
  }
  async function handleDownloadSkipped() {
    if (!uploadBanner?.skipped?.length) return
    try {
      const res = await api.post('/clients/upload/skipped-export', uploadBanner.skipped, {
        responseType: 'blob',
        headers: { 'Content-Type': 'application/json' },
      })
      const url  = URL.createObjectURL(res.data)
      const link = document.createElement('a')
      link.href = url; link.download = 'skipped_clients.csv'
      document.body.appendChild(link); link.click()
      document.body.removeChild(link); URL.revokeObjectURL(url)
    } catch { toast.error('Export failed') }
  }

  const filtered = clientsData.filter(c => {
    const s = search.toLowerCase()
    const matchSearch = (c.name||'').toLowerCase().includes(s) || (c.phone||'').includes(s) || (c.email||'').toLowerCase().includes(s)
    const matchTag = tagFilter === 'all' || c.tag === tagFilter
    return matchSearch && matchTag
  })
  const totalPages = Math.max(1, Math.ceil(filtered.length / ROWS))
  const safePage = Math.min(page, totalPages)
  const paginated = filtered.slice((safePage-1)*ROWS, safePage*ROWS)
  const optedInCount = clientsData.filter(c => c.opted_in).length

  return (
    <div className="flex-1 flex flex-col h-screen overflow-hidden bg-gray-50/60 -mx-8 -my-7">
      {/* Top Bar */}
      <div className="h-16 bg-white border-b border-gray-100 px-8 flex items-center justify-between shrink-0 sticky top-0 z-10">
        <div>
          <h1 className="text-base font-semibold text-gray-900">Clients</h1>
          <p className="text-xs text-gray-400">Manage your customer contact list</p>
        </div>
        <div className="flex items-center gap-2">
          <input ref={fileRef} type="file" accept=".csv,.xlsx,.xls" className="hidden" onChange={handleUpload} />
          <button onClick={() => fileRef.current?.click()}
            className="flex items-center gap-1.5 px-3 py-2 text-xs text-gray-600 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors">
            <Upload size={13} className="text-gray-400" /> Upload CSV / Excel
          </button>
          <button onClick={() => setShowBulkModal(true)}
            className="flex items-center gap-1.5 px-3 py-2 text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg hover:bg-emerald-100 transition-colors">
            <UserCheck size={13} /> Bulk Opt-In All
          </button>
          <button onClick={() => { setEditClient(null); setShowModal(true) }}
            className="flex items-center gap-1.5 px-3 py-2 text-xs text-white bg-gray-900 rounded-lg hover:bg-gray-700 transition-colors">
            <UserPlus size={13} /> Add New Client
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-8 py-6 space-y-4">
        {/* Upload banner */}
        {uploadBanner && (
          <div className="flex items-center gap-3 bg-emerald-50 border border-emerald-200 text-emerald-800 px-4 py-3 rounded-xl">
            <CheckCircle2 size={16} className="text-emerald-500 shrink-0" />
            <span className="text-sm flex-1">{uploadBanner.msg}</span>
            {uploadBanner.skipped?.length > 0 && (
              <button onClick={handleDownloadSkipped}
                className="flex items-center gap-1.5 text-xs text-emerald-700 bg-white border border-emerald-200 px-2.5 py-1 rounded-lg hover:bg-emerald-50 transition-colors shrink-0">
                <Download size={12} /> Download {uploadBanner.skipped.length} skipped
              </button>
            )}
            <button onClick={() => setUploadBanner(null)} className="text-emerald-400 hover:text-emerald-600 shrink-0"><X size={14} /></button>
          </div>
        )}

        {/* Stat Cards */}
        <div className="grid grid-cols-3 gap-4">
          {[
            { label: 'Total Clients', value: clientsData.length, sub: 'In your contact list', color: 'bg-blue-50', icon: Users, iconColor: 'text-blue-500' },
            { label: 'Receiving Messages', value: optedInCount, sub: 'Have opted in to WhatsApp', color: 'bg-emerald-50', icon: CheckCircle2, iconColor: 'text-emerald-500' },
            { label: 'Not Receiving', value: clientsData.length - optedInCount, sub: 'Opted out or never set up', color: 'bg-red-50', icon: AlertCircle, iconColor: 'text-red-400' },
          ].map(({ label, value, sub, color, icon: Icon, iconColor }) => (
            <div key={label} className="bg-white rounded-xl border border-gray-100 px-5 py-4 flex items-center gap-4">
              <div className={`w-10 h-10 rounded-xl ${color} flex items-center justify-center shrink-0`}><Icon size={18} className={iconColor} /></div>
              <div>
                <p className="text-xs text-gray-400">{label}</p>
                <p className="text-2xl font-semibold text-gray-900 leading-tight">{value}</p>
                <p className="text-xs text-gray-400">{sub}</p>
              </div>
            </div>
          ))}
        </div>

        {/* Filter Bar */}
        <div className="bg-white rounded-xl border border-gray-100 flex items-center overflow-hidden">
          <div className="flex items-center flex-1 px-4 py-3 gap-3">
            <Search size={15} className="text-gray-400 shrink-0" />
            <input type="text" value={search} onChange={e=>{setSearch(e.target.value);setPage(1)}}
              placeholder="Search clients by name, phone, or email..."
              className="flex-1 text-sm text-gray-700 placeholder-gray-400 bg-transparent focus:outline-none" />
            {search && <button onClick={()=>{setSearch('');setPage(1)}} className="text-gray-300 hover:text-gray-500"><X size={13} /></button>}
          </div>
          <div className="w-px h-8 bg-gray-100 shrink-0" />
          <div className="relative">
            <button onClick={() => setTagDropOpen(!tagDropOpen)}
              className="flex items-center gap-2 px-4 py-3 text-sm text-gray-600 hover:bg-gray-50 transition-colors whitespace-nowrap">
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M1.75 2.625C1.75 2.28 2.03 2 2.375 2H11.625C11.97 2 12.25 2.28 12.25 2.625C12.25 2.97 11.97 3.25 11.625 3.25H2.375C2.03 3.25 1.75 2.97 1.75 2.625ZM3.5 7C3.5 6.655 3.78 6.375 4.125 6.375H9.875C10.22 6.375 10.5 6.655 10.5 7C10.5 7.345 10.22 7.625 9.875 7.625H4.125C3.78 7.625 3.5 7.345 3.5 7ZM5.25 11.375C5.25 11.03 5.53 10.75 5.875 10.75H8.125C8.47 10.75 8.75 11.03 8.75 11.375C8.75 11.72 8.47 12 8.125 12H5.875C5.53 12 5.25 11.72 5.25 11.375Z" fill="#9CA3AF"/></svg>
              <span className={tagFilter !== 'all' ? 'text-gray-900 font-medium' : 'text-gray-500'}>{tagFilter === 'all' ? 'All Tags' : tagFilter}</span>
              <ChevronDown size={13} className={`text-gray-400 transition-transform ${tagDropOpen ? 'rotate-180' : ''}`} />
            </button>
            {tagDropOpen && (
              <div className="absolute right-0 top-full mt-1 w-36 bg-white border border-gray-100 rounded-xl shadow-lg z-20 overflow-hidden">
                {['all','VIP','New'].map(t => (
                  <button key={t} onClick={() => { setTagFilter(t); setTagDropOpen(false); setPage(1) }}
                    className={`w-full flex items-center justify-between px-4 py-2.5 text-sm text-left hover:bg-gray-50 transition-colors ${tagFilter===t ? 'text-gray-900' : 'text-gray-600'}`}>
                    {t === 'all' ? 'All Tags' : t}
                    {tagFilter === t && <Check size={13} className="text-emerald-500" />}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Table */}
        <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
          <div className="px-5 py-3.5 border-b border-gray-50">
            <p className="text-xs text-gray-500">Showing <span className="font-medium text-gray-700">{filtered.length}</span> client{filtered.length !== 1 ? 's' : ''}</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="bg-gray-50/80 border-b border-gray-100">
                  {['Name','Phone Number','Email','Receiving Messages','Language','Added On','Actions'].map(h => (
                    <th key={h} className={`px-${h === 'Name' ? '5' : '4'} py-3 text-${h === 'Receiving Messages' || h === 'Language' || h === 'Actions' ? 'center' : 'left'} text-xs font-medium text-gray-500`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {isLoading ? (
                  Array.from({length:5}).map((_,i) => (
                    <tr key={i} className="border-b border-gray-50"><td colSpan={7} className="px-5 py-4"><div className="skeleton h-3 w-full" /></td></tr>
                  ))
                ) : paginated.length === 0 ? (
                  <tr><td colSpan={7} className="px-5 py-16 text-center">
                    <div className="flex flex-col items-center gap-2">
                      <div className="w-10 h-10 rounded-full bg-gray-100 flex items-center justify-center"><Users size={18} className="text-gray-300" /></div>
                      <p className="text-sm text-gray-400">No clients found</p>
                      <p className="text-xs text-gray-300">Try a different search term or add a new client</p>
                    </div>
                  </td></tr>
                ) : paginated.map((c) => (
                  <tr key={c.id} className="border-b border-gray-50 hover:bg-gray-50/50 transition-colors group">
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-3">
                        <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-semibold shrink-0 ${avatarBg(String(c.id))}`}>{initials(c.name)}</div>
                        <div>
                          <div className="flex items-center gap-1.5">
                            <span className="text-sm font-medium text-gray-800">{c.name}</span>
                            {c.tag && <span className={`text-xs px-1.5 py-0.5 rounded-full ${c.tag === 'VIP' ? 'bg-amber-100 text-amber-700' : 'bg-blue-100 text-blue-600'}`}>{c.tag}</span>}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3.5"><span className="text-sm text-gray-600 font-mono">{c.phone}</span></td>
                    <td className="px-4 py-3.5"><span className="text-sm text-gray-500 truncate max-w-[160px] block">{c.email || '—'}</span></td>
                    <td className="px-4 py-3.5">
                      <div className="flex items-center justify-center gap-2">
                        <Toggle value={!!c.opted_in} onChange={() => updateMut.mutate({ id: c.id, opted_in: !c.opted_in })} />
                        <span className={`text-xs ${c.opted_in ? 'text-emerald-600' : 'text-gray-400'}`}>{c.opted_in ? 'Yes' : 'No'}</span>
                      </div>
                    </td>
                    <td className="px-4 py-3.5 text-center">
                      <span className={`text-xs px-2 py-1 rounded-lg font-medium ${LANG_COLORS[c.language] || 'bg-gray-50 text-gray-600'}`}>{c.language || 'EN'}</span>
                    </td>
                    <td className="px-4 py-3.5">
                      <span className="text-xs text-gray-400">{c.created_at ? format(new Date(c.created_at), 'd MMM yyyy') : '—'}</span>
                    </td>
                    <td className="px-4 py-3.5">
                      <div className="flex items-center justify-center gap-1">
                        <button onClick={() => { setEditClient(c); setShowModal(true) }} className="p-1.5 rounded-lg text-gray-400 hover:text-blue-600 hover:bg-blue-50 transition-colors" title="Edit"><Pencil size={14} /></button>
                        <button onClick={() => setDeleteTarget(c)} className="p-1.5 rounded-lg text-gray-400 hover:text-red-500 hover:bg-red-50 transition-colors" title="Remove"><Trash2 size={14} /></button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="px-5 py-3.5 border-t border-gray-100 flex items-center justify-between">
              <p className="text-xs text-gray-400">Page <span className="font-medium text-gray-700">{safePage}</span> of <span className="font-medium text-gray-700">{totalPages}</span> · {filtered.length} clients total</p>
              <div className="flex items-center gap-1">
                <button onClick={() => setPage(p => Math.max(1,p-1))} disabled={safePage===1} className="p-1.5 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-50 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"><ChevronLeft size={15} /></button>
                {Array.from({length:totalPages},(_,i)=>i+1).map(p => (
                  <button key={p} onClick={() => setPage(p)} className={`w-7 h-7 rounded-lg text-xs transition-colors ${p===safePage ? 'bg-gray-900 text-white' : 'text-gray-500 hover:bg-gray-50'}`}>{p}</button>
                ))}
                <button onClick={() => setPage(p => Math.min(totalPages,p+1))} disabled={safePage===totalPages} className="p-1.5 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-50 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"><ChevronRight size={15} /></button>
              </div>
            </div>
          )}
        </div>

        <p className="text-xs text-gray-400 text-center pb-2">Clients who have not opted in will not receive any WhatsApp messages from your store.</p>
      </div>

      {showModal && <ClientModal client={editClient} onSave={handleSave} onClose={() => { setShowModal(false); setEditClient(null) }} />}
      {deleteTarget && <DeleteConfirm name={deleteTarget.name} onConfirm={() => deleteMut.mutate(deleteTarget.id)} onClose={() => setDeleteTarget(null)} />}
      {showBulkModal && <BulkOptInModal onConfirm={() => bulkOptInMut.mutate()} onClose={() => setShowBulkModal(false)} isPending={bulkOptInMut.isPending} />}
    </div>
  )
}
