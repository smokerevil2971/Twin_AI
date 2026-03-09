import { Bell } from 'lucide-react'
import { useLocation } from 'react-router-dom'

export default function TopHeader({ onNewBroadcast }) {
  const { pathname } = useLocation()
  const isDashboard = pathname === '/dashboard'

  return (
    <header
      className="flex items-center justify-between px-6 h-14 border-b border-border shrink-0 gap-4"
      style={{ background: 'var(--bg-card)' }}
    >
      {/* Only show page title on non-dashboard pages */}
      {!isDashboard ? (
        <h1 className="text-base font-semibold text-text-primary whitespace-nowrap">
          {pathname.split('/')[1]?.replace('-', ' ').replace(/\b\w/g, c => c.toUpperCase()) || 'Dashboard'}
        </h1>
      ) : (
        <div className="flex-1" />
      )}

      {/* Right actions */}
      <div className="flex items-center gap-2 ml-auto">
        <button className="relative p-2 rounded-lg hover:bg-bg-raised text-text-secondary hover:text-text-primary transition-colors">
          <Bell size={16} />
          <span className="absolute top-1.5 right-1.5 w-1.5 h-1.5 bg-danger rounded-full" />
        </button>
      </div>
    </header>
  )
}
