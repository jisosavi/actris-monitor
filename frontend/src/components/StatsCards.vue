<script setup lang="ts">
import { computed } from 'vue'
import { useStationData } from '@/composables/useStationData'
import { useStationsStore } from '@/stores/stations'
import { storeToRefs } from 'pinia'
import { VARIABLES } from '@/types'

const { statsQuery } = useStationData()
const store = useStationsStore()
const { selectedVariable } = storeToRefs(store)

const unit = computed(() => VARIABLES[selectedVariable.value].unit)
const s = computed(() => statsQuery.data.value)

function fmt(v: number | null | undefined, decimals = 1): string {
  if (v == null) return '—'
  return v >= 1000 ? (v / 1000).toFixed(1) + 'k' : v.toFixed(decimals)
}
</script>

<template>
  <div class="stats-section">
    <div class="section-label">Network statistics</div>

    <div v-if="statsQuery.isFetching.value && !s" class="loading-text">Loading…</div>

    <div v-else class="cards-grid">
      <div class="stat-card stat-card--median">
        <div class="stat-label">Median</div>
        <div class="stat-value">{{ fmt(s?.median) }}</div>
        <div class="stat-unit">{{ unit }}</div>
      </div>

      <div class="stat-card stat-card--iqr">
        <div class="stat-label">IQR</div>
        <div class="stat-value stat-value--sm">
          {{ fmt(s?.q1) }}–{{ fmt(s?.q3) }}
        </div>
        <div class="stat-unit">{{ unit }}</div>
      </div>

      <div class="stat-card stat-card--max">
        <div class="stat-label">Max</div>
        <div class="stat-value">{{ fmt(s?.max) }}</div>
        <div class="stat-unit">{{ unit }}</div>
      </div>

      <div class="stat-card stat-card--min">
        <div class="stat-label">Min</div>
        <div class="stat-value">{{ fmt(s?.min) }}</div>
        <div class="stat-unit">{{ unit }}</div>
      </div>
    </div>

    <div v-if="s" class="stations-count">
      <span class="count-dot" />
      {{ s.n_stations }} stations reporting
    </div>
  </div>
</template>

<style scoped>
.stats-section { padding: 0 16px 16px; }

.section-label {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-muted);
  margin-bottom: 8px;
}

.loading-text { font-size: 12px; color: var(--text-muted); }

.cards-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
}

.stat-card {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  position: relative;
  overflow: hidden;
}
.stat-card::before {
  content: '';
  position: absolute;
  top: 0; left: 0;
  width: 3px;
  height: 100%;
  border-radius: 8px 0 0 8px;
}
.stat-card--median::before { background: var(--accent); }
.stat-card--iqr::before    { background: #7c3aed; }
.stat-card--max::before    { background: var(--negative); }
.stat-card--min::before    { background: var(--positive); }

.stat-label {
  font-size: 9px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-muted);
  margin-bottom: 4px;
}
.stat-value {
  font-size: 18px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: var(--text);
  line-height: 1;
}
.stat-value--sm { font-size: 13px; }
.stat-unit { font-size: 9px; color: var(--text-muted); margin-top: 2px; font-family: monospace; }

.stations-count {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  font-size: 11px;
  color: var(--text-muted);
}
.count-dot {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--positive);
  flex-shrink: 0;
}
</style>
