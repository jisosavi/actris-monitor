<script setup lang="ts">
import { ref, computed } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { Button } from '@/components/ui/button'
import { api, useFetchProgress, useStartFetch, useDbStatus, useCheckNewYear } from '@/composables/useStationData'
import { VARIABLES, YEAR_MIN, YEAR_MAX } from '@/types'
import type { Variable } from '@/types'
import FetchProgressOverlay from './FetchProgressOverlay.vue'

const queryClient = useQueryClient()
const startFetch = useStartFetch()
const { data: job } = useFetchProgress()
const { data: dbStatus } = useDbStatus()
const newYearQuery = useCheckNewYear()

const isRunning = computed(() => job.value?.status === 'running')
const busyVar = ref<Variable | null>(null)
const checkingNewYear = ref(false)
const newYearResult = ref<{ new_years: number[]; current_max: number } | null>(null)
const fetchingNewYears = ref(false)

async function refreshVariable(v: Variable) {
  if (isRunning.value) return
  busyVar.value = v
  try {
    const years = Array.from({ length: YEAR_MAX - YEAR_MIN + 1 }, (_, i) => YEAR_MIN + i)
    await startFetch(years, [v])
  } finally {
    busyVar.value = null
  }
}

async function checkNewYear() {
  checkingNewYear.value = true
  newYearResult.value = null
  try {
    const res = await api.get<{ new_years: number[]; current_max: number }>('/check-new-year')
    newYearResult.value = res.data
  } finally {
    checkingNewYear.value = false
  }
}

async function fetchNewYears() {
  if (!newYearResult.value?.new_years.length) return
  fetchingNewYears.value = true
  try {
    const vars = Object.keys(VARIABLES) as Variable[]
    await startFetch(newYearResult.value.new_years, vars)
    newYearResult.value = null
  } finally {
    fetchingNewYears.value = false
  }
}

const coverageByVar = computed(() => {
  const cov = dbStatus.value?.coverage ?? []
  const map: Record<string, number[]> = {}
  for (const { variable, year } of cov) {
    ;(map[variable] ??= []).push(year)
  }
  return map
})
</script>

<template>
  <div class="admin-panel">
    <div class="section-label">Data management</div>

    <!-- Progress while running -->
    <FetchProgressOverlay v-if="isRunning" :full-screen="false" />

    <template v-else>
      <!-- Per-variable refresh -->
      <div class="var-actions">
        <div
          v-for="[key, meta] in Object.entries(VARIABLES)"
          :key="key"
          class="var-row"
        >
          <div class="var-info">
            <span class="var-key">{{ meta.label }}</span>
            <span class="var-years">
              {{ coverageByVar[key]?.length ?? 0 }} yrs in DB
            </span>
          </div>
          <Button
            size="sm"
            variant="outline"
            class="refresh-btn"
            :disabled="isRunning || busyVar !== null"
            @click="refreshVariable(key as Variable)"
          >
            {{ busyVar === key ? 'Starting…' : 'Refresh' }}
          </Button>
        </div>
      </div>

      <!-- New year check -->
      <div class="new-year-row">
        <Button
          size="sm"
          variant="outline"
          class="check-btn"
          :disabled="checkingNewYear"
          @click="checkNewYear"
        >
          {{ checkingNewYear ? 'Checking…' : 'Check for new year' }}
        </Button>
      </div>

      <div v-if="newYearResult" class="new-year-result">
        <template v-if="newYearResult.new_years.length">
          <span class="new-year-found">
            New: {{ newYearResult.new_years.join(', ') }}
          </span>
          <Button
            size="sm"
            class="fetch-new-btn"
            :disabled="fetchingNewYears"
            @click="fetchNewYears"
          >
            {{ fetchingNewYears ? 'Starting…' : 'Fetch' }}
          </Button>
        </template>
        <span v-else class="new-year-none">Up to date (max {{ newYearResult.current_max }})</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.admin-panel {
  padding: 0 16px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.section-label {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
  margin-bottom: 2px;
}
.var-actions { display: flex; flex-direction: column; gap: 5px; }
.var-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.var-info { display: flex; flex-direction: column; flex: 1; min-width: 0; }
.var-key { font-size: 11px; color: var(--text); line-height: 1.3; }
.var-years { font-size: 10px; color: var(--text-muted); }
.refresh-btn { font-size: 11px; flex-shrink: 0; }
.new-year-row { margin-top: 4px; }
.check-btn { width: 100%; font-size: 11px; }
.new-year-result {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.new-year-found { font-size: 11px; color: var(--accent); font-weight: 500; }
.new-year-none { font-size: 11px; color: var(--text-muted); }
.fetch-new-btn { font-size: 11px; }
</style>
