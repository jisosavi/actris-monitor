export interface Station {
  id: string
  name: string
  lat: number
  lon: number
  country: string
  mean: number | null
  unit: string
  delta_pct: number | null
  prev_mean: number | null
  data_coverage: number
  networks: string
}

export interface NetworkStats {
  median: number | null
  q1: number | null
  q3: number | null
  min: number | null
  max: number | null
  n_stations: number
  year: number
  variable: string
}

export type Variable = 'N' | 'scattering' | 'absorption'
export type RankingMode = 'concentration' | 'delta'

export const VARIABLES: Record<Variable, { label: string; unit: string; shortLabel: string }> = {
  N: {
    label: 'Particle Number Concentration',
    shortLabel: 'N',
    unit: 'cm⁻³',
  },
  scattering: {
    label: 'Scattering Coefficient (525 nm)',
    shortLabel: 'σ_sp',
    unit: 'Mm⁻¹',
  },
  absorption: {
    label: 'Absorption Coefficient (520 nm)',
    shortLabel: 'σ_ap',
    unit: 'Mm⁻¹',
  },
}

export const YEAR_MIN = 2000
export const YEAR_MAX = new Date().getFullYear()
export const YEAR_PRELOADED_MIN = 2014

// ── EBAS near-real-time (NRT) ────────────────────────────────────────────────
//
// Served through our own backend because ebas-nrt.nilu.no sends no CORS headers.
// Availability only — the measurements stay on NILU's site, which is what the
// station `url` links to.

export interface NrtStation {
  name: string
  lat: number
  lon: number
  variables: Variable[]
  /** Whether this station exists in our own record, in any year. */
  known: boolean
  url: string
}

export interface NrtAvailability {
  /** null when nothing has ever been fetched successfully. */
  fetched_at: string | null
  /** true when this is a cached or empty snapshot because the upstream failed. */
  stale: boolean
  source: string
  stations: Record<string, NrtStation>
}
