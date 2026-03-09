export default function ConfidenceScoreBadge({ score }) {
  if (score === null || score === undefined) return null
  const pct   = Math.round(score * 100)
  const color = score >= 0.9 ? '#22C55E' : score >= 0.75 ? '#F59E0B' : '#EF4444'
  return (
    <span
      style={{
        color,
        fontSize: 11,
        fontWeight: 600,
        letterSpacing: '0.03em',
      }}
    >
      ⬤ {pct}% confidence
    </span>
  )
}
