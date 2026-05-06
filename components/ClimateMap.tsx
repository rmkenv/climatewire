'use client'
import { useEffect, useRef } from 'react'
import { GeoFeature, Article } from '@/lib/useWireData'
import { WireId, WIRE_MAP } from '@/lib/config'

interface Props {
  features:  GeoFeature[]
  wire:      WireId
  onSelect:  (a: Article) => void
  selected:  Article | null
}

export default function ClimateMap({ features, wire, onSelect, selected }: Props) {
  const mapRef    = useRef<any>(null)
  const layerRef  = useRef<any>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const wireConfig = WIRE_MAP[wire]

  useEffect(() => {
    if (typeof window === 'undefined') return
    if (mapRef.current) return // already initialised

    import('leaflet').then(L => {
      if (!containerRef.current) return

      const map = L.map(containerRef.current, {
        center: [39.5, -98.35],
        zoom: 4,
        zoomControl: true,
        attributionControl: false,
      })

      L.tileLayer(
        'https://{s}.basemaps.cartocdn.com/dark_matter_no_labels/{z}/{x}/{y}{r}.png',
        { subdomains: 'abcd', maxZoom: 19 },
      ).addTo(map)

      // Subtle attribution
      L.control.attribution({ prefix: false })
        .addAttribution('© OpenStreetMap © CARTO')
        .addTo(map)

      mapRef.current = map
    })

    return () => {
      if (mapRef.current) {
        mapRef.current.remove()
        mapRef.current = null
      }
    }
  }, [])

  // Re-render markers when features or wire changes
  useEffect(() => {
    if (!mapRef.current || typeof window === 'undefined') return

    import('leaflet').then(L => {
      // Clear old layer
      if (layerRef.current) {
        layerRef.current.clearLayers()
      } else {
        layerRef.current = L.layerGroup().addTo(mapRef.current)
      }

      const color = wireConfig.color
      const validFeatures = features.filter(
        f => f.geometry?.coordinates && f.properties.geocoded
      )

      validFeatures.forEach(f => {
        const [lon, lat] = f.geometry!.coordinates
        const props = f.properties

        const isSelected = selected?.article_id === props.article_id

        const icon = L.divIcon({
          className: '',
          html: `
            <div style="
              width: ${isSelected ? 14 : 9}px;
              height: ${isSelected ? 14 : 9}px;
              background: ${color};
              border-radius: 50%;
              border: ${isSelected ? `2px solid white` : `1.5px solid ${color}44`};
              box-shadow: 0 0 ${isSelected ? 12 : 6}px ${color}88;
              transition: all 0.2s;
            "></div>
          `,
          iconSize:   [isSelected ? 14 : 9, isSelected ? 14 : 9],
          iconAnchor: [isSelected ? 7  : 4,  isSelected ? 7  : 4],
        })

        const marker = L.marker([lat, lon], { icon })

        marker.on('click', () => onSelect(props))

        const sourceLabel = props.source ? `<div style="color:var(--muted);font-size:11px;margin-top:2px">${props.source}</div>` : ''
        marker.bindPopup(`
          <div style="font-family:'IBM Plex Sans',sans-serif;max-width:260px">
            <div style="font-size:12px;font-weight:500;color:#e8e8ea;line-height:1.4">${props.title}</div>
            ${sourceLabel}
            <a href="${props.url}" target="_blank" rel="noopener"
               style="display:inline-block;margin-top:6px;font-size:11px;color:${color};font-family:'IBM Plex Mono',monospace;text-decoration:none">
              Read →
            </a>
          </div>
        `, { maxWidth: 280 })

        layerRef.current.addLayer(marker)
      })
    })
  }, [features, wire, selected, wireConfig.color, onSelect])

  return (
    <div
      ref={containerRef}
      className="w-full h-full"
      style={{ minHeight: 400 }}
    />
  )
}
