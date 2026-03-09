import { useState, useRef, useEffect } from 'react'
import {
  Upload, Trash2, FileText, FileSpreadsheet, File,
  CheckCircle2, Clock, X, Search, ChevronDown, Check, BookOpen, AlertCircle,
} from 'lucide-react'

const CATEGORY_CONFIG = {
  Products:   { color: 'bg-blue-50 text-blue-700',    dot: 'bg-blue-500'   },
  Offers:     { color: 'bg-amber-50 text-amber-700',  dot: 'bg-amber-500'  },
  Broadcasts: { color: 'bg-violet-50 text-violet-700',dot: 'bg-violet-500' },
  Invoices:   { color: 'bg-emerald-50 text-emerald-700',dot: 'bg-emerald-500'},
}

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'
import toast from 'react-hot-toast'

function FileIcon({ type }) {
  if (type === 'xlsx') return <div className="w-9 h-9 rounded-lg bg-emerald-50 flex items-center justify-center shrink-0"><FileSpreadsheet size={17} className="text-emerald-600" /></div>
  if (type === 'docx') return <div className="w-9 h-9 rounded-lg bg-blue-50 flex items-center justify-center shrink-0"><File size={17} className="text-blue-600" /></div>
  return <div className="w-9 h-9 rounded-lg bg-red-50 flex items-center justify-center shrink-0"><FileText size={17} className="text-red-500" /></div>
}

function Spinner() {
  return <svg className="animate-spin w-4 h-4 text-amber-500" viewBox="0 0 24 24" fill="none"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4l3-3-3-3V0a12 12 0 00-12 12h4z"/></svg>
}

function StatusBadge({ status }) {
  if (status === 'indexed') return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-50 text-emerald-700 text-xs"><CheckCircle2 size={11} className="text-emerald-500" />Ready to use</span>
  )
  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-amber-50 text-amber-700 text-xs"><Spinner />Reading document…</span>
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
            <h3 className="text-sm font-semibold text-gray-900 mb-1">Remove this document?</h3>
            <p className="text-xs text-gray-500 leading-relaxed"><span className="font-medium text-gray-700">"{name}"</span> will be removed and the AI will no longer use it to answer customer questions.</p>
          </div>
        </div>
        <div className="flex gap-2">
          <button onClick={onClose} className="flex-1 px-4 py-2.5 text-sm text-gray-600 bg-gray-50 border border-gray-100 rounded-xl hover:bg-gray-100 transition-colors">Keep It</button>
          <button onClick={onConfirm} className="flex-1 px-4 py-2.5 text-sm text-white bg-red-500 rounded-xl hover:bg-red-600 transition-colors">Yes, Remove</button>
        </div>
      </div>
    </div>
  )
}

