import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { Station, NetworkStats, Variable, RankingMode } from '@/types'
import { YEAR_MAX } from '@/types'

export const useStationsStore = defineStore('stations', () => {
  const selectedYear = ref<number>(YEAR_MAX)
  const selectedVariable = ref<Variable>('N')
  const rankingMode = ref<RankingMode>('concentration')
  const hoveredStation = ref<Station | null>(null)
  const showDataSetup = ref(false)

  return { selectedYear, selectedVariable, rankingMode, hoveredStation, showDataSetup }
})
