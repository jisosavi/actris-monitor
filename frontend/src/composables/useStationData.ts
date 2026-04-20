import { computed } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { storeToRefs } from 'pinia'
import axios from 'axios'
import { useStationsStore } from '@/stores/stations'
import type { Station, NetworkStats } from '@/types'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL
    ?? (import.meta.env.DEV ? 'http://localhost:8000/api' : '/api'),
})

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
  })

  const statsQuery = useQuery({
    queryKey: computed(() => ['stats', selectedYear.value, selectedVariable.value]),
    queryFn: () =>
      api
        .get<NetworkStats>(`/network-stats/${selectedYear.value}/${selectedVariable.value}`)
        .then((r) => r.data),
    staleTime: 1000 * 60 * 60,
    placeholderData: (prev) => prev,
  })

  return { stationsQuery, statsQuery }
}
