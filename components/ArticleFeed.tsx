import { Article } from '@/lib/useWireData'
import { WireId, WIRE_MAP } from '@/lib/config'
import clsx from 'clsx'

interface Props {
  articles:  Article[]
  wire:      WireId
  selected:  Article | null
  onSelect:  (a: Article) => void
}

function timeAgo(dateStr: string) {
  if (!dateStr) return ''
  try {
    const d = new Date(dateStr)
    const diff = Date.now() - d.getTime()
    const h = Math.floor(diff / 3_600_000)
    if (h < 1)  return 'just now'
    if (h < 24) return `${h}h ago`
    return `${Math.floor(h / 24)}d ago`
  } catch { return '' }
}

export default function ArticleFeed({ articles, wire, selected, onSelect }: Props) {
  const cfg = WIRE_MAP[wire]
  const sorted = [...articles].sort((a, b) =>
    new Date(b.fetched_at).getTime() - new Date(a.fetched_at).getTime()
  )

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="px-4 py-3 border-b" style={{ borderColor: 'var(--border)' }}>
        <div className="font-mono text-xs uppercase tracking-widest" style={{ color: 'var(--muted)' }}>
          Latest dispatches
        </div>
        <div className="font-mono text-xs mt-0.5" style={{ color: cfg.color }}>
          {sorted.length} articles
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {sorted.length === 0 && (
          <div className="p-6 text-center" style={{ color: 'var(--muted)' }}>
            <div className="text-2xl mb-2">{cfg.emoji}</div>
            <div className="font-mono text-xs">No articles yet</div>
          </div>
        )}

        {sorted.map((a, i) => {
          const isSelected = selected?.article_id === a.article_id
          return (
            <button
              key={a.article_id + i}
              onClick={() => onSelect(a)}
              className={clsx(
                'w-full text-left px-4 py-3 border-b transition-colors duration-150 cursor-pointer',
                'hover:bg-white/[0.03]',
                isSelected && 'bg-white/[0.05]',
              )}
              style={{
                borderColor: 'var(--border)',
                borderLeft: isSelected ? `2px solid ${cfg.color}` : '2px solid transparent',
              }}
            >
              <div
                className="text-xs leading-snug mb-1.5"
                style={{ color: isSelected ? 'var(--ink)' : 'var(--ink2)' }}
              >
                {a.title}
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                {a.source && (
                  <span className="font-mono text-[10px]" style={{ color: 'var(--muted)' }}>
                    {a.source}
                  </span>
                )}
                {a.mention_text && (
                  <span
                    className="font-mono text-[10px] px-1.5 py-0.5 rounded"
                    style={{ background: `${cfg.color}18`, color: cfg.color }}
                  >
                    📍 {a.mention_text}
                  </span>
                )}
                <span className="font-mono text-[10px] ml-auto" style={{ color: 'var(--muted)' }}>
                  {timeAgo(a.fetched_at)}
                </span>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