export default function KnowledgeBase() {
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [catFilter, setCatFilter] = useState('all')
  const [catDropOpen, setCatDropOpen] = useState(false)
  const [deleteDoc, setDeleteDoc] = useState(null)
  
  const fileRef = useRef(null)

  // ─── Fetch Documents
  const { data: rawDocs = [], isLoading } = useQuery({
    queryKey: ['kb-docs', catFilter === 'all' ? null : catFilter.toLowerCase()],
    queryFn: () => api.get('/knowledge-base', { params: catFilter === 'all' ? {} : { category: catFilter.toLowerCase() } }).then(r => r.data?.data?.documents || []),
  })

  // Format backend data for the UI
  const docs = rawDocs.map(d => ({
    id: d.id,
    fileName: d.filename,
    fileType: d.filename.split('.').pop()?.toLowerCase() || 'pdf',
    category: d.category.charAt(0).toUpperCase() + d.category.slice(1),
    uploadDate: new Date(d.created_at).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'}),
    status: d.is_active ? 'indexed' : 'processing',
    fileSize: '—' // Backend doesn't store filesize currently
  }))

  const filtered = docs.filter(d => d.fileName.toLowerCase().includes(search.toLowerCase()))

  // ─── Upload Mutation
  const uploadMutation = useMutation({
    mutationFn: (formData) => api.post('/knowledge-base/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    }),
    onSuccess: () => {
      toast.success('Document uploaded and indexed successfully!')
      qc.invalidateQueries(['kb-docs'])
    },
    onError: (e) => toast.error(e?.response?.data?.detail || 'Failed to upload document')
  })

  function handleFileSelect(e) {
    const file = e.target.files?.[0]; if (!file) return
    e.target.value = ''
    
    const lower = file.name.toLowerCase()
    let category = 'products'
    if (lower.includes('offer')||lower.includes('sale')||lower.includes('promo')) category = 'offers'
    else if (lower.includes('invoice')||lower.includes('payment')) category = 'documents' // 'documents' instead of 'invoices' per VALID_CATEGORIES
    else if (lower.includes('broadcast')||lower.includes('campaign')) category = 'broadcasts'

    const fd = new FormData()
    fd.append('file', file)
    fd.append('category', category)

    toast.loading(`Uploading taking a moment to read...`, { id: 'upload' })
    uploadMutation.mutate(fd, {
      onSettled: () => toast.dismiss('upload')
    })
  }

  // ─── Delete Mutation
  const deleteMutation = useMutation({
    mutationFn: (id) => api.delete(`/knowledge-base/${id}`),
    onSuccess: () => {
      toast.success('Document removed')
      qc.invalidateQueries(['kb-docs'])
      setDeleteDoc(null)
    },
    onError: () => toast.error('Failed to remove document')
  })

  function handleDelete() {
    if (!deleteDoc) return
    deleteMutation.mutate(deleteDoc.id)
  }


  const indexedCount = docs.filter(d => d.status === 'indexed').length
  const processingCount = docs.filter(d => d.status === 'processing').length
  const categoryCounts = docs.reduce((acc,d) => { acc[d.category]=(acc[d.category]||0)+1; return acc }, {})

  return (
    <div className="flex-1 flex flex-col h-screen overflow-hidden bg-gray-50/60 -mx-8 -my-7">
      <div className="h-16 bg-white border-b border-gray-100 px-8 flex items-center justify-between shrink-0 sticky top-0 z-10">
        <div>
          <h1 className="text-base font-semibold text-gray-900">Knowledge Base</h1>
          <p className="text-xs text-gray-400">What your AI knows about your business</p>
        </div>
        <div className="flex items-center gap-3">
          <input ref={fileRef} type="file" accept=".pdf,.xlsx,.xls,.docx,.doc" className="hidden" onChange={handleFileSelect} />
          <button onClick={() => fileRef.current?.click()}
            className="flex items-center gap-2 px-4 py-2 text-sm text-white bg-gray-900 rounded-lg hover:bg-gray-700 transition-colors">
            <Upload size={14} /> Upload Document
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-8 py-6 space-y-4">

        {/* How it works banner */}
        <div className="bg-blue-50 border border-blue-100 rounded-xl px-5 py-4 flex items-start gap-3">
          <div className="w-8 h-8 rounded-lg bg-blue-100 flex items-center justify-center shrink-0 mt-0.5"><BookOpen size={15} className="text-blue-600" /></div>
          <div>
            <p className="text-sm font-medium text-blue-900">How this works</p>
            <p className="text-xs text-blue-700 mt-0.5 leading-relaxed">Upload your product catalogues, offer sheets, or invoices here. Your AI assistant will read them and use the information to answer customer questions accurately — no extra setup needed.</p>
          </div>
        </div>

        {/* Stat cards */}
        <div className="grid grid-cols-4 gap-4">
          {[
            { label:'Total Documents', value:docs.length,              sub:'Uploaded to your library',  color:'bg-gray-50',    icon:FileText,    iconColor:'text-gray-500'    },
            { label:'Ready to Use',    value:indexedCount,             sub:'AI is using these now',     color:'bg-emerald-50', icon:CheckCircle2,iconColor:'text-emerald-500' },
            { label:'Being Read',      value:processingCount,          sub:'Will be ready shortly',     color:'bg-amber-50',   icon:Clock,       iconColor:'text-amber-500'   },
            { label:'Categories',      value:Object.keys(categoryCounts).length, sub:'Types of documents', color:'bg-blue-50',icon:BookOpen,   iconColor:'text-blue-500'    },
          ].map(({label,value,sub,color,icon:Icon,iconColor}) => (
            <div key={label} className="bg-white rounded-xl border border-gray-100 px-5 py-4 flex items-center gap-3">
              <div className={`w-10 h-10 rounded-xl ${color} flex items-center justify-center shrink-0`}><Icon size={17} className={iconColor} /></div>
              <div>
                <p className="text-xs text-gray-400">{label}</p>
                <p className="text-2xl font-semibold text-gray-900 leading-tight">{value}</p>
                <p className="text-xs text-gray-400">{sub}</p>
              </div>
            </div>
          ))}
        </div>

        {/* Filter bar */}
        <div className="bg-white rounded-xl border border-gray-100 flex items-center overflow-hidden">
          <div className="flex items-center flex-1 px-4 py-3 gap-3">
            <Search size={15} className="text-gray-400 shrink-0" />
            <input type="text" value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search documents by file name…"
              className="flex-1 text-sm text-gray-700 placeholder-gray-400 bg-transparent focus:outline-none" />
            {search && <button onClick={() => setSearch('')} className="text-gray-300 hover:text-gray-500 transition-colors shrink-0"><X size={13} /></button>}
          </div>
          <div className="w-px h-8 bg-gray-100 shrink-0" />
          <div className="relative">
            <button onClick={() => setCatDropOpen(!catDropOpen)} className="flex items-center gap-2 px-4 py-3 text-sm hover:bg-gray-50 transition-colors whitespace-nowrap">
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M1.75 2.625C1.75 2.28 2.03 2 2.375 2H11.625C11.97 2 12.25 2.28 12.25 2.625C12.25 2.97 11.97 3.25 11.625 3.25H2.375C2.03 3.25 1.75 2.97 1.75 2.625ZM3.5 7C3.5 6.655 3.78 6.375 4.125 6.375H9.875C10.22 6.375 10.5 6.655 10.5 7C10.5 7.345 10.22 7.625 9.875 7.625H4.125C3.78 7.625 3.5 7.345 3.5 7ZM5.25 11.375C5.25 11.03 5.53 10.75 5.875 10.75H8.125C8.47 10.75 8.75 11.03 8.75 11.375C8.75 11.72 8.47 12 8.125 12H5.875C5.53 12 5.25 11.72 5.25 11.375Z" fill="#9CA3AF"/></svg>
              <span className={catFilter !== 'all' ? 'text-gray-900 font-medium text-sm' : 'text-gray-500 text-sm'}>{catFilter === 'all' ? 'All Categories' : catFilter}</span>
              <ChevronDown size={13} className={`text-gray-400 transition-transform ${catDropOpen ? 'rotate-180' : ''}`} />
            </button>
            {catDropOpen && (
              <div className="absolute right-0 top-full mt-1 w-44 bg-white border border-gray-100 rounded-xl shadow-lg z-20 overflow-hidden">
                {['all','Products','Offers','Broadcasts','Documents'].map(cat => (
                  <button key={cat} onClick={() => { setCatFilter(cat); setCatDropOpen(false) }}
                    className={`w-full flex items-center justify-between px-4 py-2.5 text-sm text-left hover:bg-gray-50 transition-colors ${catFilter===cat ? 'text-gray-900' : 'text-gray-600'}`}>
                    <div className="flex items-center gap-2">
                      {cat !== 'all' && <span className={`w-2 h-2 rounded-full ${CATEGORY_CONFIG[cat]?.dot}`} />}
                      {cat === 'all' ? 'All Categories' : cat}
                    </div>
                    {catFilter === cat && <Check size={13} className="text-emerald-500" />}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Document table */}
        <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
          <div className="px-5 py-3.5 border-b border-gray-50 flex items-center justify-between">
            <p className="text-xs text-gray-500"><span className="font-medium text-gray-700">{filtered.length}</span> document{filtered.length !== 1 ? 's' : ''}</p>
            {catFilter !== 'all' && <button onClick={() => setCatFilter('all')} className="text-xs text-gray-400 hover:text-gray-700 flex items-center gap-1 transition-colors"><X size={11} /> Clear filter</button>}
          </div>
          {filtered.length === 0 ? (
            <div className="py-20 flex flex-col items-center gap-3">
              <div className="w-12 h-12 rounded-2xl bg-gray-100 flex items-center justify-center"><FileText size={22} className="text-gray-300" /></div>
              <div className="text-center">
                <p className="text-sm font-medium text-gray-600">No documents found</p>
                <p className="text-xs text-gray-400 mt-1">Try a different search or upload your first document.</p>
              </div>
              <button onClick={() => fileRef.current?.click()} className="mt-1 flex items-center gap-1.5 px-4 py-2 text-xs text-white bg-gray-900 rounded-lg hover:bg-gray-700 transition-colors"><Upload size={12} /> Upload Document</button>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="bg-gray-50/80 border-b border-gray-100">
                    {['File Name','Category','Upload Date','File Size','Status','Actions'].map(h => (
                      <th key={h} className={`px-${h==='File Name'?'5':'4'} py-3 text-${h==='Actions'?'center':'left'} text-xs font-medium text-gray-500`}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filtered.map(doc => (
                    <tr key={doc.id} className="border-b border-gray-50 last:border-0 hover:bg-gray-50/50 transition-colors">
                      <td className="px-5 py-3.5">
                        <div className="flex items-center gap-3">
                          <FileIcon type={doc.fileType} />
                          <div>
                            <p className="text-sm font-medium text-gray-800 leading-snug max-w-xs truncate">{doc.fileName}</p>
                            <p className="text-xs text-gray-400 mt-0.5 uppercase tracking-wide">{doc.fileType}</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3.5">
                        <span className={`inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full font-medium ${CATEGORY_CONFIG[doc.category]?.color}`}>
                          <span className={`w-1.5 h-1.5 rounded-full ${CATEGORY_CONFIG[doc.category]?.dot}`} />{doc.category}
                        </span>
                      </td>
                      <td className="px-4 py-3.5"><span className="text-sm text-gray-500">{doc.uploadDate}</span></td>
                      <td className="px-4 py-3.5"><span className="text-sm text-gray-400">{doc.fileSize}</span></td>
                      <td className="px-4 py-3.5"><StatusBadge status={doc.status} /></td>
                      <td className="px-4 py-3.5 text-center">
                        <button onClick={() => setDeleteDoc(doc)} disabled={deleteMutation.isPending}
                          className="p-1.5 rounded-lg text-gray-400 hover:text-red-500 hover:bg-red-50 disabled:opacity-30 disabled:cursor-not-allowed transition-colors" title="Remove document">
                          <Trash2 size={14} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="flex items-center justify-center gap-2 pb-2">
          <AlertCircle size={12} className="text-gray-300" />
          <p className="text-xs text-gray-400">Accepted file types: PDF, Excel (.xlsx), Word (.docx) · Max file size: 20 MB</p>
        </div>
      </div>

      {deleteDoc && <DeleteConfirm name={deleteDoc.fileName} onConfirm={handleDelete} onClose={() => setDeleteDoc(null)} />}
    </div>
  )
}
