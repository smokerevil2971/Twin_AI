import { TrendingUp, TrendingDown, Minus } from 'lucide-react'
import clsx from 'clsx'

export default function KPICard({ icon: Icon, label, value, sub, trend, accentColor = '#6C63FF', onClick }) {
  const trendColor = trend > 0 ? '#22C55E' : trend < 0 ? '#EF4444' : '#94A3B8'
  const TrendIcon  = trend > 0 ? TrendingUp : trend < 0 ? TrendingDown : Minus

  return (
    <div
      onClick={onClick}
      className={clsx(
        'card card-hover relative overflow-hidden flex flex-col gap-3',
        onClick && 'cursor-pointer'
      )}
    >
      {/* Icon */}
      <div className="flex items-center justify-between">
        <span className="text-text-secondary text-sm font-medium">{label}</span>
        {Icon && (
          <div
            className="w-9 h-9 rounded-lg flex items-center justify-center"
            style={{ background: `${accentColor}20` }}
          >
            <Icon size={18} style={{ color: accentColor }} />
          </div>
        )}
      </div>

      {/* Value */}
      <div className="text-[32px] font-bold text-text-primary leading-none">{value ?? '—'}</div>

      {/* Sub + trend */}
      {(sub || trend !== undefined) && (
        <div className="flex items-center justify-between">
          {sub && <span className="text-text-muted text-xs">{sub}</span>}
          {trend !== undefined && (
            <div className="flex items-center gap-1" style={{ color: trendColor }}>
              <TrendIcon size={12} />
              <span className="text-xs font-semibold">{Math.abs(trend)}%</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
