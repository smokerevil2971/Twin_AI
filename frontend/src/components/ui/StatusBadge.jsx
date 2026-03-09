const BADGE_CONFIG = {
  sent:       { bg: '#E0F2FE', text: '#0EA5E9',  label: 'SENT'       },
  delivered:  { bg: '#EBF3FB', text: '#1A56A0',  label: 'DELIVERED'  },
  read:       { bg: '#E8FAF0', text: '#22C55E',  label: 'READ'       },
  failed:     { bg: '#FEE2E2', text: '#EF4444',  label: 'FAILED'     },
  scheduled:  { bg: '#FEF3E2', text: '#F59E0B',  label: 'SCHEDULED'  },
  draft:      { bg: '#F1F5F9', text: '#475569',  label: 'DRAFT'      },
  flagged:    { bg: '#FEE2E2', text: '#EF4444',  label: 'FLAGGED'    },
  resolved:   { bg: '#E8FAF0', text: '#22C55E',  label: 'RESOLVED'   },
  indexed:    { bg: '#E8FAF0', text: '#22C55E',  label: 'INDEXED'    },
  processing: { bg: '#FEF3E2', text: '#F59E0B',  label: 'PROCESSING' },
  failed_kb:  { bg: '#FEE2E2', text: '#EF4444',  label: 'FAILED'     },
  active:     { bg: '#E8FAF0', text: '#22C55E',  label: 'ACTIVE'     },
  expired:    { bg: '#F1F5F9', text: '#475569',  label: 'EXPIRED'    },
  opted_in:   { bg: '#E8FAF0', text: '#22C55E',  label: 'OPT-IN'     },
  opted_out:  { bg: '#FEE2E2', text: '#EF4444',  label: 'OPT-OUT'    },
}

export default function StatusBadge({ status }) {
  const cfg = BADGE_CONFIG[status?.toLowerCase()] || {
    bg: 'var(--bg-card)', text: '#94A3B8', label: status?.toUpperCase() || 'UNKNOWN',
  }
  return (
    <span
      style={{
        background: cfg.bg,
        color: cfg.text,
        padding: '3px 8px',
        borderRadius: 4,
        fontSize: 11,
        fontWeight: 600,
        letterSpacing: '0.05em',
        whiteSpace: 'nowrap',
      }}
    >
      {cfg.label}
    </span>
  )
}
