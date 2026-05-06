import { WIRES, WireId } from '@/lib/config'
import clsx from 'clsx'

interface Props {
  active:   WireId
  onChange: (w: WireId) => void
  counts:   Partial<Record<WireId, number>>
}

export default function WireToggle({ active, onChange, counts }: Props) {
  return (
    <div className="flex gap-1">
      {WIRES.map(w => {
        const isActive = w.id === active
        return (
          <button
            key={w.id}
            onClick={() => onChange(w.id)}
            style={{
              borderColor:     isActive ? w.color : 'transparent',
              color:           isActive ? w.color : 'var(--muted)',
              backgroundColor: isActive ? `${w.color}12` : 'transparent',
            }}
            className={clsx(
              'flex items-center gap-2 px-3 py-1.5 rounded text-xs font-mono',
              'border transition-all duration-200 cursor-pointer',
              'hover:opacity-90',
            )}
          >
            <span>{w.emoji}</span>
            <span className="uppercase tracking-widest">{w.label}</span>
            {counts[w.id] != null && (
              <span
                className="rounded px-1 text-[10px]"
                style={{
                  background: isActive ? `${w.color}28` : 'var(--surface2)',
                  color:      isActive ? w.color : 'var(--muted)',
                }}
              >
                {counts[w.id]}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}
