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

export const YEAR_MIN = 2021
export const YEAR_MAX = 2024
