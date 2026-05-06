import { Article } from '@/lib/useWireData'
import { WireId, WIRE_MAP } from '@/lib/config'

interface Props {
  articles:    Article[]
  wire:        WireId
  lastUpdated: string | null
}

export default function StatsBar({ articles, wire, lastUpdated }: Props) {
  const cfg       = WIRE_MAP[wire]
  const geocoded  = articles.filter(a => a.geocoded).length
  const pct       = articles.length ? Math.round((geocoded / articles.length) * 100) : 0
  const sources   = new Set(articles.map(a => a.source).filter(Boolean)).size

  const updated = lastUpdated
    ? new Date(lastUpdated).toLocaleString('en-US', {
        month: 'short', day: 'numeric',
        hour: 'numeric', minute: '2-digit',
      })
    : 'Never'

  const stats = [
    { label: 'Articles',   value: articles.length },
    { label: 'Mapped',     value: geocoded },
    { label: 'Coverage',   value: `${pct}%` },
    { label: 'Sources',    value: sources },
    { label: 'Updated',    value: updated },
  ]

  return (
    <div className="flex items-center gap-6 flex-wrap">
      {stats.map(s => (
        <div key={s.label}>
          <div className="font-mono text-[10px] uppercase tracking-widest" style={{ color: 'var(--muted)' }}>
            {s.label}
          </div>
          <div className="font-mono text-sm font-medium" style={{ color: cfg.color }}>
            {s.value}
          </div>
        </div>
      ))}
    </div>
  )
}
