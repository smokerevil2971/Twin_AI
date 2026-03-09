import { useQuery } from '@tanstack/react-query'
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis,
  CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import api from '../api/client'

function useAnalytics() {
  return useQuery({
    queryKey: ['analytics'],
    queryFn: () => api.get('/analytics').then(r => r.data?.data),
    placeholderData: {
      delivery_trend: [],
      bot_stats: [],
    },
  })
}

const CHART_STYLE = {
  background: 'transparent',
  fontFamily: 'Inter, sans-serif',
  fontSize: 12,
}

const tooltipStyle = {
  contentStyle: { background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8, color: 'var(--text-primary)', fontSize: 12 },
  labelStyle: { color: 'var(--text-secondary)' },
}

export default function Analytics() {
  const { data: analytics } = useAnalytics()

  const trend   = analytics?.delivery_trend || []
  const botData = analytics?.bot_stats || []

  return (
    <div className="space-y-6" style={{ animation: 'fadeIn 0.3s ease-out' }}>
      <div>
        <h2 className="text-xl font-semibold text-text-primary">Analytics</h2>
        <p className="text-sm text-text-secondary mt-0.5">Performance metrics for broadcasts and the AI bot.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Delivery Trend */}
        <div className="card">
          <h3 className="text-sm font-semibold text-text-primary mb-4">Delivery & Read Rate Trend</h3>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={trend} style={CHART_STYLE}>
              <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
              <XAxis dataKey="date" tick={{ fill: '#6B7280', fontSize: 11 }} />
              <YAxis tick={{ fill: '#6B7280', fontSize: 11 }} unit="%" />
              <Tooltip {...tooltipStyle} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line type="monotone" dataKey="delivery_rate" stroke="#1A56A0" strokeWidth={2} dot={false} name="Delivery %" />
              <Line type="monotone" dataKey="read_rate"     stroke="#22C55E" strokeWidth={2} dot={false} name="Read %" />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Bot Resolution */}
        <div className="card">
          <h3 className="text-sm font-semibold text-text-primary mb-4">Bot Resolution vs Escalation (Daily)</h3>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={botData} style={CHART_STYLE}>
              <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
              <XAxis dataKey="date" tick={{ fill: '#6B7280', fontSize: 11 }} />
              <YAxis tick={{ fill: '#6B7280', fontSize: 11 }} />
              <Tooltip {...tooltipStyle} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="resolved"  fill="#22C55E" name="Resolved"  radius={[4,4,0,0]} stackId="a" />
              <Bar dataKey="escalated" fill="#F59E0B" name="Escalated" radius={[4,4,0,0]} stackId="a" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Reply Rate */}
        <div className="card">
          <h3 className="text-sm font-semibold text-text-primary mb-4">Reply Rate by Broadcast</h3>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={analytics?.reply_rate_by_broadcast || []} layout="vertical" style={CHART_STYLE}>
              <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
              <XAxis type="number" tick={{ fill: '#6B7280', fontSize: 11 }} unit="%" />
              <YAxis type="category" dataKey="name" tick={{ fill: '#6B7280', fontSize: 11 }} width={120} />
              <Tooltip {...tooltipStyle} />
              <Bar dataKey="reply_rate" fill="#6C63FF" name="Reply %" radius={[0,4,4,0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Escalation Rate */}
        <div className="card">
          <h3 className="text-sm font-semibold text-text-primary mb-4">Escalation Rate (Daily)</h3>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={botData} style={CHART_STYLE}>
              <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
              <XAxis dataKey="date" tick={{ fill: '#6B7280', fontSize: 11 }} />
              <YAxis tick={{ fill: '#6B7280', fontSize: 11 }} unit="%" />
              <Tooltip {...tooltipStyle} />
              <Line type="monotone" dataKey="escalation_rate" stroke="#EF4444" strokeWidth={2} dot={false} name="Escalation %" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  )
}
