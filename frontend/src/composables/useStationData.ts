import { computed, ref } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { storeToRefs } from 'pinia'
import axios from 'axios'
import { useStationsStore } from '@/stores/stations'
import type { Station, NetworkStats } from '@/types'


export interface WarmupStatus {
  done: number
  total: number
  complete: boolean
}

export interface DbCoverageEntry {
  year: number
  variable: string
  fetched_at: string
}

export interface DbStatus {
  coverage: DbCoverageEntry[]
  is_empty: boolean
}

export interface FetchJob {
  id: number | null
  status: 'idle' | 'running' | 'complete' | 'failed' | 'complete_with_errors'
  total: number
  done: number
  current_desc: string | null
  started_at: string | null
  finished_at: string | null
  error_msg: string | null
}

export interface NewYearStatus {
  new_years: number[]
  current_max: number
}

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL
    ?? (import.meta.env.DEV ? 'http://localhost:8000/api' : '/api'),
})

// ── Admin token ───────────────────────────────────────────────────────────────
//
// The mutating endpoints (start-fetch, db/reset, backfill-networks) require an
// X-Admin-Token header. The token is deliberately NOT part of the build: it is
// typed into the Data Setup panel by the operator and kept in their own browser.
// Nothing secret ships to visitors.

const ADMIN_TOKEN_KEY = 'actris.adminToken'

function readStoredToken(): string {
  try {
    return localStorage.getItem(ADMIN_TOKEN_KEY) ?? ''
  } catch {
    return '' // private mode or storage disabled
  }
}

export const adminToken = ref<string>(readStoredToken())
export const hasAdminToken = computed(() => adminToken.value.length > 0)

export function setAdminToken(token: string) {
  adminToken.value = token
  try {
    if (token) localStorage.setItem(ADMIN_TOKEN_KEY, token)
    else localStorage.removeItem(ADMIN_TOKEN_KEY)
  } catch {
    // Non-persistent session: the in-memory ref still works for this tab.
  }
}

export function clearAdminToken() {
  setAdminToken('')
}

// Only the protected endpoints get the header. Attaching it to every request
// would make ordinary GETs non-simple and cost a CORS preflight round trip each.
const ADMIN_PATHS = ['/start-fetch', '/db/reset', '/backfill-networks', '/admin/check']

api.interceptors.request.use((config) => {
  const url = config.url ?? ''
  if (adminToken.value && ADMIN_PATHS.some((path) => url.startsWith(path))) {
    config.headers['X-Admin-Token'] = adminToken.value
  }
  return config
})

/** Validate a token against the backend without causing side effects. */
export async function checkAdminToken(token: string): Promise<boolean> {
  try {
    await api.get('/admin/check', { headers: { 'X-Admin-Token': token } })
    return true
  } catch {
    return false
  }
}

export function useStationData() {
  const store = useStationsStore()
  const { selectedYear, selectedVariable } = storeToRefs(store)

  const stationsQuery = useQuery({
    queryKey: computed(() => ['stations', selectedYear.value, selectedVariable.value]),
    queryFn: () =>
      api
        .get<Station[]>(`/stations/${selectedYear.value}/${selectedVariable.value}`)
        .then((r) => r.data),
    staleTime: 1000 * 60 * 60,
    placeholderData: (prev) => prev,
    retry: false,
  })

  const statsQuery = useQuery({
    queryKey: computed(() => ['stats', selectedYear.value, selectedVariable.value]),
    queryFn: () =>
      api
        .get<NetworkStats>(`/network-stats/${selectedYear.value}/${selectedVariable.value}`)
        .then((r) => r.data),
    staleTime: 1000 * 60 * 60,
    placeholderData: (prev) => prev,
    retry: false,
  })

  return { stationsQuery, statsQuery }
}

export function useWarmupStatus() {
  return useQuery<WarmupStatus>({
    queryKey: ['warmup-status'],
    queryFn: () => api.get<WarmupStatus>('/warmup-status').then((r) => r.data),
    refetchInterval: (query) => (query.state.data?.complete ? false : 4000),
    staleTime: 0,
  })
}

export function useDbStatus() {
  return useQuery<DbStatus>({
    queryKey: ['db-status'],
    queryFn: () => api.get<DbStatus>('/db-status').then((r) => r.data),
    staleTime: 1000 * 30,
    refetchInterval: 1000 * 30,
  })
}

export function useFetchProgress() {
  return useQuery<FetchJob>({
    queryKey: ['fetch-progress'],
    queryFn: () => api.get<FetchJob>('/fetch-progress').then((r) => r.data),
    refetchInterval: (query) => {
      const s = query.state.data?.status
      return s === 'running' ? 2000 : false
    },
    staleTime: 0,
  })
}

export function useStartFetch() {
  const queryClient = useQueryClient()
  return async (years: number[], variables: string[]) => {
    await api.post('/start-fetch', { years, variables })
    await queryClient.invalidateQueries({ queryKey: ['fetch-progress'] })
    await queryClient.invalidateQueries({ queryKey: ['db-status'] })
  }
}

export function useResetDb() {
  const queryClient = useQueryClient()
  return async () => {
    await api.post('/db/reset')
    await queryClient.invalidateQueries({ queryKey: ['db-status'] })
    await queryClient.invalidateQueries({ queryKey: ['fetch-progress'] })
  }
}

export function useBackfillNetworks() {
  const queryClient = useQueryClient()
  return async (): Promise<{ updated: number; skipped: number }> => {
    const res = await api.post<{ updated: number; skipped: number }>('/backfill-networks')
    await queryClient.invalidateQueries({ queryKey: ['stations'] })
    return res.data
  }
}

export function useCheckNewYear() {
  return useQuery<NewYearStatus>({
    queryKey: ['check-new-year'],
    queryFn: () => api.get<NewYearStatus>('/check-new-year').then((r) => r.data),
    staleTime: 1000 * 60 * 10,
    enabled: false, // only fetch when explicitly triggered
  })
}

export function useFilteredStations() {
  const store = useStationsStore()
  const { networkFilter } = storeToRefs(store)
  const { stationsQuery } = useStationData()

  return computed(() => {
    const all = stationsQuery.data.value ?? []
    if (networkFilter.value.length === 0) return all
    return all.filter((s) => {
      if (!s.networks) return true  // unknown affiliation: always include, styled differently
      const nets = new Set(s.networks.split(','))
      return networkFilter.value.some((n) => nets.has(n))
    })
  })
}

export { api }
