import { Article } from '@/lib/useWireData'
import { WireId, WIRE_MAP } from '@/lib/config'

interface Props {
  article: Article | null
  wire:    WireId
  onClose: () => void
}

export default function ArticleDetail({ article, wire, onClose }: Props) {
  const cfg = WIRE_MAP[wire]

  if (!article) return null

  return (
    <div
      className="flex flex-col h-full overflow-hidden fade-up"
      style={{ borderLeft: `1px solid var(--border)` }}
    >
      {/* Header */}
      <div className="flex items-start justify-between p-4 border-b" style={{ borderColor: 'var(--border)' }}>
        <div className="font-mono text-[10px] uppercase tracking-widest" style={{ color: cfg.color }}>
          {cfg.emoji} {cfg.label} dispatch
        </div>
        <button
          onClick={onClose}
          className="font-mono text-xs cursor-pointer"
          style={{ color: 'var(--muted)' }}
        >
          ✕
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        <h2
          className="leading-snug"
          style={{ fontFamily: 'var(--font-display)', fontSize: 18, fontWeight: 300 }}
        >
          {article.title}
        </h2>

        {article.snippet && (
          <p className="text-xs leading-relaxed" style={{ color: 'var(--ink2)' }}>
            {article.snippet}
          </p>
        )}

        {/* Metadata grid */}
        <div className="grid grid-cols-2 gap-3">
          {[
            { label: 'Source',    value: article.source },
            { label: 'Location',  value: article.mention_text || '—' },
            { label: 'Published', value: article.published_at || '—' },
            { label: 'Event',     value: article.event_type || '—' },
          ].map(row => (
            <div key={row.label}>
              <div className="font-mono text-[10px] uppercase tracking-widest mb-0.5" style={{ color: 'var(--muted)' }}>
                {row.label}
              </div>
              <div className="font-mono text-xs" style={{ color: 'var(--ink2)' }}>
                {row.value}
              </div>
            </div>
          ))}
        </div>

        {/* Coordinates */}
        {article.lat && article.lon && (
          <div
            className="font-mono text-[10px] px-3 py-2 rounded"
            style={{ background: 'var(--surface2)', color: 'var(--muted)' }}
          >
            {article.lat.toFixed(4)}°N, {Math.abs(article.lon).toFixed(4)}°W
            {article.osm_display && (
              <div className="mt-0.5 truncate" title={article.osm_display}>
                {article.osm_display}
              </div>
            )}
          </div>
        )}

        {/* Read link */}
        {article.url && (
          <a
            href={article.url}
            target="_blank"
            rel="noopener noreferrer"
            className="block w-full text-center font-mono text-xs py-2 rounded transition-opacity hover:opacity-80"
            style={{ background: `${cfg.color}20`, color: cfg.color, border: `1px solid ${cfg.color}40` }}
          >
            Read full article →
          </a>
        )}
      </div>
    </div>
  )
}
