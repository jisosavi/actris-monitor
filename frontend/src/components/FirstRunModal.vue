<script setup lang="ts">
import { ref, computed } from 'vue'
import { storeToRefs } from 'pinia'
import { Button } from '@/components/ui/button'
import {
  api,
  useStartFetch,
  useFetchProgress,
  useDbStatus,
  useResetDb,
  useBackfillNetworks,
} from '@/composables/useStationData'
import { useStationsStore } from '@/stores/stations'
import { VARIABLES, YEAR_MIN, YEAR_MAX } from '@/types'
import type { Variable } from '@/types'
import FetchProgressOverlay from './FetchProgressOverlay.vue'

const store = useStationsStore()
const { showDataSetup } = storeToRefs(store)

const startFetch = useStartFetch()
const resetDb = useResetDb()
const backfillNetworks = useBackfillNetworks()
const { data: job } = useFetchProgress()
const { data: dbStatus } = useDbStatus()

const isFirstRun = computed(() => dbStatus.value?.is_empty === true)
const isRunning = computed(() => job.value?.status === 'running')

// ── Fetch new data ────────────────────────────────────────────────────────────

const fromYear = ref(2014)
const toYear = ref(YEAR_MAX)
const selectedVars = ref<Variable[]>(Object.keys(VARIABLES) as Variable[])

const allYears = Array.from({ length: YEAR_MAX - YEAR_MIN + 1 }, (_, i) => YEAR_MAX - i)
const fromYears = computed(() => allYears.filter((y) => y <= toYear.value))
const toYears = computed(() => allYears.filter((y) => y >= fromYear.value))
const totalCombos = computed(() => (toYear.value - fromYear.value + 1) * selectedVars.value.length)

const isStarting = ref(false)

async function onStart() {
  if (selectedVars.value.length === 0) return
  isStarting.value = true
  try {
    const years = Array.from({ length: toYear.value - fromYear.value + 1 }, (_, i) => fromYear.value + i)
    await startFetch(years, selectedVars.value)
    showDataSetup.value = false
  } finally {
    isStarting.value = false
  }
}

function toggleVar(v: Variable) {
  const idx = selectedVars.value.indexOf(v)
  if (idx >= 0) selectedVars.value.splice(idx, 1)
  else selectedVars.value.push(v)
}

// ── Per-variable refresh ──────────────────────────────────────────────────────

const busyVar = ref<Variable | null>(null)

const coverageByVar = computed(() => {
  const map: Record<string, number[]> = {}
  for (const { variable, year } of dbStatus.value?.coverage ?? [])
    (map[variable] ??= []).push(year)
  return map
})

async function refreshVariable(v: Variable) {
  if (isRunning.value || busyVar.value) return
  busyVar.value = v
  try {
    const years = Array.from({ length: YEAR_MAX - YEAR_MIN + 1 }, (_, i) => YEAR_MIN + i)
    await startFetch(years, [v])
  } finally {
    busyVar.value = null
  }
}

// ── Check for new year ────────────────────────────────────────────────────────

const checkingNewYear = ref(false)
const newYearResult = ref<{ new_years: number[]; current_max: number } | null>(null)
const fetchingNewYears = ref(false)

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
    await startFetch(newYearResult.value.new_years, Object.keys(VARIABLES) as Variable[])
    newYearResult.value = null
  } finally {
    fetchingNewYears.value = false
  }
}

// ── Backfill network metadata ─────────────────────────────────────────────────

const backfilling = ref(false)
const backfillResult = ref<{ updated: number; skipped: number } | null>(null)

async function doBackfill() {
  backfilling.value = true
  backfillResult.value = null
  try {
    backfillResult.value = await backfillNetworks()
  } finally {
    backfilling.value = false
  }
}

// ── Reset database ────────────────────────────────────────────────────────────

const confirmReset = ref(false)
const resetting = ref(false)

async function doReset() {
  resetting.value = true
  try {
    await resetDb()
    confirmReset.value = false
  } finally {
    resetting.value = false
  }
}
</script>

