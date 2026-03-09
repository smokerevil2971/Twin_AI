import { useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { Download, ArrowLeft } from 'lucide-react'
import { Link } from 'react-router-dom'
import { format } from 'date-fns'
import KPICard from '../components/ui/KPICard'
import StatusBadge from '../components/ui/StatusBadge'
import DataTable from '../components/ui/DataTable'
import api from '../api/client'
import { Megaphone, CheckCircle, BookOpen, XCircle } from 'lucide-react'

export default function BroadcastDetail() {
  const { id } = useParams()
  const qc = useQueryClient()
  const esRef = useRef(null)

  const { data: broadcast, isLoading } = useQuery({
    queryKey: ['broadcast', id],
    queryFn: () => api.get(`/broadcasts/${id}`).then(r => r.data?.data),
  })

  // SSE real-time delivery updates
  useEffect(() => {
    const token = localStorage.getItem('twinai_token')
    // EventSource doesn't support custom headers natively, so we use a URL param
    // The backend should accept ?token=... OR we fall back to polling if SSE can't auth
    const url = `/api/broadcasts/${id}/stream${token ? `?token=${encodeURIComponent(token)}` : ''}`
    const es = new EventSource(url)

    es.onmessage = (event) => {
      // Invalidate so React Query refetches the broadcast
      qc.invalidateQueries({ queryKey: ['broadcast', id] })
      try {
        const data = JSON.parse(event.data)
        if (data.status === 'completed' || data.status === 'failed') {
          es.close()
        }
      } catch (_) {}
    }

    es.onerror = () => {
      // SSE error (auth failure, network error) — close silently, data is still visible
      es.close()
    }

    esRef.current = es
    return () => { es.close() }
  }, [id, qc])

  if (isLoading) return <div className="space-y-4">
    {Array(4).fill(0).map((_, i) => <div key={i} className="skeleton h-24 rounded-card" />)}
  </div>

  const b = broadcast || {}
  const total = b.total_recipients || 1
  const sentPct      = Math.round(((b.sent_count || 0) / total) * 100)
  const deliveredPct = Math.round(((b.delivered_count || 0) / total) * 100)
  const readPct      = Math.round(((b.read_count || 0) / total) * 100)
  const failedPct    = Math.round(((b.failed_count || 0) / total) * 100)

  const recipCols = [
    { key: 'client_name', label: 'Client' },
    { key: 'phone',       label: 'Phone' },
    { key: 'status',      label: 'Status',       render: r => <StatusBadge status={r.status} /> },
    { key: 'sent_at',     label: 'Sent',          render: r => r.sent_at ? format(new Date(r.sent_at), 'h:mm a') : '—' },
    { key: 'delivered_at',label: 'Delivered',     render: r => r.delivered_at ? format(new Date(r.delivered_at), 'h:mm a') : '—' },
    { key: 'read_at',     label: 'Read',          render: r => r.read_at ? format(new Date(r.read_at), 'h:mm a') : '—' },
    { key: 'failed_reason',label: 'Fail Reason',  render: r => r.failed_reason ? <span className="text-danger text-xs">{r.failed_reason}</span> : '—' },
  ]

  return (
    <div className="space-y-6" style={{ animation: 'fadeIn 0.3s ease-out' }}>
      <div className="flex items-center gap-4">
        <Link to="/broadcasts" className="text-text-secondary hover:text-text-primary"><ArrowLeft size={18} /></Link>
        <div className="flex-1">
          <h2 className="text-xl font-semibold text-text-primary">{b.name || 'Broadcast Detail'}</h2>
          <div className="flex items-center gap-3 mt-1">
            {b.created_at && <span className="text-xs text-text-muted">{format(new Date(b.created_at), 'MMM d, yyyy h:mm a')}</span>}
            <StatusBadge status={b.status} />
          </div>
        </div>
        <button className="btn-secondary" onClick={() => window.open(`/api/broadcasts/${id}/export`)}>
          <Download size={14} /> Export CSV
        </button>
      </div>

      {/* 4 KPI Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard icon={Megaphone}    label="Sent"      value={b.sent_count || 0}      sub={`${sentPct}%`}      accentColor="#0EA5E9" />
        <KPICard icon={CheckCircle}  label="Delivered" value={b.delivered_count || 0}  sub={`${deliveredPct}%`} accentColor="#1A56A0" />
        <KPICard icon={BookOpen}     label="Read"      value={b.read_count || 0}       sub={`${readPct}%`}      accentColor="#22C55E" />
        <KPICard icon={XCircle}      label="Failed"    value={b.failed_count || 0}     sub={`${failedPct}%`}    accentColor="#EF4444" />
      </div>

      {/* Per-client table */}
      <div>
        <h3 className="text-base font-semibold text-text-primary mb-3">Per-client delivery</h3>
        <DataTable
          columns={recipCols}
          data={b.recipients || []}
          emptyMessage="No delivery data yet."
        />
      </div>
    </div>
  )
}
