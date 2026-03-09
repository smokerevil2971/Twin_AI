import { useState, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  Plus, X, Check, Upload, Pencil, Archive, Tag,
  CalendarDays, Inbox, Clock, Zap, Image as ImageIcon, FileText, Trash2
} from 'lucide-react'
import api from '../api/client'

// ─── Helpers ──────────────────────────────────────────────────────────────────

const fmt = d => new Date(d).toISOString().split('T')[0]
const addDays = (d, n) => { const r = new Date(d); r.setDate(r.getDate() + n); return r }

function computeStatus(offer) {
  // Backend already sends `status` field; use it if present
  if (offer.status) return offer.status
  if (!offer.is_active) return 'archived'
  const now = new Date(); now.setHours(0, 0, 0, 0)
  const until = offer.valid_until ? new Date(offer.valid_until) : null
  const from  = offer.valid_from  ? new Date(offer.valid_from)  : null
  if (until && until < now) return 'expired'
  if (from  && from  > now) return 'upcoming'
  return 'active'
}
function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-GB', { day:'numeric', month:'short', year:'numeric' })
}
function daysLeft(iso) {
  const now   = new Date(); now.setHours(0, 0, 0, 0)
  const until = new Date(iso); until.setHours(0, 0, 0, 0)
  return Math.round((until - now) / 86400000)
}

// ─── Archive Confirm ───────────────────────────────────────────────────────────
function ArchiveConfirm({ offer, onConfirm, onClose }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/20 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-sm mx-4 p-6">
        <div className="flex items-start gap-3 mb-5">
          <div className="w-10 h-10 rounded-full bg-gray-100 flex items-center justify-center shrink-0"><Archive size={16} className="text-gray-500" /></div>
          <div>
            <h3 className="text-sm font-semibold text-gray-900 mb-1">Archive this offer?</h3>
            <p className="text-xs text-gray-500 leading-relaxed"><span className="font-medium text-gray-700">"{offer.title}"</span> will be archived and your AI assistant will no longer share it with customers. You can view it in your archive any time.</p>
          </div>
        </div>
        <div className="flex gap-2">
          <button onClick={onClose} className="flex-1 px-4 py-2.5 text-sm text-gray-600 bg-gray-50 border border-gray-100 rounded-xl hover:bg-gray-100 transition-colors">Keep It</button>
          <button onClick={onConfirm} className="flex-1 px-4 py-2.5 text-sm text-white bg-gray-900 rounded-xl hover:bg-gray-700 transition-colors flex items-center justify-center gap-1.5"><Archive size={13} /> Yes, Archive</button>
        </div>
      </div>
    </div>
  )
}

// ─── Delete Confirm ────────────────────────────────────────────────────────────
function DeleteConfirm({ offer, onConfirm, onClose }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/20 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-sm mx-4 p-6">
        <div className="flex items-start gap-3 mb-5">
          <div className="w-10 h-10 rounded-full bg-red-50 flex items-center justify-center shrink-0"><Trash2 size={16} className="text-red-500" /></div>
          <div>
            <h3 className="text-sm font-semibold text-gray-900 mb-1">Delete this offer?</h3>
            <p className="text-xs text-gray-500 leading-relaxed"><span className="font-medium text-gray-700">"{offer.title}"</span> will be permanently deleted. This cannot be undone.</p>
          </div>
        </div>
        <div className="flex gap-2">
          <button onClick={onClose} className="flex-1 px-4 py-2.5 text-sm text-gray-600 bg-gray-50 border border-gray-100 rounded-xl hover:bg-gray-100 transition-colors">Cancel</button>
          <button onClick={onConfirm} className="flex-1 px-4 py-2.5 text-sm text-white bg-red-600 rounded-xl hover:bg-red-700 transition-colors flex items-center justify-center gap-1.5"><Trash2 size={13} /> Delete</button>
        </div>
      </div>
    </div>
  )
}

