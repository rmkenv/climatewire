import useSWR from 'swr'
import { WireId, geojsonUrl } from './config'

export interface Article {
  article_id:      string
  title:           string
  snippet:         string
  url:             string
  source:          string
  published_at:    string
  wire:            WireId
  fetched_at:      string
  mention_text:    string | null
  osm_display:     string | null
  geocoded:        boolean
  event_type:      string | null
  lat:             number | null
  lon:             number | null
  run_at:          string
}

export interface GeoFeature {
  type: 'Feature'
  geometry: { type: 'Point'; coordinates: [number, number] } | null
  properties: Article
}

export interface GeoData {
  type: 'FeatureCollection'
  features: GeoFeature[]
  metadata?: {
    wire:          WireId
    last_updated:  string | null
    total_features: number
  }
}

const fetcher = (url: string) =>
  fetch(url, { next: { revalidate: 900 } }).then(r => {
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
    return r.json() as Promise<GeoData>
  })

export function useWireData(wire: WireId) {
  const { data, error, isLoading } = useSWR<GeoData>(
    geojsonUrl(wire),
    fetcher,
    { refreshInterval: 15 * 60 * 1000 }, // revalidate every 15 min
  )
  return {
    data,
    articles: data?.features.map(f => f.properties) ?? [],
    features: data?.features ?? [],
    lastUpdated: data?.metadata?.last_updated ?? null,
    total: data?.metadata?.total_features ?? 0,
    isLoading,
    error,
  }
}
