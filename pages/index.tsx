import { useState, useCallback } from 'react'
import dynamic from 'next/dynamic'
import Head from 'next/head'
import { WireId, WIRES } from '@/lib/config'
import { useWireData, Article } from '@/lib/useWireData'
import WireToggle from '@/components/WireToggle'
import StatsBar from '@/components/StatsBar'
import ArticleFeed from '@/components/ArticleFeed'
import ArticleDetail from '@/components/ArticleDetail'

// Leaflet must be loaded client-side only
const ClimateMap = dynamic(() => import('@/components/ClimateMap'), {
  ssr: false,
  loading: () => (
    <div className="w-full h-full flex items-center justify-center" style={{ color: 'var(--muted)' }}>
      <span className="font-mono text-xs animate-pulse">Loading map…</span>
    </div>
  ),
})

// Preload all wires so counts are available in toggle
function useAllWires() {
  const drought = useWireData('drought')
  const fire    = useWireData('fire')
  const heat    = useWireData('heat')
  const water   = useWireData('water')
  return { drought, fire, heat, water }
}

export default function Dashboard() {
  const [activeWire, setActiveWire] = useState<WireId>('drought')
  const [selected,  setSelected]  = useState<Article | null>(null)

  const allWires = useAllWires()
  const active   = allWires[activeWire]

  const handleWireChange = useCallback((w: WireId) => {
    setActiveWire(w)
    setSelected(null)
  }, [])

  const handleSelect = useCallback((a: Article) => {
    setSelected(prev => prev?.article_id === a.article_id ? null : a)
  }, [])

  const counts = Object.fromEntries(
    WIRES.map(w => [w.id, allWires[w.id].total])
  ) as Partial<Record<WireId, number>>

  return (
    <>
      <Head>
        <title>ClimateWire — Live Climate Hazard Intelligence</title>
        <meta name="description" content="Real-time climate hazard news: drought, wildfire, extreme heat, water scarcity across the US." />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <link rel="icon" href="/favicon.ico" />
      </Head>

      <div className="flex flex-col h-screen overflow-hidden" style={{ background: 'var(--bg)' }}>

        {/* ── Top Bar ── */}
        <header
          className="flex items-center justify-between px-5 py-3 shrink-0 border-b"
          style={{ borderColor: 'var(--border)' }}
        >
          <div className="flex items-center gap-4">
            <div>
              <div
                className="text-sm tracking-tight leading-none"
                style={{ fontFamily: 'var(--font-display)', fontWeight: 300 }}
              >
                Climate<span style={{ color: allWires[activeWire] ? undefined : 'var(--accent)' }}>Wire</span>
              </div>
              <div className="font-mono text-[9px] uppercase tracking-widest mt-0.5" style={{ color: 'var(--muted)' }}>
                Live hazard intelligence
              </div>
            </div>

            <div className="hidden md:block h-6 w-px" style={{ background: 'var(--border)' }} />

            <WireToggle
              active={activeWire}
              onChange={handleWireChange}
              counts={counts}
            />
          </div>

          {/* Live indicator */}
          <div className="flex items-center gap-2">
            <div
              className="w-1.5 h-1.5 rounded-full"
              style={{
                background: 'var(--accent)',
                animation: 'pulse-dot 2s ease-in-out infinite',
              }}
            />
            <span className="font-mono text-[10px]" style={{ color: 'var(--muted)' }}>
              AUTO-REFRESH 15m
            </span>
          </div>
        </header>

        {/* ── Stats Bar ── */}
        <div
          className="px-5 py-2.5 border-b shrink-0"
          style={{ borderColor: 'var(--border)', background: 'var(--surface)' }}
        >
          {active.isLoading ? (
            <div className="font-mono text-[10px] animate-pulse" style={{ color: 'var(--muted)' }}>
              Loading wire data…
            </div>
          ) : (
            <StatsBar
              articles={active.articles}
              wire={activeWire}
              lastUpdated={active.lastUpdated}
            />
          )}
        </div>

        {/* ── Main content ── */}
        <div className="flex flex-1 overflow-hidden">

          {/* Article feed — left column */}
          <div
            className="w-72 shrink-0 border-r flex flex-col overflow-hidden"
            style={{ borderColor: 'var(--border)' }}
          >
            {active.error ? (
              <div className="p-6 text-center">
                <div className="font-mono text-xs" style={{ color: 'var(--muted)' }}>
                  Failed to load data.<br />Check your GitHub URLs.
                </div>
              </div>
            ) : (
              <ArticleFeed
                articles={active.articles}
                wire={activeWire}
                selected={selected}
                onSelect={handleSelect}
              />
            )}
          </div>

          {/* Map — centre */}
          <div className="flex-1 relative overflow-hidden">
            <ClimateMap
              features={active.features}
              wire={activeWire}
              onSelect={handleSelect}
              selected={selected}
            />

            {/* Wire label overlay */}
            <div
              className="absolute bottom-4 left-4 font-mono text-[10px] uppercase tracking-widest px-2 py-1 rounded"
              style={{
                background:  'rgba(12,12,14,0.85)',
                color:       'var(--muted)',
                backdropFilter: 'blur(4px)',
              }}
            >
              {WIRES.find(w => w.id === activeWire)?.tagline}
            </div>
          </div>

          {/* Article detail — right panel */}
          {selected && (
            <div
              className="w-72 shrink-0 overflow-hidden"
              style={{ borderLeft: '1px solid var(--border)' }}
            >
              <ArticleDetail
                article={selected}
                wire={activeWire}
                onClose={() => setSelected(null)}
              />
            </div>
          )}
        </div>
      </div>
    </>
  )
}
