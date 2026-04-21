<script setup lang="ts">
import { computed } from 'vue'
import { useStationData } from '@/composables/useStationData'
import { useStationsStore } from '@/stores/stations'
import { storeToRefs } from 'pinia'
import { VARIABLES } from '@/types'
import { Card, CardContent } from '@/components/ui/card'

const { statsQuery, stationsQuery } = useStationData()
const store = useStationsStore()
const { selectedVariable } = storeToRefs(store)

const unit = computed(() => VARIABLES[selectedVariable.value].unit)
const s = computed(() => statsQuery.data.value)

const totalStations = computed(() => stationsQuery.data.value?.length ?? 0)
const withData = computed(() => stationsQuery.data.value?.filter(s => s.mean !== null).length ?? 0)
const withoutData = computed(() => totalStations.value - withData.value)

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
      <Card class="stat-card stat-card--median">
        <CardContent class="stat-content">
          <div class="stat-label">Median</div>
          <div class="stat-value">{{ fmt(s?.median) }}</div>
          <div class="stat-unit">{{ unit }}</div>
        </CardContent>
      </Card>

      <Card class="stat-card stat-card--iqr">
        <CardContent class="stat-content">
          <div class="stat-label">IQR</div>
          <div class="stat-value stat-value--sm">{{ fmt(s?.q1) }}–{{ fmt(s?.q3) }}</div>
          <div class="stat-unit">{{ unit }}</div>
        </CardContent>
      </Card>

      <Card class="stat-card stat-card--max">
        <CardContent class="stat-content">
          <div class="stat-label">Max</div>
          <div class="stat-value">{{ fmt(s?.max) }}</div>
          <div class="stat-unit">{{ unit }}</div>
        </CardContent>
      </Card>

      <Card class="stat-card stat-card--min">
        <CardContent class="stat-content">
          <div class="stat-label">Min</div>
          <div class="stat-value">{{ fmt(s?.min) }}</div>
          <div class="stat-unit">{{ unit }}</div>
        </CardContent>
      </Card>
    </div>

    <div v-if="totalStations > 0" class="stations-count">
      <div class="count-row">
        <span class="count-dot count-dot--total" />
        <span>{{ totalStations }} stations total</span>
      </div>
      <div class="count-row">
        <span class="count-dot count-dot--data" />
        <span>{{ withData }} with data</span>
      </div>
      <div class="count-row">
        <span class="count-dot count-dot--nodata" />
        <span>{{ withoutData }} no data this year</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.stats-section { padding: 0 16px 16px; }

.section-label {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
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
  border: 1px solid var(--border);
  border-radius: var(--radius);
  position: relative;
  overflow: hidden;
  box-shadow: none;
}
.stat-card::before {
  content: '';
  position: absolute;
  top: 0; left: 0;
  width: 3px;
  height: 100%;
}
.stat-card--median::before { background: var(--accent); }
.stat-card--iqr::before    { background: #6366f1; }
.stat-card--max::before    { background: var(--negative); }
.stat-card--min::before    { background: var(--positive); }

.stat-content { padding: 10px 12px !important; }

.stat-label {
  font-size: 9px;
  letter-spacing: 0.08em;
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
  flex-direction: column;
  gap: 4px;
  margin-top: 10px;
}
.count-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text-muted);
}
.count-dot {
  width: 6px; height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.count-dot--total  { background: var(--accent); }
.count-dot--data   { background: var(--positive); }
.count-dot--nodata { background: var(--text-muted); opacity: 0.5; }
</style>
