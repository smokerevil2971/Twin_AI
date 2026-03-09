import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  Users, Tag, Radio, Bot,
  CheckCircle2, Eye, MessageCircle,
  AlertTriangle, TrendingUp, TrendingDown,
  ChevronRight, Send, ArrowUpRight, X, Flag,
} from 'lucide-react'
import api from '../api/client'
import { format } from 'date-fns'

function useDashboardStats() {
  return useQuery({
    queryKey: ['dashboard-stats'],
    queryFn: () => api.get('/dashboard/stats').then(r => r.data?.data),
    placeholderData: {
      total_clients: 0, opted_in: 0,
      broadcasts_this_month: 0, delivery_rate: 0,
      bot_resolution_rate: 0, active_offers: 0,
      flagged_count: 0,
    },
  })
}

function useRecentBroadcasts() {
  return useQuery({
    queryKey: ['broadcasts', { limit: 5 }],
    queryFn: () => api.get('/broadcasts?limit=5').then(r => r.data?.data?.broadcasts || []),
    placeholderData: [],
  })
}

function getGreeting() {
  const h = new Date().getHours()
  return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening'
}

function getDisplayName() {
  try {
    const s = JSON.parse(localStorage.getItem('twinai_user') || '{}')
    if (s.business_name) return s.business_name.split(' ')[0]
  } catch (_) {}
  return 'there'
}

function deliveryRate(sent, delivered) {
  return sent > 0 ? Math.round((delivered / sent) * 100) : 0
}
function readRate(delivered, read) {
  return delivered > 0 ? Math.round((read / delivered) * 100) : 0
}

