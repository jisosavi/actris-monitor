import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { Station, Variable, RankingMode } from '@/types'
import { YEAR_MAX } from '@/types'

export const useStationsStore = defineStore('stations', () => {
  const selectedYear = ref<number>(YEAR_MAX)
  const selectedVariable = ref<Variable>('N')
  const rankingMode = ref<RankingMode>('concentration')
  const hoveredStation = ref<Station | null>(null)
  const showDataSetup = ref(false)
  const networkFilter = ref<string[]>([])

  // Clicking a station pins it and opens the detail panel. Held as an id rather
  // than a Station object because the panel also opens for NRT-only sites, which
  // have no annual record of ours at all.
  const selectedStationId = ref<string | null>(null)

  return {
    selectedYear,
    selectedVariable,
    rankingMode,
    hoveredStation,
    showDataSetup,
    networkFilter,
    selectedStationId,
  }
})