// ─── Offer Modal ───────────────────────────────────────────────────────────────
function OfferModal({ offer, onSave, onClose }) {
  const today = new Date()
  const [title, setTitle]           = useState(offer?.title || '')
  const [description, setDescription] = useState(offer?.description || '')
  const [validFrom, setValidFrom]   = useState(offer?.valid_from ? fmt(offer.valid_from) : fmt(today))
  const [validUntil, setValidUntil] = useState(offer?.valid_until ? fmt(offer.valid_until) : fmt(addDays(today, 7)))
  const [fileName, setFileName]     = useState(null)
  const fileRef = useRef(null)

  const valid = title.trim() && validFrom && validUntil && validUntil >= validFrom

  function handleFile(e) { const f = e.target.files?.[0]; if (f) setFileName(f.name); e.target.value = '' }
  function handleSubmit() {
    if (!valid) return
    onSave({ title: title.trim(), description: description.trim() || null, valid_from: validFrom, valid_until: validUntil })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/20 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-lg mx-4 flex flex-col max-h-[90vh] overflow-hidden">
        <div className="px-6 pt-6 pb-4 border-b border-gray-100 flex items-center justify-between shrink-0">
          <div>
            <h2 className="text-base font-semibold text-gray-900">{offer ? 'Edit Offer' : 'Create New Offer'}</h2>
            <p className="text-xs text-gray-400 mt-0.5">{offer ? 'Update the details of this offer.' : 'Fill in the details below and your AI will start sharing this offer with customers.'}</p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-gray-50 text-gray-400 hover:text-gray-600 transition-colors"><X size={16} /></button>
        </div>

        <div className="px-6 py-5 space-y-4 overflow-y-auto flex-1">
          <div>
            <label className="text-xs font-medium text-gray-600 block mb-1.5">Offer Title *</label>
            <input type="text" value={title} onChange={e=>setTitle(e.target.value)} placeholder="e.g. March Flash Sale – 30% Off"
              className="w-full px-3.5 py-2.5 bg-gray-50 border border-gray-100 rounded-xl text-sm text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-gray-200 focus:bg-white transition" />
          </div>
          <div>
            <label className="text-xs font-medium text-gray-600 block mb-1.5">Description</label>
            <textarea value={description} onChange={e=>setDescription(e.target.value)} placeholder="Describe what's on offer, any conditions, and how customers can take advantage of it." rows={3}
              className="w-full px-3.5 py-2.5 bg-gray-50 border border-gray-100 rounded-xl text-sm text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-gray-200 focus:bg-white transition resize-none" />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-medium text-gray-600 block mb-1.5">Valid From *</label>
              <input type="date" value={validFrom} onChange={e=>setValidFrom(e.target.value)}
                className="w-full px-3.5 py-2.5 bg-gray-50 border border-gray-100 rounded-xl text-sm text-gray-700 focus:outline-none focus:ring-1 focus:ring-gray-200 focus:bg-white transition" />
            </div>
            <div>
              <label className="text-xs font-medium text-gray-600 block mb-1.5">Valid Until *</label>
              <input type="date" value={validUntil} min={validFrom} onChange={e=>setValidUntil(e.target.value)}
                className="w-full px-3.5 py-2.5 bg-gray-50 border border-gray-100 rounded-xl text-sm text-gray-700 focus:outline-none focus:ring-1 focus:ring-gray-200 focus:bg-white transition" />
              {validUntil && validFrom && validUntil < validFrom && <p className="text-[11px] text-red-400 mt-1">"Until" must be after "From".</p>}
            </div>
          </div>
          <div>
            <label className="text-xs font-medium text-gray-600 block mb-1.5">Offer Image or PDF <span className="text-gray-400 font-normal">(optional)</span></label>
            <input ref={fileRef} type="file" accept=".pdf,.jpg,.jpeg,.png,.webp" className="hidden" onChange={handleFile} />
            {fileName ? (
              <div className="flex items-center gap-3 px-4 py-3 bg-blue-50 border border-blue-100 rounded-xl">
                {fileName.endsWith('.pdf') ? <FileText size={15} className="text-blue-500 shrink-0" /> : <ImageIcon size={15} className="text-blue-500 shrink-0" />}
                <span className="flex-1 text-xs text-blue-700 truncate">{fileName}</span>
                <button onClick={() => setFileName(null)} className="text-blue-400 hover:text-blue-600 transition-colors shrink-0"><X size={13} /></button>
              </div>
            ) : (
              <button type="button" onClick={() => fileRef.current?.click()}
                className="w-full flex flex-col items-center gap-2 px-4 py-5 bg-gray-50 border-2 border-dashed border-gray-200 rounded-xl text-gray-400 hover:border-gray-300 hover:bg-white transition-colors">
                <Upload size={18} className="text-gray-300" />
                <span className="text-xs text-center">Click to upload a photo or PDF<br /><span className="text-gray-300">JPG, PNG, WEBP or PDF · Max 10 MB</span></span>
              </button>
            )}
          </div>
        </div>

        <div className="px-6 pb-6 pt-4 border-t border-gray-100 flex gap-2 shrink-0">
          <button onClick={onClose} className="flex-1 px-4 py-2.5 text-sm text-gray-600 bg-gray-50 border border-gray-100 rounded-xl hover:bg-gray-100 transition-colors">Cancel</button>
          <button onClick={handleSubmit} disabled={!valid}
            className="flex-1 px-4 py-2.5 text-sm text-white bg-gray-900 rounded-xl hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-1.5">
            <Check size={14} />{offer ? 'Save Changes' : 'Create Offer'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Offer Card ────────────────────────────────────────────────────────────────
function OfferCard({ offer, onEdit, onArchive, onDelete }) {
  const status    = computeStatus(offer)
  const remaining = status === 'active' ? daysLeft(offer.valid_until) : null
  const upcoming  = status === 'upcoming'

  const isActive   = status === 'active'
  const isUpcoming = status === 'upcoming'
  const isExpired  = status === 'expired'
  const isArchived = status === 'archived'

  return (
    <div className={`relative bg-white rounded-2xl border transition-all flex flex-col overflow-hidden ${isActive ? 'border-emerald-200 shadow-sm shadow-emerald-50' : 'border-gray-100'} ${isExpired || isArchived ? 'opacity-60' : ''}`}>
      {/* Top accent bar */}
      <div className={`h-1 w-full shrink-0 ${isActive ? 'bg-gradient-to-r from-emerald-400 to-teal-400' : isUpcoming ? 'bg-gradient-to-r from-blue-400 to-indigo-400' : 'bg-gray-100'}`} />

      <div className="px-5 py-4 flex-1 flex flex-col">
        <div className="flex items-start justify-between gap-3 mb-3">
          {isActive   && <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-50 text-emerald-700 text-xs font-medium shrink-0"><span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />Active</span>}
          {isUpcoming && <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-blue-50 text-blue-700 text-xs font-medium shrink-0"><Clock size={11} />Upcoming</span>}
          {isExpired  && <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-gray-100 text-gray-500 text-xs font-medium shrink-0">Expired</span>}
          {isArchived && <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-gray-100 text-gray-400 text-xs font-medium shrink-0"><Archive size={10} />Archived</span>}

          {!isArchived && (
            <div className="flex items-center gap-1 shrink-0">
              <button onClick={onEdit}    className="p-1.5 rounded-lg text-gray-400 hover:text-blue-600 hover:bg-blue-50 transition-colors" title="Edit offer"><Pencil size={14} /></button>
              <button onClick={onArchive} className="p-1.5 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors" title="Archive offer"><Archive size={14} /></button>
              <button onClick={onDelete}  className="p-1.5 rounded-lg text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors" title="Delete offer"><Trash2 size={14} /></button>
            </div>
          )}
          {isArchived && (
            <div className="flex items-center gap-1 shrink-0">
              <button onClick={onDelete}  className="p-1.5 rounded-lg text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors" title="Delete offer"><Trash2 size={14} /></button>
            </div>
          )}
        </div>

        <h3 className={`text-sm font-semibold mb-1.5 leading-snug ${isExpired || isArchived ? 'text-gray-500' : 'text-gray-900'}`}>{offer.title}</h3>
        {offer.description && <p className="text-xs text-gray-500 leading-relaxed mb-4 flex-1">{offer.description}</p>}

        <div className="mt-auto pt-3 border-t border-gray-50 flex items-end justify-between gap-3">
          <div className="flex items-center gap-1.5 text-xs text-gray-400">
            <CalendarDays size={11} className="shrink-0" />
            <span>{formatDate(offer.valid_from)} → {formatDate(offer.valid_until)}</span>
          </div>
          {isActive   && remaining !== null && <span className={`text-xs font-medium px-2.5 py-1 rounded-full shrink-0 ${remaining<=3 ? 'bg-red-50 text-red-500' : remaining<=7 ? 'bg-amber-50 text-amber-600' : 'bg-emerald-50 text-emerald-600'}`}>{remaining===0 ? 'Ends today' : remaining===1 ? '1 day left' : `${remaining} days left`}</span>}
          {isUpcoming && <span className="text-xs font-medium px-2.5 py-1 rounded-full bg-blue-50 text-blue-600 shrink-0">Starts {formatDate(offer.valid_from)}</span>}
          {isExpired  && <span className="text-xs text-gray-400 shrink-0">Ended {formatDate(offer.valid_until)}</span>}
        </div>
      </div>
    </div>
  )
}

// ─── Filter Tab ────────────────────────────────────────────────────────────────
function FilterTab({ label, count, active, onClick }) {
  return (
    <button onClick={onClick} className={`flex items-center gap-2 px-4 py-2 rounded-xl text-sm transition-colors ${active ? 'bg-gray-900 text-white' : 'bg-white border border-gray-100 text-gray-500 hover:bg-gray-50'}`}>
      {label}
      <span className={`text-xs px-1.5 py-0.5 rounded-full font-medium ${active ? 'bg-white/20 text-white' : 'bg-gray-100 text-gray-500'}`}>{count}</span>
    </button>
  )
}

// ─── Main Page ─────────────────────────────────────────────────────────────────
export default function Offers() {
  const qc = useQueryClient()
  const [filter, setFilter]           = useState('all')
  const [showModal, setShowModal]     = useState(false)
  const [editOffer, setEditOffer]     = useState(null)
  const [archiveOffer, setArchiveOffer] = useState(null)
  const [deleteOffer, setDeleteOffer] = useState(null)

  // ── Data ──────────────────────────────────────────────────────────────────
  const { data: allOffers = [], isLoading } = useQuery({
    queryKey: ['offers'],
    queryFn: () => api.get('/offers').then(r => r.data?.data?.offers || []),
    placeholderData: [],
  })

  // ── Mutations ─────────────────────────────────────────────────────────────
  const createMutation = useMutation({
    mutationFn: (body) => api.post('/offers', body),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['offers'] }); toast.success('Offer created') },
  })
  const updateMutation = useMutation({
    mutationFn: ({ id, ...body }) => api.patch(`/offers/${id}`, body),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['offers'] }); toast.success('Offer updated') },
  })
  const archiveMutation = useMutation({
    mutationFn: (id) => api.patch(`/offers/${id}`, { is_active: false }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['offers'] }); toast.success('Offer archived'); setArchiveOffer(null) },
  })
  const deleteMutation = useMutation({
    mutationFn: (id) => api.delete(`/offers/${id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['offers'] }); toast.success('Offer logically deleted'); setDeleteOffer(null) },
  })

  // ── Handlers ──────────────────────────────────────────────────────────────
  function handleSave(data) {
    if (editOffer) {
      updateMutation.mutate({ id: editOffer.id, ...data })
    } else {
      createMutation.mutate(data)
    }
    setShowModal(false); setEditOffer(null)
  }
  function handleArchive() {
    if (!archiveOffer) return
    archiveMutation.mutate(archiveOffer.id)
  }
  function handleDelete() {
    if (!deleteOffer) return
    deleteMutation.mutate(deleteOffer.id)
  }

  // ── Derived ───────────────────────────────────────────────────────────────
  const counts = {
    all:      allOffers.filter(o => computeStatus(o) !== 'archived').length,
    active:   allOffers.filter(o => computeStatus(o) === 'active').length,
    upcoming: allOffers.filter(o => computeStatus(o) === 'upcoming').length,
    expired:  allOffers.filter(o => computeStatus(o) === 'expired').length,
    archived: allOffers.filter(o => computeStatus(o) === 'archived').length,
  }

  const filtered = allOffers.filter(o => {
    const s = computeStatus(o)
    if (filter === 'all') return s !== 'archived'
    return s === filter
  })
  const sorted = [...filtered].sort((a, b) => {
    const order = { active:0, upcoming:1, expired:2, archived:3 }
    return (order[computeStatus(a)] || 0) - (order[computeStatus(b)] || 0)
  })

  return (
    <div className="flex-1 flex flex-col h-screen overflow-hidden bg-gray-50/60 -mx-8 -my-7">
      {/* Top Bar */}
      <div className="h-16 bg-white border-b border-gray-100 px-8 flex items-center justify-between shrink-0 sticky top-0 z-10">
        <div>
          <h1 className="text-base font-semibold text-gray-900">Offers</h1>
          <p className="text-xs text-gray-400">Promotions and deals your AI shares with customers</p>
        </div>
        <button onClick={() => { setEditOffer(null); setShowModal(true) }}
          className="flex items-center gap-1.5 px-3.5 py-2 text-sm text-white bg-gray-900 rounded-lg hover:bg-gray-700 transition-colors">
          <Plus size={14} /> Create Offer
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-8 py-6 space-y-5">
        {/* Stat Cards */}
        <div className="grid grid-cols-3 gap-4">
          {[
            { label:'Active Offers',        value: counts.active,  sub:'Customers can see these now',   icon:Zap,   bg:'bg-emerald-50', color:'text-emerald-500' },
            { label:'Upcoming',             value: counts.upcoming, sub:'Scheduled to go live soon',     icon:Clock, bg:'bg-blue-50',    color:'text-blue-500'    },
            { label:'Total Offers Created', value: allOffers.length, sub:'All time',                    icon:Tag,   bg:'bg-gray-100',   color:'text-gray-500'    },
          ].map(({ label, value, sub, icon: Icon, bg, color }) => (
            <div key={label} className="bg-white rounded-xl border border-gray-100 px-5 py-4 flex items-center gap-4">
              <div className={`w-10 h-10 rounded-xl ${bg} flex items-center justify-center shrink-0`}><Icon size={18} className={color} /></div>
              <div>
                <p className="text-xs text-gray-400">{label}</p>
                <p className="text-2xl font-semibold text-gray-900 leading-tight">{isLoading ? '…' : value}</p>
                <p className="text-xs text-gray-400">{sub}</p>
              </div>
            </div>
          ))}
        </div>

        {/* Filter Tabs */}
        <div className="flex items-center gap-2">
          <FilterTab label="All Offers" count={counts.all}      active={filter==='all'}      onClick={() => setFilter('all')}      />
          <FilterTab label="Active"     count={counts.active}   active={filter==='active'}   onClick={() => setFilter('active')}   />
          <FilterTab label="Upcoming"   count={counts.upcoming} active={filter==='upcoming'} onClick={() => setFilter('upcoming')} />
          <FilterTab label="Expired"    count={counts.expired}  active={filter==='expired'}  onClick={() => setFilter('expired')}  />
          <FilterTab label="Archived"   count={counts.archived} active={filter==='archived'} onClick={() => setFilter('archived')} />
        </div>

        {/* Offers Grid */}
        {isLoading ? (
          <div className="flex items-center justify-center py-20"><div className="w-7 h-7 border-2 border-gray-200 border-t-gray-500 rounded-full animate-spin" /></div>
        ) : sorted.length === 0 ? (
          <div className="bg-white rounded-2xl border border-gray-100 py-20 flex flex-col items-center gap-3">
            <div className="w-12 h-12 rounded-2xl bg-gray-100 flex items-center justify-center"><Inbox size={22} className="text-gray-300" /></div>
            <div className="text-center">
              <p className="text-sm font-medium text-gray-600">{filter==='archived' ? 'No archived offers' : filter==='expired' ? 'No expired offers' : filter==='upcoming' ? 'No upcoming offers' : 'No offers yet'}</p>
              <p className="text-xs text-gray-400 mt-1">{filter==='all' ? 'Create your first offer to get started.' : `No ${filter} offers to show.`}</p>
            </div>
            {filter==='all' && <button onClick={() => { setEditOffer(null); setShowModal(true) }} className="mt-1 flex items-center gap-1.5 px-4 py-2 text-xs text-white bg-gray-900 rounded-lg hover:bg-gray-700 transition-colors"><Plus size={12} /> Create Offer</button>}
          </div>
        ) : (
          <div className="grid grid-cols-3 gap-4">
            {sorted.map(offer => (
              <OfferCard key={offer.id} offer={offer}
                onEdit={() => { setEditOffer(offer); setShowModal(true) }}
                onArchive={() => setArchiveOffer(offer)}
                onDelete={() => setDeleteOffer(offer)} />
            ))}
          </div>
        )}

        <p className="text-xs text-gray-400 text-center pb-2">Active offers are automatically shared by your AI assistant when customers ask about deals or promotions.</p>
      </div>

      {showModal   && <OfferModal offer={editOffer} onSave={handleSave} onClose={() => { setShowModal(false); setEditOffer(null) }} />}
      {archiveOffer && <ArchiveConfirm offer={archiveOffer} onConfirm={handleArchive} onClose={() => setArchiveOffer(null)} />}
      {deleteOffer && <DeleteConfirm offer={deleteOffer} onConfirm={handleDelete} onClose={() => setDeleteOffer(null)} />}
    </div>
  )
}
