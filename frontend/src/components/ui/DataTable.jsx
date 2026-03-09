import { useState, useMemo } from 'react'
import { ChevronUp, ChevronDown, ChevronLeft, ChevronRight } from 'lucide-react'
import clsx from 'clsx'

const PAGE_SIZES = [10, 25, 50]

function Skeleton() {
  return (
    <div className="space-y-2 py-2">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="skeleton h-10 w-full" />
      ))}
    </div>
  )
}

export default function DataTable({ columns, data, isLoading, emptyMessage = 'No data yet.', actions }) {
  const [sortKey, setSortKey]     = useState(null)
  const [sortDir, setSortDir]     = useState('asc')
  const [page, setPage]           = useState(1)
  const [pageSize, setPageSize]   = useState(10)

  const sorted = useMemo(() => {
    if (!sortKey) return data || []
    return [...(data || [])].sort((a, b) => {
      const av = a[sortKey] ?? ''
      const bv = b[sortKey] ?? ''
      return sortDir === 'asc' ? (av > bv ? 1 : -1) : (av < bv ? 1 : -1)
    })
  }, [data, sortKey, sortDir])

  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize))
  const paginated  = sorted.slice((page - 1) * pageSize, page * pageSize)

  function toggleSort(key) {
    if (!key) return
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('asc') }
  }

  return (
    <div className="w-full overflow-x-auto rounded-card border border-border">
      <table className="w-full border-collapse">
        <thead>
          <tr className="border-b border-border bg-bg-raised">
            {columns.map(col => (
              <th
                key={col.key}
                onClick={() => col.sortable !== false && toggleSort(col.key)}
                className={clsx(
                  'text-left px-4 py-3 text-xs font-semibold text-text-secondary select-none whitespace-nowrap',
                  col.sortable !== false && 'cursor-pointer hover:text-text-primary'
                )}
                style={{ minWidth: col.width }}
              >
                <div className="flex items-center gap-1">
                  {col.label}
                  {col.sortable !== false && sortKey === col.key && (
                    sortDir === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />
                  )}
                </div>
              </th>
            ))}
            {actions && <th className="px-4 py-3 text-xs font-semibold text-text-secondary text-right">Actions</th>}
          </tr>
        </thead>
        <tbody>
          {isLoading ? (
            <tr><td colSpan={columns.length + (actions ? 1 : 0)} className="px-4 py-2"><Skeleton /></td></tr>
          ) : paginated.length === 0 ? (
            <tr>
              <td colSpan={columns.length + (actions ? 1 : 0)} className="text-center py-12 text-text-secondary text-sm">
                {emptyMessage}
              </td>
            </tr>
          ) : (
            paginated.map((row, i) => (
              <tr
                key={row.id || i}
                className="border-b border-border last:border-0 hover:bg-bg-raised transition-colors"
                style={{ background: i % 2 === 0 ? 'transparent' : 'rgba(0,0,0,0.02)' }}
              >
                {columns.map(col => (
                  <td key={col.key} className="px-4 py-3 text-sm text-text-primary">
                    {col.render ? col.render(row) : (row[col.key] ?? '—')}
                  </td>
                ))}
                {actions && (
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-1">{actions(row)}</div>
                  </td>
                )}
              </tr>
            ))
          )}
        </tbody>
      </table>

      {/* Pagination */}
      {!isLoading && sorted.length > 0 && (
        <div className="flex items-center justify-between px-4 py-3 border-t border-border">
          <div className="flex items-center gap-2 text-sm text-text-secondary">
            <span>Rows:</span>
            <select
              value={pageSize}
              onChange={e => { setPageSize(Number(e.target.value)); setPage(1) }}
              className="bg-bg-raised border border-border rounded px-2 py-1 text-text-primary text-sm"
            >
              {PAGE_SIZES.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
            <span>{(page - 1) * pageSize + 1}–{Math.min(page * pageSize, sorted.length)} of {sorted.length}</span>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page === 1}
              className="p-1.5 rounded hover:bg-bg-raised disabled:opacity-40 text-text-secondary"
            >
              <ChevronLeft size={16} />
            </button>
            <span className="px-3 text-sm text-text-primary">{page} / {totalPages}</span>
            <button
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="p-1.5 rounded hover:bg-bg-raised disabled:opacity-40 text-text-secondary"
            >
              <ChevronRight size={16} />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