export default function Dashboard() {
  const { data: stats } = useDashboardStats()
  const { data: broadcasts = [], isLoading } = useRecentBroadcasts()
  const [alert, setAlert] = useState(true)

  const latest = broadcasts[0]
  const latestDelivery = latest ? deliveryRate(latest.sent_count || 0, latest.delivered_count || 0) : 0
  const latestRead     = latest ? readRate(latest.delivered_count || 0, latest.read_count || 0) : 0
  const latestReply    = latest && latest.delivered_count > 0
    ? Math.round(((latest.replied_count || 0) / latest.delivered_count) * 100) : 0

  const statCards = [
    {
      id: 'clients', icon: Users, label: 'Total Clients',
      value: (stats?.total_clients ?? 0).toLocaleString(),
      sub: `+${stats?.opted_in ?? 0} opted-in`, trend: 'up',
      iconBg: 'bg-blue-50', iconColor: 'text-blue-500', trendColor: 'text-emerald-600',
    },
    {
      id: 'offers', icon: Tag, label: 'Active Offers',
      value: String(stats?.active_offers ?? 0),
      sub: `${stats?.broadcasts_this_month ?? 0} broadcasts this month`, trend: 'neutral',
      iconBg: 'bg-violet-50', iconColor: 'text-violet-500', trendColor: 'text-amber-500',
    },
    {
      id: 'broadcast', icon: Radio, label: 'Last Broadcast',
      value: latest ? 'Sent' : '—',
      valueSub: latest ? format(new Date(latest.created_at), 'MMM d, h:mm a') : '',
      sub: latest ? `${(latest.delivered_count || 0).toLocaleString()} messages delivered` : 'No broadcasts yet',
      trend: 'up',
      iconBg: 'bg-emerald-50', iconColor: 'text-emerald-500', trendColor: 'text-emerald-600',
      badge: latest ? { label: 'Delivered', color: 'bg-emerald-100 text-emerald-700' } : null,
    },
    {
      id: 'bot', icon: Bot, label: 'Bot Resolution Rate',
      value: `${stats?.bot_resolution_rate ?? 0}%`,
      sub: 'Bot handled without owner help', trend: 'up',
      iconBg: 'bg-amber-50', iconColor: 'text-amber-500', trendColor: 'text-emerald-600',
      progressValue: stats?.bot_resolution_rate ?? 0,
    },
    {
      id: 'flagged', icon: Flag, label: 'Flagged Conversations',
      value: String(stats?.flagged_count ?? 0),
      sub: 'Needs manual review',
      trend: (stats?.flagged_count ?? 0) > 0 ? 'down' : 'neutral',
      iconBg: 'bg-red-50', iconColor: 'text-red-400', trendColor: (stats?.flagged_count ?? 0) > 0 ? 'text-red-500' : 'text-gray-400',
      link: '/conversations',
    },
  ]

  const today = format(new Date(), "EEEE, d MMMM yyyy")

  return (
    <div className="flex-1 overflow-y-auto bg-gray-50/60 min-h-screen -mx-8 -my-7">
      {/* Sticky top bar */}
      <div className="h-16 bg-white border-b border-gray-100 px-8 flex items-center justify-between sticky top-0 z-10">
        <div>
          <h1 className="text-base font-semibold text-gray-900">
            {getGreeting()}, {getDisplayName()} 👋
          </h1>
          <p className="text-xs text-gray-400">{today} · Here's how your store is doing today</p>
        </div>
        <Link
          to="/broadcasts"
          className="flex items-center gap-2 px-3 py-2 bg-gray-900 text-white text-xs rounded-lg hover:bg-gray-700 transition-colors"
        >
          <Send size={13} /> New Broadcast
        </Link>
      </div>

      <div className="px-8 py-7 space-y-7">

        {/* Alert */}
        {alert && (
          <div className="flex items-start gap-3 bg-amber-50 border border-amber-200 rounded-xl px-5 py-4">
            <AlertTriangle size={18} className="text-amber-500 shrink-0 mt-0.5" />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-amber-800">Your WhatsApp sending quality is below normal</p>
              <p className="text-xs text-amber-700 mt-0.5 leading-relaxed">
                Too many customers have been blocking or reporting your messages recently. If this continues,
                WhatsApp may limit how many messages you can send per day.{' '}
                <span className="underline cursor-pointer">See what to do →</span>
              </p>
            </div>
            <button onClick={() => setAlert(false)} className="shrink-0 text-xs text-amber-600 hover:text-amber-800 transition-colors mt-0.5">
              Dismiss
            </button>
          </div>
        )}

        {/* Stat Cards */}
        <div className="grid grid-cols-5 gap-5">
          {statCards.map(card => {
            const Icon = card.icon
            const inner = (
              <div key={card.id} className="bg-white rounded-xl border border-gray-100 px-5 py-5 flex flex-col gap-3 hover:shadow-sm transition-shadow">
                <div className="flex items-center justify-between">
                  <div className={`w-9 h-9 rounded-lg ${card.iconBg} flex items-center justify-center`}>
                    <Icon size={17} className={card.iconColor} />
                  </div>
                  {card.badge && (
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${card.badge.color}`}>
                      {card.badge.label}
                    </span>
                  )}
                </div>
                <div>
                  <p className="text-xs text-gray-400 mb-0.5">{card.label}</p>
                  <div className="flex items-end gap-1.5">
                    <span className="text-3xl font-semibold text-gray-900 leading-none tracking-tight">
                      {card.value}
                    </span>
                    {card.valueSub && (
                      <span className="text-xs text-gray-400 mb-0.5">{card.valueSub}</span>
                    )}
                  </div>
                </div>
                {card.progressValue !== undefined && (
                  <div className="w-full bg-gray-100 rounded-full h-1.5">
                    <div className="bg-emerald-500 h-1.5 rounded-full" style={{ width: `${card.progressValue}%` }} />
                  </div>
                )}
                <div className="flex items-center gap-1">
                  {card.trend === 'up'   && <TrendingUp   size={12} className={card.trendColor} />}
                  {card.trend === 'down' && <TrendingDown size={12} className={card.trendColor} />}
                  <span className={`text-xs ${card.trendColor}`}>{card.sub}</span>
                </div>
              </div>
            )
            return card.link
              ? <Link key={card.id} to={card.link} className="block">{inner}</Link>
              : <div key={card.id}>{inner}</div>
          })}
        </div>

        {/* Bottom Row */}
        <div className="grid grid-cols-3 gap-5 items-start">

          {/* Broadcasts Table — 2 cols */}
          <div className="col-span-2 bg-white rounded-xl border border-gray-100 overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold text-gray-900">Recent Broadcasts</h2>
                <p className="text-xs text-gray-400 mt-0.5">Messages you've sent to your customer list</p>
              </div>
              <Link to="/broadcasts" className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 transition-colors">
                View all <ChevronRight size={13} />
              </Link>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-gray-50">
                    <th className="px-5 py-3 text-left text-xs text-gray-400 font-medium">Broadcast Name</th>
                    <th className="px-4 py-3 text-left text-xs text-gray-400 font-medium">Date Sent</th>
                    <th className="px-4 py-3 text-center text-xs text-gray-400 font-medium">
                      <div className="flex items-center justify-center gap-1"><Send size={11} /> Sent</div>
                    </th>
                    <th className="px-4 py-3 text-center text-xs text-gray-400 font-medium">
                      <div className="flex items-center justify-center gap-1"><CheckCircle2 size={11} /> Delivered</div>
                    </th>
                    <th className="px-4 py-3 text-center text-xs text-gray-400 font-medium">
                      <div className="flex items-center justify-center gap-1"><Eye size={11} /> Read</div>
                    </th>
                    <th className="px-4 py-3 text-center text-xs text-gray-400 font-medium">
                      <div className="flex items-center justify-center gap-1"><MessageCircle size={11} /> Replied</div>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {isLoading ? (
                    Array.from({ length: 4 }).map((_, i) => (
                      <tr key={i} className="border-b border-gray-50">
                        <td colSpan={6} className="px-5 py-4">
                          <div className="skeleton h-3 w-full" />
                        </td>
                      </tr>
                    ))
                  ) : broadcasts.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="px-5 py-12 text-center text-xs text-gray-400">
                        No broadcasts yet. Create your first broadcast!
                      </td>
                    </tr>
                  ) : (
                    broadcasts.map((b, idx) => {
                      const sent      = b.sent_count      || 0
                      const delivered = b.delivered_count || 0
                      const read      = b.read_count      || 0
                      const replied   = b.replied_count   || 0
                      const dr = deliveryRate(sent, delivered)
                      const rr = readRate(delivered, read)
                      return (
                        <tr key={b.id} className={`border-b border-gray-50 hover:bg-gray-50/60 transition-colors ${idx === 0 ? 'bg-emerald-50/30' : ''}`}>
                          <td className="px-5 py-3.5">
                            <div className="flex items-center gap-2">
                              <div className={`w-1.5 h-1.5 rounded-full ${idx === 0 ? 'bg-emerald-500' : 'bg-gray-300'}`} />
                              <span className="text-sm text-gray-800 font-medium">{b.name || b.template_text?.slice(0, 35) + '…'}</span>
                              {idx === 0 && (
                                <span className="text-xs bg-emerald-100 text-emerald-700 px-1.5 py-0.5 rounded-full">Latest</span>
                              )}
                            </div>
                          </td>
                          <td className="px-4 py-3.5">
                            <span className="text-xs text-gray-500">{b.created_at ? format(new Date(b.created_at), 'EEE, d MMM') : '—'}</span>
                          </td>
                          <td className="px-4 py-3.5 text-center">
                            <span className="text-sm text-gray-700">{sent.toLocaleString()}</span>
                          </td>
                          <td className="px-4 py-3.5 text-center">
                            <div className="flex flex-col items-center gap-0.5">
                              <span className="text-sm text-gray-700">{delivered.toLocaleString()}</span>
                              <span className={`text-xs font-medium ${dr >= 97 ? 'text-emerald-600' : dr >= 90 ? 'text-amber-500' : 'text-red-500'}`}>{dr}%</span>
                            </div>
                          </td>
                          <td className="px-4 py-3.5 text-center">
                            <div className="flex flex-col items-center gap-0.5">
                              <span className="text-sm text-gray-700">{read.toLocaleString()}</span>
                              <span className={`text-xs font-medium ${rr >= 65 ? 'text-emerald-600' : rr >= 50 ? 'text-amber-500' : 'text-red-500'}`}>{rr}%</span>
                            </div>
                          </td>
                          <td className="px-4 py-3.5 text-center">
                            <span className="text-sm text-gray-700">{replied.toLocaleString()}</span>
                          </td>
                        </tr>
                      )
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Right Column */}
          <div className="flex flex-col gap-5">

            {/* Last Broadcast Results */}
            <div className="bg-white rounded-xl border border-gray-100 px-5 py-5">
              <div className="flex items-center justify-between mb-1">
                <h3 className="text-sm font-semibold text-gray-900">Last Broadcast Results</h3>
                <span className="text-xs text-gray-400">Today</span>
              </div>
              <p className="text-xs text-gray-400 mb-5">How your most recent message performed</p>

              {latest ? (
                <div className="space-y-4">
                  {[
                    { icon: CheckCircle2, label: 'Delivered',    pct: latestDelivery, count: latest.delivered_count || 0, color: 'bg-emerald-500', iconColor: 'text-emerald-500' },
                    { icon: Eye,          label: 'Opened & Read', pct: latestRead,    count: latest.read_count || 0,      color: 'bg-blue-500',    iconColor: 'text-blue-500'    },
                    { icon: MessageCircle,label: 'Replied',       pct: latestReply,   count: latest.replied_count || 0,   color: 'bg-violet-500',  iconColor: 'text-violet-500'  },
                  ].map(({ icon: Icon, label, pct, count, color, iconColor }) => (
                    <div key={label}>
                      <div className="flex items-center justify-between mb-1.5">
                        <div className="flex items-center gap-1.5">
                          <Icon size={13} className={iconColor} />
                          <span className="text-xs text-gray-600">{label}</span>
                        </div>
                        <div className="flex items-center gap-1.5">
                          <span className="text-xs font-semibold text-gray-800">{pct}%</span>
                          <span className="text-xs text-gray-400">{count.toLocaleString()} people</span>
                        </div>
                      </div>
                      <div className="w-full bg-gray-100 rounded-full h-2">
                        <div className={`${color} h-2 rounded-full transition-all`} style={{ width: `${pct}%` }} />
                      </div>
                    </div>
                  ))}
                  <div className="mt-5 pt-4 border-t border-gray-100 flex items-start gap-2">
                    <ArrowUpRight size={13} className="text-emerald-500 mt-0.5 shrink-0" />
                    <p className="text-xs text-gray-500 leading-relaxed">
                      Your read rate is <span className="font-semibold text-gray-700">above average</span>. Sending at 9 AM on weekdays tends to get more opens.
                    </p>
                  </div>
                </div>
              ) : (
                <p className="text-xs text-gray-400 text-center py-6">No broadcast data yet</p>
              )}
            </div>

            {/* Quick Actions */}
            <div className="bg-white rounded-xl border border-gray-100 px-5 py-5">
              <h3 className="text-sm font-semibold text-gray-900 mb-1">Quick Actions</h3>
              <p className="text-xs text-gray-400 mb-4">Common things you might want to do</p>
              <div className="space-y-2">
                {[
                  { label: 'Send a broadcast message', icon: Radio,         color: 'text-emerald-600 bg-emerald-50', to: '/broadcasts'     },
                  { label: 'View new conversations',   icon: MessageCircle, color: 'text-blue-600 bg-blue-50',      to: '/conversations'   },
                  { label: 'Add to Knowledge Base',    icon: Tag,           color: 'text-violet-600 bg-violet-50',  to: '/knowledge-base'  },
                  { label: 'Check your client list',   icon: Users,         color: 'text-amber-600 bg-amber-50',    to: '/clients'         },
                ].map(({ label, icon: Icon, color, to }) => (
                  <Link
                    key={to}
                    to={to}
                    className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-gray-50 transition-colors text-left group"
                  >
                    <div className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 ${color}`}>
                      <Icon size={13} />
                    </div>
                    <span className="text-xs text-gray-700 flex-1">{label}</span>
                    <ChevronRight size={13} className="text-gray-300 group-hover:text-gray-400 transition-colors" />
                  </Link>
                ))}
              </div>
            </div>

          </div>
        </div>
      </div>
    </div>
  )
}
