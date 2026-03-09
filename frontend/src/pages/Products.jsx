import { useState, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  Search, Plus, Pencil, Trash2, X, Check,
  Upload, ShoppingBag, ChevronDown, Eye, EyeOff, Package, Tag,
  Image as ImageIcon, FileText,
} from 'lucide-react'
import api from '../api/client'

const CATEGORIES = ['Sneakers','Sandals','Formal','Heels','Boots','Kids','Accessories']

const CATEGORY_COLORS = {
  Sneakers:    'bg-blue-50 text-blue-700',
  Sandals:     'bg-amber-50 text-amber-700',
  Formal:      'bg-gray-100 text-gray-700',
  Heels:       'bg-rose-50 text-rose-700',
  Boots:       'bg-orange-50 text-orange-700',
  Kids:        'bg-green-50 text-green-700',
  Accessories: 'bg-violet-50 text-violet-700',
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function truncate(text, max = 72) {
  if (!text) return ''
  return text.length <= max ? text : text.slice(0, max).trimEnd() + '…'
}
function formatPrice(raw) {
  const n = parseFloat(raw)
  return isNaN(n) ? '—' : `GHS ${n.toFixed(2)}`
}

// ─── Status Badge ──────────────────────────────────────────────────────────────
function StatusBadge({ status, onToggle }) {
  return (
    <button onClick={onToggle}
      title={status === 'Active' ? 'Click to hide from customers' : 'Click to make visible'}
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium transition-colors cursor-pointer ${status === 'Active' ? 'bg-emerald-50 text-emerald-700 hover:bg-emerald-100' : 'bg-gray-100 text-gray-500 hover:bg-gray-200'}`}>
      {status === 'Active' ? <><Eye size={11} />Active</> : <><EyeOff size={11} />Hidden</>}
    </button>
  )
}

// ─── Product Modal ─────────────────────────────────────────────────────────────
function ProductModal({ product, onSave, onClose }) {
  const [name, setName]               = useState(product?.name || '')
  const [description, setDescription] = useState(product?.description || '')
  const [price, setPrice]             = useState(product?.price != null ? String(product.price) : '')
  const [isActive, setIsActive]       = useState(product != null ? (product.is_active !== false) : true)
  const [fileName, setFileName]       = useState(null)
  const fileRef = useRef(null)

  const valid = name.trim() && (price === '' || parseFloat(price) >= 0)

  function handleFile(e) {
    const f = e.target.files?.[0]; if (f) setFileName(f.name); e.target.value = ''
  }
  function handleSubmit(e) {
    e?.preventDefault?.(); if (!valid) return
    onSave({
      name: name.trim(),
      description: description.trim() || null,
      price: price !== '' ? parseFloat(price) : null,
      is_active: isActive,
    })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/20 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-lg mx-4 overflow-hidden flex flex-col max-h-[90vh]">
        <div className="px-6 pt-6 pb-4 border-b border-gray-100 flex items-center justify-between shrink-0">
          <div>
            <h2 className="text-base font-semibold text-gray-900">{product ? 'Edit Product' : 'Add New Product'}</h2>
            <p className="text-xs text-gray-400 mt-0.5">{product ? 'Update the details for this product.' : 'Fill in the details below to add a product to your catalogue.'}</p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-gray-50 text-gray-400 hover:text-gray-600 transition-colors"><X size={16} /></button>
        </div>

        <div className="px-6 py-5 space-y-4 overflow-y-auto flex-1">
          <div>
            <label className="text-xs font-medium text-gray-600 block mb-1.5">Product Name *</label>
            <input type="text" value={name} onChange={e=>setName(e.target.value)} placeholder="e.g. Nike Air Force 1 – White"
              className="w-full px-3.5 py-2.5 bg-gray-50 border border-gray-100 rounded-xl text-sm text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-gray-200 focus:bg-white transition" />
          </div>
          <div>
            <label className="text-xs font-medium text-gray-600 block mb-1.5">Description</label>
            <textarea value={description} onChange={e=>setDescription(e.target.value)} placeholder="Describe this product — sizes, colours, material, etc." rows={3}
              className="w-full px-3.5 py-2.5 bg-gray-50 border border-gray-100 rounded-xl text-sm text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-gray-200 focus:bg-white transition resize-none" />
          </div>
          <div>
            <label className="text-xs font-medium text-gray-600 block mb-1.5">Price</label>
            <div className="relative">
              <span className="absolute left-3.5 top-1/2 -translate-y-1/2 text-xs text-gray-400 font-medium">GHS</span>
              <input type="number" min="0" step="0.01" value={price} onChange={e=>setPrice(e.target.value)} placeholder="0.00"
                className="w-full pl-11 pr-3.5 py-2.5 bg-gray-50 border border-gray-100 rounded-xl text-sm text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-gray-200 focus:bg-white transition" />
            </div>
          </div>
          <div>
            <label className="text-xs font-medium text-gray-600 block mb-1.5">Visibility</label>
            <div className="flex gap-2">
              {[{label:'Visible to customers', val:true},{label:'Hidden from customers', val:false}].map(({label, val}) => (
                <button key={String(val)} type="button" onClick={() => setIsActive(val)}
                  className={`flex-1 flex items-center justify-center gap-1.5 py-2.5 rounded-xl border text-xs font-medium transition-colors ${isActive===val ? (val ? 'bg-emerald-50 border-emerald-200 text-emerald-700' : 'bg-gray-100 border-gray-200 text-gray-600') : 'bg-white border-gray-100 text-gray-400 hover:bg-gray-50'}`}>
                  {val ? <Eye size={13} /> : <EyeOff size={13} />}
                  {label}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="text-xs font-medium text-gray-600 block mb-1.5">Product Image or PDF <span className="text-gray-400 font-normal">(optional)</span></label>
            <input ref={fileRef} type="file" accept=".pdf,.jpg,.jpeg,.png,.webp" className="hidden" onChange={handleFile} />
            {fileName ? (
              <div className="flex items-center gap-3 px-4 py-3 bg-blue-50 border border-blue-100 rounded-xl">
                {fileName.endsWith('.pdf') ? <FileText size={16} className="text-blue-500 shrink-0" /> : <ImageIcon size={16} className="text-blue-500 shrink-0" />}
                <span className="flex-1 text-xs text-blue-700 truncate">{fileName}</span>
                <button type="button" onClick={() => setFileName(null)} className="text-blue-400 hover:text-blue-600 transition-colors"><X size={13} /></button>
              </div>
            ) : (
              <button type="button" onClick={() => fileRef.current?.click()}
                className="w-full flex flex-col items-center gap-2 px-4 py-5 bg-gray-50 border-2 border-dashed border-gray-200 rounded-xl text-gray-400 hover:border-gray-300 hover:bg-gray-50 transition-colors">
                <Upload size={18} className="text-gray-300" />
                <span className="text-xs text-center">Click to upload a photo or PDF<br /><span className="text-gray-300">JPG, PNG, WEBP or PDF · Max 10 MB</span></span>
              </button>
            )}
          </div>
        </div>

        <div className="px-6 pb-6 pt-4 border-t border-gray-100 flex gap-2 shrink-0">
          <button type="button" onClick={onClose} className="flex-1 px-4 py-2.5 text-sm text-gray-600 bg-gray-50 border border-gray-100 rounded-xl hover:bg-gray-100 transition-colors">Cancel</button>
          <button type="button" onClick={handleSubmit} disabled={!valid}
            className="flex-1 px-4 py-2.5 text-sm text-white bg-gray-900 rounded-xl hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-1.5">
            <Check size={14} />{product ? 'Save Changes' : 'Add Product'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Delete Confirm ────────────────────────────────────────────────────────────
function DeleteConfirm({ name, onConfirm, onClose }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/20 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-sm mx-4 p-6">
        <div className="flex items-start gap-3 mb-5">
          <div className="w-9 h-9 rounded-full bg-red-50 flex items-center justify-center shrink-0"><Trash2 size={15} className="text-red-500" /></div>
          <div>
            <h3 className="text-sm font-semibold text-gray-900 mb-1">Remove this product?</h3>
            <p className="text-xs text-gray-500 leading-relaxed"><span className="font-medium text-gray-700">"{name}"</span> will be permanently removed from your catalogue. Your AI assistant will no longer be able to tell customers about it.</p>
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

// ─── Main Page ─────────────────────────────────────────────────────────────────
export default function Products() {
  const qc = useQueryClient()
  const [search, setSearch]               = useState('')
  const [catDropOpen, setCatDropOpen]     = useState(false)
  const [showModal, setShowModal]         = useState(false)
  const [editProduct, setEditProduct]     = useState(null)
  const [deleteProduct, setDeleteProduct] = useState(null)

  // ── Data ──────────────────────────────────────────────────────────────────
  const { data: products = [], isLoading } = useQuery({
    queryKey: ['products', search],
    queryFn: () => api.get('/products', { params: search ? { search } : {} }).then(r => r.data?.data?.products || []),
    placeholderData: [],
  })

  // ── Mutations ─────────────────────────────────────────────────────────────
  const createMutation = useMutation({
    mutationFn: (body) => api.post('/products', body),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['products'] }); toast.success('Product added') },
  })
  const updateMutation = useMutation({
    mutationFn: ({ id, ...body }) => api.patch(`/products/${id}`, body),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['products'] }); toast.success('Product updated') },
  })
  const toggleMutation = useMutation({
    mutationFn: (product) => api.patch(`/products/${product.id}`, { is_active: !product.is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['products'] }),
  })
  const deleteMutation = useMutation({
    mutationFn: (id) => api.delete(`/products/${id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['products'] }); toast.success('Product removed'); setDeleteProduct(null) },
  })

  // ── Handlers ──────────────────────────────────────────────────────────────
  function handleSave(data) {
    if (editProduct) {
      updateMutation.mutate({ id: editProduct.id, ...data })
    } else {
      createMutation.mutate(data)
    }
    setShowModal(false); setEditProduct(null)
  }
  function handleDelete() {
    if (!deleteProduct) return
    deleteMutation.mutate(deleteProduct.id)
  }

  // ── Derived ───────────────────────────────────────────────────────────────
  const activeCount = products.filter(p => p.is_active).length
  const hiddenCount = products.filter(p => !p.is_active).length

  return (
    <div className="flex-1 flex flex-col h-screen overflow-hidden bg-gray-50/60 -mx-8 -my-7">
      {/* Top Bar */}
      <div className="h-16 bg-white border-b border-gray-100 px-8 flex items-center justify-between shrink-0 sticky top-0 z-10">
        <div>
          <h1 className="text-base font-semibold text-gray-900">Products</h1>
          <p className="text-xs text-gray-400">Manage what your AI knows about your catalogue</p>
        </div>
        <button onClick={() => { setEditProduct(null); setShowModal(true) }}
          className="flex items-center gap-1.5 px-3.5 py-2 text-sm text-white bg-gray-900 rounded-lg hover:bg-gray-700 transition-colors">
          <Plus size={14} /> Add Product
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-8 py-6 space-y-4">
        {/* Stat Cards */}
        <div className="grid grid-cols-3 gap-4">
          {[
            { label:'Total Products',        value: products.length, sub:'In your catalogue',       icon:Package, bg:'bg-blue-50',    color:'text-blue-500'    },
            { label:'Visible to Customers',  value: activeCount,     sub:'AI can talk about these', icon:Eye,     bg:'bg-emerald-50', color:'text-emerald-500' },
            { label:'Hidden',                value: hiddenCount,     sub:'Not shown to customers',  icon:EyeOff,  bg:'bg-gray-100',   color:'text-gray-400'    },
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

        {/* Filter Bar */}
        <div className="bg-white rounded-xl border border-gray-100 flex items-center overflow-hidden">
          <div className="flex items-center flex-1 px-4 py-3 gap-3">
            <Search size={15} className="text-gray-400 shrink-0" />
            <input type="text" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search products by name or description…"
              className="flex-1 text-sm text-gray-700 placeholder-gray-400 bg-transparent focus:outline-none" />
            {search && <button onClick={() => setSearch('')} className="text-gray-300 hover:text-gray-500 transition-colors shrink-0"><X size={13} /></button>}
          </div>
          <div className="w-px h-8 bg-gray-100 shrink-0" />
          <div className="relative">
            <button onClick={() => setCatDropOpen(!catDropOpen)} className="flex items-center gap-2 px-4 py-3 text-sm hover:bg-gray-50 transition-colors whitespace-nowrap">
              <Tag size={13} className="text-gray-400" />
              <span className="text-gray-500 text-sm">All Categories</span>
              <ChevronDown size={13} className={`text-gray-400 transition-transform ${catDropOpen ? 'rotate-180' : ''}`} />
            </button>
            {catDropOpen && (
              <div className="absolute right-0 top-full mt-1 w-44 bg-white border border-gray-100 rounded-xl shadow-lg z-20 overflow-hidden">
                {CATEGORIES.map(cat => (
                  <button key={cat} onClick={() => setCatDropOpen(false)}
                    className="w-full flex items-center justify-between px-4 py-2.5 text-left hover:bg-gray-50 transition-colors text-gray-600">
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${CATEGORY_COLORS[cat] || 'bg-gray-100 text-gray-600'}`}>{cat}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Table */}
        <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
          <div className="px-5 py-3.5 border-b border-gray-50">
            <p className="text-xs text-gray-500">
              <span className="font-medium text-gray-700">{products.length}</span> product{products.length !== 1 ? 's' : ''}
              {search && <span> matching "<span className="font-medium">{search}</span>"</span>}
            </p>
          </div>

          {isLoading ? (
            <div className="py-20 flex flex-col items-center gap-3">
              <div className="w-7 h-7 border-2 border-gray-200 border-t-gray-500 rounded-full animate-spin" />
              <p className="text-xs text-gray-400">Loading products…</p>
            </div>
          ) : products.length === 0 ? (
            <div className="py-20 flex flex-col items-center gap-3">
              <div className="w-12 h-12 rounded-2xl bg-gray-100 flex items-center justify-center"><ShoppingBag size={22} className="text-gray-300" /></div>
              <div className="text-center">
                <p className="text-sm font-medium text-gray-600">No products found</p>
                <p className="text-xs text-gray-400 mt-1">{search ? 'Try a different search term.' : 'Add your first product to get started.'}</p>
              </div>
              {!search && <button onClick={() => { setEditProduct(null); setShowModal(true) }} className="mt-1 flex items-center gap-1.5 px-4 py-2 text-xs text-white bg-gray-900 rounded-lg hover:bg-gray-700 transition-colors"><Plus size={12} /> Add Product</button>}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="bg-gray-50/80 border-b border-gray-100">
                    <th className="px-5 py-3 text-left text-xs font-medium text-gray-500">Product Name</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">Price</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">Description</th>
                    <th className="px-4 py-3 text-center text-xs font-medium text-gray-500">Status</th>
                    <th className="px-4 py-3 text-center text-xs font-medium text-gray-500">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {products.map(product => (
                    <tr key={product.id} className={`border-b border-gray-50 last:border-0 hover:bg-gray-50/50 transition-colors ${!product.is_active ? 'opacity-60' : ''}`}>
                      <td className="px-5 py-3.5">
                        <div className="flex items-center gap-3">
                          <div className="w-9 h-9 rounded-xl bg-gray-100 flex items-center justify-center shrink-0"><ShoppingBag size={15} className="text-gray-400" /></div>
                          <span className="text-sm font-medium text-gray-800 max-w-[200px] truncate block">{product.name}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3.5"><span className="text-sm font-semibold text-gray-800 tabular-nums">{formatPrice(product.price)}</span></td>
                      <td className="px-4 py-3.5 max-w-xs"><p className="text-xs text-gray-500 leading-relaxed">{truncate(product.description)}</p></td>
                      <td className="px-4 py-3.5 text-center">
                        <StatusBadge status={product.is_active ? 'Active' : 'Hidden'} onToggle={() => toggleMutation.mutate(product)} />
                      </td>
                      <td className="px-4 py-3.5">
                        <div className="flex items-center justify-center gap-1">
                          <button onClick={() => { setEditProduct(product); setShowModal(true) }} className="p-1.5 rounded-lg text-gray-400 hover:text-blue-600 hover:bg-blue-50 transition-colors" title="Edit product"><Pencil size={14} /></button>
                          <button onClick={() => setDeleteProduct(product)} className="p-1.5 rounded-lg text-gray-400 hover:text-red-500 hover:bg-red-50 transition-colors" title="Remove product"><Trash2 size={14} /></button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <p className="text-xs text-gray-400 text-center pb-2">Products marked as <span className="font-medium text-gray-500">Active</span> are shared with customers by your AI assistant. Hidden products are not shown.</p>
      </div>

      {showModal && <ProductModal product={editProduct} onSave={handleSave} onClose={() => { setShowModal(false); setEditProduct(null) }} />}
      {deleteProduct && <DeleteConfirm name={deleteProduct.name} onConfirm={handleDelete} onClose={() => setDeleteProduct(null)} />}
    </div>
  )
}
