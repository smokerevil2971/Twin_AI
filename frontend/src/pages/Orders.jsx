import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  Plus, X, Check, Search, Trash2, Edit2, Package, CheckCircle2, FileText, ChevronDown, Clock, XCircle, Anchor
} from 'lucide-react'
import api from '../api/client'
import clsx from 'clsx'

// ─── Formatting Helpers ───────────────────────────────────────────────────────

function formatMoney(amount) {
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 0 }).format(amount)
}

function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

// ─── Status Badge ─────────────────────────────────────────────────────────────

function OrderStatus({ status }) {
  const styles = {
    pending:   'bg-amber-50 text-amber-700 border-amber-200',
    confirmed: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    cancelled: 'bg-red-50 text-red-700 border-red-200',
  }
  const icons = {
    pending:   Clock,
    confirmed: CheckCircle2,
    cancelled: XCircle,
  }
  const Icon = icons[status] || Package
  const s = styles[status] || 'bg-gray-50 text-gray-700 border-gray-200'
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${s}`}>
      <Icon size={12} />
      <span className="capitalize">{status}</span>
    </span>
  )
}

// ─── Delete Confirm Modal ─────────────────────────────────────────────────────

function DeleteConfirm({ order, onConfirm, onClose }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/20 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-sm mx-4 p-6">
        <div className="flex items-start gap-3 mb-5">
          <div className="w-10 h-10 rounded-full bg-red-50 flex items-center justify-center shrink-0">
            <Trash2 size={16} className="text-red-500" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-gray-900 mb-1">Delete Order?</h3>
            <p className="text-xs text-gray-500 leading-relaxed">
              Are you sure you want to delete this order for <span className="font-medium text-gray-700">{order.product_name}</span>? This action cannot be undone.
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          <button onClick={onClose} className="flex-1 px-4 py-2.5 text-sm text-gray-600 bg-gray-50 border border-gray-100 rounded-xl hover:bg-gray-100 transition-colors">Cancel</button>
          <button onClick={onConfirm} className="flex-1 px-4 py-2.5 text-sm text-white bg-red-600 rounded-xl hover:bg-red-700 transition-colors">Yes, Delete</button>
        </div>
      </div>
    </div>
  )
}

// ─── Status Update Modal ──────────────────────────────────────────────────────

function StatusModal({ order, onSave, onClose }) {
  const [status, setStatus] = useState(order.status)
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/20 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-xs mx-4 p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-gray-900">Update Status</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X size={16} /></button>
        </div>
        <div className="space-y-2 mb-5">
          {['pending', 'confirmed', 'cancelled'].map(s => (
            <label key={s} className={`flex items-center gap-3 p-3 rounded-xl border cursor-pointer transition-colors ${status === s ? 'border-emerald-500 bg-emerald-50/50' : 'border-gray-200 hover:bg-gray-50'}`}>
              <input type="radio" name="status" value={s} checked={status === s} onChange={() => setStatus(s)} className="text-emerald-500 focus:ring-emerald-500" />
              <span className="text-sm font-medium text-gray-800 capitalize">{s}</span>
            </label>
          ))}
        </div>
        <button onClick={() => onSave(status)} className="w-full py-2.5 bg-gray-900 text-white rounded-xl text-sm font-medium hover:bg-gray-800 transition-colors">
          Save Changes
        </button>
      </div>
    </div>
  )
}

// ─── Order Modal (Create Only) ────────────────────────────────────────────────

function OrderModal({ onSave, onClose }) {
  const [clientId, setClientId] = useState('')
  const [productName, setProductName] = useState('')
  const [amount, setAmount] = useState('')
  const [status, setStatus] = useState('pending')

  // Fetch clients for dropdown
  const { data: clientsData = [] } = useQuery({
    queryKey: ['clients'],
    queryFn: () => api.get('/clients').then(r => r.data?.data || []),
  })

  // We should extract just the clients array if the backend is paginated
  // Let's handle both flat array and paginated format:
  const clientsList = Array.isArray(clientsData) ? clientsData : (clientsData.clients || [])

  const valid = clientId && productName.trim() && amount > 0

  function handleSubmit() {
    if (!valid) return
    onSave({
      client_id: clientId,
      product_name: productName.trim(),
      amount: parseFloat(amount),
      status,
    })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/20 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden flex flex-col max-h-[90vh]">
        <div className="px-6 pt-6 pb-4 border-b border-gray-100 flex items-center justify-between shrink-0">
          <div>
            <h2 className="text-base font-semibold text-gray-900">Create New Order</h2>
            <p className="text-xs text-gray-400 mt-0.5">Manually record an order for a client</p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-gray-50 text-gray-400 hover:text-gray-600 transition-colors"><X size={16} /></button>
        </div>

        <div className="px-6 py-5 space-y-4 overflow-y-auto">
          <div>
            <label className="text-xs font-medium text-gray-600 block mb-1.5">Select Client *</label>
            <div className="relative">
              <select value={clientId} onChange={e => setClientId(e.target.value)}
                className="w-full px-3.5 py-2.5 bg-gray-50 border border-gray-100 rounded-xl text-sm text-gray-800 appearance-none focus:outline-none focus:ring-1 focus:ring-emerald-200">
                <option value="" disabled>Choose a client...</option>
                {clientsList.map(c => (
                  <option key={c.id} value={c.id}>{c.name} ({c.phone})</option>
                ))}
              </select>
              <div className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none text-gray-400">
                <ChevronDown size={14} />
              </div>
            </div>
          </div>
          
          <div>
            <label className="text-xs font-medium text-gray-600 block mb-1.5">Product / Service Name *</label>
            <input type="text" value={productName} onChange={e => setProductName(e.target.value)} placeholder="e.g. Premium Subscription"
              className="w-full px-3.5 py-2.5 bg-gray-50 border border-gray-100 rounded-xl text-sm text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-emerald-200" />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-medium text-gray-600 block mb-1.5">Amount (₹) *</label>
              <input type="number" min="0" step="0.01" value={amount} onChange={e => setAmount(e.target.value)} placeholder="0.00"
                className="w-full px-3.5 py-2.5 bg-gray-50 border border-gray-100 rounded-xl text-sm text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-emerald-200" />
            </div>
            <div>
              <label className="text-xs font-medium text-gray-600 block mb-1.5">Initial Status</label>
              <div className="relative">
                <select value={status} onChange={e => setStatus(e.target.value)}
                  className="w-full px-3.5 py-2.5 bg-gray-50 border border-gray-100 rounded-xl text-sm text-gray-800 appearance-none focus:outline-none focus:ring-1 focus:ring-emerald-200">
                  <option value="pending">Pending</option>
                  <option value="confirmed">Confirmed</option>
                  <option value="cancelled">Cancelled</option>
                </select>
                <div className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none text-gray-400">
                  <ChevronDown size={14} />
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="px-6 pb-6 pt-4 border-t border-gray-100 flex gap-2 shrink-0">
          <button onClick={onClose} className="flex-1 px-4 py-2.5 text-sm text-gray-600 bg-gray-50 border border-gray-100 rounded-xl hover:bg-gray-100 transition-colors">Cancel</button>
          <button onClick={handleSubmit} disabled={!valid}
            className="flex-1 px-4 py-2.5 text-sm text-white bg-gray-900 rounded-xl hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-1.5">
            <Check size={14} /> Create Order
          </button>
        </div>
      </div>
    </div>
  )
}


// ─── Main Page ────────────────────────────────────────────────────────────────

export default function Orders() {
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all') // all, pending, confirmed, cancelled
  const [showModal, setShowModal] = useState(false)
  const [statusTarget, setStatusTarget] = useState(null) // order obj
  const [deleteTarget, setDeleteTarget] = useState(null) // order obj

  const { data: response = {}, isLoading } = useQuery({
    queryKey: ['orders', statusFilter, search],
    queryFn: () => {
      const p = { page_size: 100 }
      if (statusFilter !== 'all') p.status = statusFilter
      if (search.trim()) p.search = search.trim()
      return api.get('/orders', { params: p }).then(r => r.data?.data || {})
    },
    placeholderData: {},
  })

  const orders = response.orders || []

  const createMut = useMutation({
    mutationFn: (d) => api.post('/orders', d),
    onSuccess: () => { toast.success('Order created'); qc.invalidateQueries(['orders']); setShowModal(false) },
    onError: (e) => toast.error(e?.response?.data?.detail || 'Failed to create order'),
  })

  const updateStatusMut = useMutation({
    mutationFn: ({ id, status }) => api.patch(`/orders/${id}`, { status }),
    onSuccess: () => { toast.success('Status updated'); qc.invalidateQueries(['orders']); setStatusTarget(null) },
    onError: () => toast.error('Failed to update status'),
  })

  const deleteMut = useMutation({
    mutationFn: (id) => api.delete(`/orders/${id}`),
    onSuccess: () => { toast.success('Order deleted'); qc.invalidateQueries(['orders']); setDeleteTarget(null) },
    onError: () => toast.error('Failed to delete order'),
  })

  return (
    <div className="space-y-6 max-w-6xl mx-auto pb-12">
      {/* Header */}
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-gray-900 mb-1">Orders</h1>
          <p className="text-sm text-gray-500">Manage customer purchases and payment statuses</p>
        </div>
        <button onClick={() => setShowModal(true)}
          className="flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium text-white bg-gray-900 rounded-xl hover:bg-gray-800 transition-colors shadow-sm">
          <Plus size={16} /> New Order
        </button>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
          <input type="text" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search client name or product..."
            className="w-full pl-9 pr-4 py-2.5 bg-white border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-1 focus:ring-emerald-500 transition-shadow" />
        </div>
        
        <div className="flex p-1 bg-gray-100/80 rounded-xl border border-gray-200/50 backdrop-blur-sm">
          {['all', 'pending', 'confirmed', 'cancelled'].map(s => (
            <button key={s} onClick={() => setStatusFilter(s)}
              className={clsx(
                'px-4 py-1.5 text-xs font-medium rounded-lg capitalize transition-all',
                statusFilter === s ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700 hover:bg-gray-200/50'
              )}>
              {s}
            </button>
          ))}
        </div>
      </div>

      {/* Table Content */}
      <div className="bg-white border text-left rounded-2xl border-gray-100 shadow-sm overflow-hidden">
        {isLoading ? (
          <div className="flex flex-col items-center justify-center py-20">
            <div className="w-8 h-8 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin mb-3"></div>
            <p className="text-sm text-gray-400">Loading orders...</p>
          </div>
        ) : orders.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-center px-4">
            <div className="w-16 h-16 bg-gray-50 rounded-full flex items-center justify-center mb-4">
              <Package size={24} className="text-gray-400" />
            </div>
            <h3 className="text-base font-semibold text-gray-900 mb-1">No orders found</h3>
            <p className="text-sm text-gray-500 max-w-sm">
              {search || statusFilter!=='all' ? "Try adjusting your filters or search terms." : "You haven't added any orders yet. Create one manually to start tracking."}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left whitespace-nowrap">
              <thead className="bg-gray-50/50 text-xs text-gray-500 font-medium">
                <tr>
                  <th className="px-6 py-4 rounded-tl-2xl">Client</th>
                  <th className="px-6 py-4">Product / Service</th>
                  <th className="px-6 py-4">Amount</th>
                  <th className="px-6 py-4">Date</th>
                  <th className="px-6 py-4">Status</th>
                  <th className="px-6 py-4 text-right rounded-tr-2xl">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {orders.map(order => (
                  <tr key={order.id} className="hover:bg-gray-50/50 transition-colors group">
                    <td className="px-6 py-3.5">
                      <div className="font-medium text-gray-900">{order.client_name || 'Unknown Client'}</div>
                      <div className="text-xs text-gray-500">{order.client_phone || '—'}</div>
                    </td>
                    <td className="px-6 py-3.5 flex items-center gap-2">
                       <Package size={14} className="text-gray-400" />
                       <span className="text-gray-700">{order.product_name}</span>
                    </td>
                    <td className="px-6 py-3.5 font-medium text-gray-900">
                      {formatMoney(order.amount)}
                    </td>
                    <td className="px-6 py-3.5 text-gray-500 text-xs">
                      {formatDate(order.created_at)}
                    </td>
                    <td className="px-6 py-3.5">
                      <OrderStatus status={order.status} />
                    </td>
                    <td className="px-6 py-3.5 text-right">
                      <div className="flex items-center justify-end gap-1 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity">
                        <button onClick={() => setStatusTarget(order)} title="Change Status"
                          className="p-1.5 text-gray-400 hover:text-emerald-600 hover:bg-emerald-50 rounded-lg transition-colors">
                          <Edit2 size={15} />
                        </button>
                        <button onClick={() => setDeleteTarget(order)} title="Delete Order"
                          className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors">
                          <Trash2 size={15} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Modals */}
      {showModal && <OrderModal onSave={d => createMut.mutate(d)} onClose={() => setShowModal(false)} />}
      {statusTarget && <StatusModal order={statusTarget} onSave={st => updateStatusMut.mutate({ id: statusTarget.id, status: st })} onClose={() => setStatusTarget(null)} />}
      {deleteTarget && <DeleteConfirm order={deleteTarget} onConfirm={() => deleteMut.mutate(deleteTarget.id)} onClose={() => setDeleteTarget(null)} />}
    </div>
  )
}
