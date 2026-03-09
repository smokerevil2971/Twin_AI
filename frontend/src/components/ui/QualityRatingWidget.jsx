import clsx from 'clsx'

const CONFIG = {
  green:  { dot: '#22C55E', label: 'Green',  sub: 'Quality: Excellent' },
  yellow: { dot: '#F59E0B', label: 'Yellow', sub: 'Quality: Warning—reduce frequency' },
  red:    { dot: '#EF4444', label: 'Red',    sub: 'Quality: Critical—broadcasts paused' },
}

export default function QualityRatingWidget({ rating = 'green', compact = false }) {
  const cfg = CONFIG[rating] || CONFIG.green
  const isPulse = rating !== 'green'

  return (
    <div className={clsx('flex items-center gap-2', compact ? 'p-2' : 'px-3 py-2 rounded-lg bg-bg-raised border border-border')}>
      <span
        className={clsx('w-2.5 h-2.5 rounded-full shrink-0', isPulse && 'animate-pulse')}
        style={{ background: cfg.dot }}
      />
      {!compact && (
        <div>
          <p className="text-xs font-semibold text-text-primary">WhatsApp Quality</p>
          <p className="text-[10px] text-text-muted">{cfg.sub}</p>
        </div>
      )}
    </div>
  )
}
