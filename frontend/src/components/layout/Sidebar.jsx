import { NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard, Users, Radio, MessageSquare,
  ShoppingBag, Tag, BookOpen, BarChart2, Settings, MessageCircle, LogOut, Percent, Package
} from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import clsx from 'clsx'

const navItems = [
  { to: '/dashboard',      icon: LayoutDashboard, label: 'Dashboard'      },
  { to: '/clients',        icon: Users,            label: 'Clients'        },
  { to: '/broadcasts',     icon: Radio,            label: 'Broadcasts'     },
  { to: '/conversations',  icon: MessageSquare,    label: 'Conversations'  },
  { to: '/products',       icon: ShoppingBag,      label: 'Products'       },
  { to: '/offers',         icon: Percent,          label: 'Offers'         },
  { to: '/orders',         icon: Package,          label: 'Orders'         },
  { to: '/knowledge-base', icon: BookOpen,         label: 'Knowledge Base' },
  { to: '/analytics',      icon: BarChart2,        label: 'Analytics'      },
  { to: '/settings',       icon: Settings,         label: 'Settings'       },
]

function NavItem({ to, icon: Icon, label }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        clsx(
          'w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors text-left',
          isActive
            ? 'bg-gray-100 text-gray-900'
            : 'text-gray-500 hover:bg-gray-50 hover:text-gray-700'
        )
      }
    >
      {({ isActive }) => (
        <>
          <Icon size={16} className={isActive ? 'text-gray-800' : 'text-gray-400'} />
          <span>{label}</span>
        </>
      )}
    </NavLink>
  )
}

export default function Sidebar() {
  const { user, logout } = useAuth()
  const name = (() => {
    try {
      const s = JSON.parse(localStorage.getItem('twinai_user') || '{}')
      return s.business_name || user?.email?.split('@')[0] || 'Owner'
    } catch { return user?.email?.split('@')[0] || 'Owner' }
  })()
  const initial = name[0]?.toUpperCase() || 'K'

  return (
    <aside className="w-56 shrink-0 h-screen bg-white border-r border-gray-100 flex flex-col">
      {/* Logo */}
      <div className="h-16 flex items-center px-5 border-b border-gray-100">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-emerald-500 flex items-center justify-center">
            <MessageCircle size={14} className="text-white" />
          </div>
          <span className="text-sm font-semibold text-gray-800 tracking-tight">Twin AI</span>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
        {navItems.map(item => <NavItem key={item.to} {...item} />)}
      </nav>

      {/* User */}
      <div className="px-3 py-4 border-t border-gray-100">
        <div className="flex items-center gap-3 px-3 py-2 group">
          <div className="w-7 h-7 rounded-full bg-gray-200 flex items-center justify-center text-xs text-gray-600 font-medium shrink-0">
            {initial}
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-xs font-medium text-gray-700 truncate">{name}</p>
            <p className="text-xs text-gray-400">Admin</p>
          </div>
          <button
            onClick={logout}
            title="Logout"
            className="p-1 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-colors opacity-0 group-hover:opacity-100"
          >
            <LogOut size={13} />
          </button>
        </div>
      </div>
    </aside>
  )
}