<template>
  <div class="modal-overlay">
    <FetchProgressOverlay v-if="isRunning" :full-screen="true" />

    <div v-else class="modal-box">
      <button v-if="!isFirstRun" class="close-btn" @click="showDataSetup = false">✕</button>

      <div class="modal-icon">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="12" r="10" stroke="#303193" stroke-width="1.8" />
          <circle cx="12" cy="12" r="5" stroke="#303193" stroke-width="1.8" stroke-dasharray="3 2" />
          <circle cx="12" cy="12" r="1.8" fill="#303193" />
        </svg>
      </div>
      <div class="modal-title">Data Setup</div>

      <!-- ── Fetch new data ── -->
      <div class="section-label">Fetch data</div>

      <div class="form-section">
        <div class="form-label">Year range</div>
        <div class="year-row">
          <select v-model="fromYear" class="year-select">
            <option v-for="y in fromYears" :key="y" :value="y">{{ y }}</option>
          </select>
          <span class="year-dash">–</span>
          <select v-model="toYear" class="year-select">
            <option v-for="y in toYears" :key="y" :value="y">{{ y }}</option>
          </select>
        </div>
      </div>

      <div class="form-section">
        <div class="form-label">Variables</div>
        <div class="var-toggles">
          <button
            v-for="[key, meta] in Object.entries(VARIABLES)"
            :key="key"
            :class="['var-tog', selectedVars.includes(key as Variable) && 'var-tog--on']"
            @click="toggleVar(key as Variable)"
          >
            {{ meta.label }}
          </button>
        </div>
      </div>

      <div class="combo-count">{{ totalCombos }} year × variable combinations</div>

      <Button class="action-btn" :disabled="selectedVars.length === 0 || isStarting" @click="onStart">
        {{ isStarting ? 'Starting…' : 'Start Fetch' }}
      </Button>

      <div class="modal-note">
        Already-fetched combinations are skipped. The app remains usable for any data already in the database.
      </div>

      <!-- ── Management sections (only when DB has data) ── -->
      <template v-if="!isFirstRun">
        <div class="modal-divider" />

        <!-- Per-variable refresh -->
        <div class="section-label">Refresh variable</div>
        <div class="var-rows">
          <div v-for="[key, meta] in Object.entries(VARIABLES)" :key="key" class="var-row">
            <div class="var-row-info">
              <span class="var-row-name">{{ meta.label }}</span>
              <span class="var-row-years">{{ coverageByVar[key]?.length ?? 0 }} yrs in DB</span>
            </div>
            <Button
              size="sm"
              variant="outline"
              class="var-row-btn"
              :disabled="isRunning || busyVar !== null"
              @click="refreshVariable(key as Variable)"
            >
              {{ busyVar === key ? 'Starting…' : 'Refresh' }}
            </Button>
          </div>
        </div>

        <!-- Check for new year -->
        <div class="new-year-wrap">
          <Button
            size="sm"
            variant="outline"
            class="action-btn"
            :disabled="checkingNewYear"
            @click="checkNewYear"
          >
            {{ checkingNewYear ? 'Checking…' : 'Check for new year' }}
          </Button>
          <div v-if="newYearResult" class="new-year-result">
            <template v-if="newYearResult.new_years.length">
              <span class="new-year-found">New: {{ newYearResult.new_years.join(', ') }}</span>
              <Button size="sm" :disabled="fetchingNewYears" @click="fetchNewYears">
                {{ fetchingNewYears ? 'Starting…' : 'Fetch' }}
              </Button>
            </template>
            <span v-else class="new-year-none">Up to date (max {{ newYearResult.current_max }})</span>
          </div>
        </div>

        <div class="modal-divider" />

        <!-- Backfill -->
        <div class="section-label">Network metadata</div>
        <Button
          size="sm"
          variant="outline"
          class="action-btn"
          :disabled="backfilling || isRunning"
          @click="doBackfill"
        >
          {{ backfilling ? 'Fetching metadata…' : 'Backfill network metadata' }}
        </Button>
        <div class="section-note">
          Fetches one small metadata file per station to populate missing network
          affiliation (ACTRIS / EMEP / GAW-WDCA). No measurement data is downloaded.
          Run this if network filter shows stations as unknown after a data fetch.
        </div>
        <div v-if="backfillResult" class="action-result">
          Updated {{ backfillResult.updated }} / {{ backfillResult.updated + backfillResult.skipped }} stations
          <span v-if="backfillResult.skipped > 0"> · {{ backfillResult.skipped }} not found in catalog</span>
        </div>

        <div class="modal-divider" />

        <!-- Reset -->
        <div class="section-label">Danger zone</div>
        <div v-if="!confirmReset">
          <button class="danger-link" @click="confirmReset = true">Reset database…</button>
        </div>
        <div v-else class="reset-confirm">
          <span class="reset-warn">Delete all data?</span>
          <Button size="sm" variant="destructive" :disabled="resetting" @click="doReset">
            {{ resetting ? 'Resetting…' : 'Yes, reset' }}
          </Button>
          <button class="cancel-link" @click="confirmReset = false">Cancel</button>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(238, 241, 247, 0.88);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 500;
  backdrop-filter: blur(4px);
}

