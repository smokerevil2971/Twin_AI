import { format } from 'date-fns'
import ConfidenceScoreBadge from './ConfidenceScoreBadge'
import clsx from 'clsx'

export default function ChatBubble({ message, isInbound, clientName, timestamp, confidence, flagged }) {
  return (
    <div className={clsx('flex flex-col gap-1 max-w-[80%]', isInbound ? 'self-start' : 'self-end')}>
      {/* Sender label */}
      <span className="text-xs text-text-muted px-1">
        {isInbound ? (clientName || 'Client') : 'Bot'}
        {timestamp && ` · ${format(new Date(timestamp), 'h:mm a')}`}
      </span>

      {/* Bubble */}
      <div
        className={clsx('rounded-xl px-4 py-2.5 text-sm leading-relaxed', flagged && 'ring-1 ring-danger')}
        style={{
          background: isInbound
            ? (flagged ? 'rgba(239,68,68,0.12)' : 'var(--bg-raised)')
            : '#1A56A0',
          color: '#fff',
          borderRadius: isInbound ? '4px 16px 16px 16px' : '16px 4px 16px 16px',
        }}
      >
        {message}
        {flagged && (
          <div className="mt-1.5 text-[10px] font-semibold text-danger flex items-center gap-1">
            🚩 Needs review
          </div>
        )}
      </div>

      {/* Confidence score for bot messages */}
      {!isInbound && confidence !== undefined && (
        <div className="px-1">
          <ConfidenceScoreBadge score={confidence} />
        </div>
      )}
    </div>
  )
}
