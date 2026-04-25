<script setup lang="ts">
import { ref, computed } from 'vue'
import { Button } from '@/components/ui/button'
import { useStartFetch, useFetchProgress } from '@/composables/useStationData'
import { VARIABLES, YEAR_MIN, YEAR_MAX } from '@/types'
import type { Variable } from '@/types'
import FetchProgressOverlay from './FetchProgressOverlay.vue'

const startFetch = useStartFetch()
const { data: job } = useFetchProgress()

const fromYear = ref(2014)
const toYear = ref(YEAR_MAX)
const selectedVars = ref<Variable[]>(Object.keys(VARIABLES) as Variable[])

const allYears = Array.from({ length: YEAR_MAX - YEAR_MIN + 1 }, (_, i) => YEAR_MAX - i)
const fromYears = computed(() => allYears.filter((y) => y <= toYear.value))
const toYears = computed(() => allYears.filter((y) => y >= fromYear.value))

const totalCombos = computed(() => {
  const n = toYear.value - fromYear.value + 1
  return n * selectedVars.value.length
})

const isRunning = computed(() => job.value?.status === 'running')
const isStarting = ref(false)

async function onStart() {
  if (selectedVars.value.length === 0) return
  isStarting.value = true
  try {
    const years = Array.from({ length: toYear.value - fromYear.value + 1 }, (_, i) => fromYear.value + i)
    await startFetch(years, selectedVars.value)
  } finally {
    isStarting.value = false
  }
}

function toggleVar(v: Variable) {
  const idx = selectedVars.value.indexOf(v)
  if (idx >= 0) selectedVars.value.splice(idx, 1)
  else selectedVars.value.push(v)
}
</script>

<template>
  <div class="modal-overlay">
    <!-- Progress view while running -->
    <FetchProgressOverlay v-if="isRunning" :full-screen="true" />

    <!-- Config form -->
    <div v-else class="modal-box">
      <div class="modal-icon">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="12" r="10" stroke="#303193" stroke-width="1.8" />
          <circle cx="12" cy="12" r="5" stroke="#303193" stroke-width="1.8" stroke-dasharray="3 2" />
          <circle cx="12" cy="12" r="1.8" fill="#303193" />
        </svg>
      </div>

      <div class="modal-title">Welcome to ACTRIS Monitor</div>
      <div class="modal-sub">
        The local database is empty. Select the year range and variables to fetch.
        This will take 30–90 minutes but only needs to happen once.
      </div>

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

      <Button
        class="start-btn"
        :disabled="selectedVars.length === 0 || isStarting"
        @click="onStart"
      >
        {{ isStarting ? 'Starting…' : 'Start Fetch' }}
      </Button>

      <div class="modal-note">
        Data is fetched from EBAS THREDDS in the background.
        The app remains usable for any data already in the database.
      </div>
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
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 36px 40px;
  max-width: 460px;
  width: calc(100% - 40px);
  display: flex;
  flex-direction: column;
  gap: 18px;
  box-shadow: 0 12px 48px rgba(48, 49, 147, 0.15);
}
.modal-icon { display: flex; justify-content: center; }
.modal-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--accent);
  text-align: center;
}
.modal-sub {
  font-size: 13px;
  color: var(--text-muted);
  line-height: 1.6;
  text-align: center;
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
.combo-count {
  font-size: 11px;
  color: var(--text-muted);
  text-align: center;
}
.start-btn { width: 100%; }
.modal-note {
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.5;
  text-align: center;
}
</style>