.modal-box {
  position: relative;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 32px 36px;
  max-width: 480px;
  width: calc(100% - 40px);
  max-height: 90vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
  box-shadow: 0 12px 48px rgba(48, 49, 147, 0.15);
}

.close-btn {
  position: sticky;
  top: 0;
  align-self: flex-end;
  background: none;
  border: none;
  font-size: 14px;
  color: var(--text-muted);
  cursor: pointer;
  line-height: 1;
  padding: 2px 4px;
  border-radius: 4px;
  margin-bottom: -28px;
  z-index: 1;
}
.close-btn:hover { color: var(--text); background: var(--border); }

.modal-icon { display: flex; justify-content: center; }

.modal-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--accent);
  text-align: center;
}

.section-label {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
}

.modal-divider {
  border: none;
  border-top: 1px solid var(--border);
  margin: 2px 0;
}

.form-section { display: flex; flex-direction: column; gap: 8px; }

.form-label {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
}

.year-row { display: flex; align-items: center; gap: 10px; }
.year-select {
  flex: 1;
  padding: 7px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--text);
  font-size: 13px;
  font-family: inherit;
}
.year-dash { color: var(--text-muted); }

.var-toggles { display: flex; flex-direction: column; gap: 6px; }
.var-tog {
  padding: 9px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--text-muted);
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  text-align: left;
  transition: all 0.15s;
}
.var-tog:hover { border-color: var(--accent); color: var(--text); }
.var-tog--on {
  border-color: var(--accent);
  background: var(--accent-light);
  color: var(--text);
  font-weight: 500;
}

.combo-count { font-size: 11px; color: var(--text-muted); text-align: center; }

.action-btn { width: 100%; font-size: 12px; }

.modal-note {
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.5;
  text-align: center;
}

.var-rows { display: flex; flex-direction: column; gap: 5px; }
.var-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.var-row-info { display: flex; flex-direction: column; flex: 1; min-width: 0; }
.var-row-name { font-size: 11px; color: var(--text); line-height: 1.3; }
.var-row-years { font-size: 10px; color: var(--text-muted); }
.var-row-btn { font-size: 11px; flex-shrink: 0; }

.new-year-wrap { display: flex; flex-direction: column; gap: 8px; }
.new-year-result { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.new-year-found { font-size: 11px; color: var(--accent); font-weight: 500; }
.new-year-none { font-size: 11px; color: var(--text-muted); }

.section-note {
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.5;
}
.action-result { font-size: 11px; color: var(--accent); }
.result-muted { color: var(--text-muted); }

.danger-link {
  background: none;
  border: none;
  font-size: 11px;
  color: var(--text-muted);
  cursor: pointer;
  padding: 0;
  text-decoration: underline;
  text-underline-offset: 2px;
  font-family: inherit;
}
.danger-link:hover { color: var(--negative); }

.reset-confirm { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.reset-warn { font-size: 11px; color: var(--negative); font-weight: 500; }
.cancel-link {
  background: none;
  border: none;
  font-size: 11px;
  color: var(--text-muted);
  cursor: pointer;
  padding: 0;
  text-decoration: underline;
  text-underline-offset: 2px;
  font-family: inherit;
}
.cancel-link:hover { color: var(--text); }
</style>
