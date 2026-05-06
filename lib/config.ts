export type WireId = 'drought' | 'fire' | 'heat' | 'water'

export interface WireConfig {
  id:      WireId
  label:   string
  emoji:   string
  color:   string
  tagline: string
}

export const WIRES: WireConfig[] = [
  { id: 'drought', label: 'Drought',    emoji: '🌵', color: '#e8892a', tagline: 'Water shortage & drought monitor' },
  { id: 'fire',    label: 'Wildfire',   emoji: '🔥', color: '#e84a2a', tagline: 'Active fire & evacuation alerts' },
  { id: 'heat',    label: 'Extreme Heat', emoji: '☀️', color: '#d4a017', tagline: 'Heat emergency & public health' },
  { id: 'water',   label: 'Water',      emoji: '💧', color: '#2a7de8', tagline: 'Water restriction & scarcity' },
]

export const WIRE_MAP = Object.fromEntries(WIRES.map(w => [w.id, w])) as Record<WireId, WireConfig>

const BASE = process.env.GITHUB_RAW_BASE ??
  'https://raw.githubusercontent.com/rmkenv/climatewire/main/data'

export const geojsonUrl = (wire: WireId) => `${BASE}/${wire}.geojson`
export const csvUrl     = (wire: WireId) => `${BASE}/${wire}.csv`
