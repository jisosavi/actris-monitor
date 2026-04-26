<script setup lang="ts">
import { computed } from 'vue'
import { useFilteredStations } from '@/composables/useStationData'
import { useStationsStore } from '@/stores/stations'
import { storeToRefs } from 'pinia'
import { VARIABLES } from '@/types'
import { Card, CardContent } from '@/components/ui/card'

const store = useStationsStore()
const { selectedVariable, networkFilter } = storeToRefs(store)
const filteredStations = useFilteredStations()

const unit = computed(() => VARIABLES[selectedVariable.value].unit)

function computeStats(values: number[]) {
  const sorted = [...values].sort((a, b) => a - b)
  if (sorted.length === 0) return null
  const pct = (p: number) => {
    const idx = (p / 100) * (sorted.length - 1)
    const lo = Math.floor(idx); const hi = Math.ceil(idx)
    return sorted[lo]! + (sorted[hi]! - sorted[lo]!) * (idx - lo)
  }
  return { median: pct(50), q1: pct(25), q3: pct(75), min: sorted[0]!, max: sorted[sorted.length - 1]! }
}

const filteredStats = computed(() => {
  const values = filteredStations.value.filter(s => s.mean !== null).map(s => s.mean as number)
  const s = computeStats(values)
  return s ? { ...s, n_stations: values.length } : null
})

// Previous year values derived from delta_pct: prev = current / (1 + delta_pct/100)
const prevStats = computed(() => {
  const values = filteredStations.value
    .filter(s => s.mean !== null && s.delta_pct !== null)
    .map(s => s.mean! / (1 + s.delta_pct! / 100))
    .filter(v => v > 0 && isFinite(v))
  return computeStats(values)
})

interface Delta { pct: number; abs: number }

function diff(curr: number | null | undefined, prev: number | null | undefined): Delta | null {
  if (curr == null || prev == null || prev === 0) return null
  return { abs: curr - prev, pct: ((curr - prev) / prev) * 100 }
}

function fmt(v: number | null | undefined, decimals = 1): string {
  if (v == null) return '—'
  return Math.abs(v) >= 1000 ? (v / 1000).toFixed(1) + 'k' : v.toFixed(decimals)
}

function fmtDelta(d: Delta | null): { pctStr: string; absStr: string; up: boolean } | null {
  if (!d) return null
  const sign = d.abs >= 0 ? '+' : ''
  return {
    pctStr: `${sign}${d.pct.toFixed(1)}%`,
    absStr: `${sign}${fmt(d.abs)}`,
    up: d.abs >= 0,
  }
}

const iqrCurr = computed(() =>
  filteredStats.value ? filteredStats.value.q3 - filteredStats.value.q1 : null)
const iqrPrev = computed(() =>
  prevStats.value ? prevStats.value.q3 - prevStats.value.q1 : null)

const totalStations = computed(() => filteredStations.value.length)
const withData = computed(() => filteredStations.value.filter(s => s.mean !== null).length)
const withoutData = computed(() => totalStations.value - withData.value)
</script>

<template>
  <div class="stats-section">
    <div class="section-label">Network statistics</div>

    <div class="cards-grid">
      <!-- Median -->
      <Card class="stat-card stat-card--median">
        <CardContent class="stat-content">
          <div class="stat-label">Median</div>
          <div class="stat-value">{{ fmt(filteredStats?.median) }}</div>
          <div class="stat-unit">{{ unit }}</div>
          <StatDelta :d="fmtDelta(diff(filteredStats?.median, prevStats?.median))" />
        </CardContent>
      </Card>

      <!-- IQR -->
      <Card class="stat-card stat-card--iqr">
        <CardContent class="stat-content">
          <div class="stat-label">IQR</div>
          <div class="stat-value stat-value--sm">{{ fmt(filteredStats?.q1) }}–{{ fmt(filteredStats?.q3) }}</div>
          <div class="stat-unit">{{ unit }}</div>
          <StatDelta :d="fmtDelta(diff(iqrCurr, iqrPrev))" label="spread" />
        </CardContent>
      </Card>

      <!-- Max -->
      <Card class="stat-card stat-card--max">
        <CardContent class="stat-content">
          <div class="stat-label">Max</div>
          <div class="stat-value">{{ fmt(filteredStats?.max) }}</div>
          <div class="stat-unit">{{ unit }}</div>
          <StatDelta :d="fmtDelta(diff(filteredStats?.max, prevStats?.max))" />
        </CardContent>
      </Card>

      <!-- Min -->
      <Card class="stat-card stat-card--min">
        <CardContent class="stat-content">
          <div class="stat-label">Min</div>
          <div class="stat-value">{{ fmt(filteredStats?.min) }}</div>
          <div class="stat-unit">{{ unit }}</div>
          <StatDelta :d="fmtDelta(diff(filteredStats?.min, prevStats?.min))" />
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
    <div v-if="networkFilter.length > 0" class="filter-note">
      Filtered to {{ networkFilter.join(', ') }}
    </div>
  </div>
</template>

<!-- Inline sub-component for the delta row -->
<script lang="ts">
import { defineComponent, h } from 'vue'

const StatDelta = defineComponent({
  props: {
    d: { type: Object as () => { pctStr: string; absStr: string; up: boolean } | null, default: null },
    label: { type: String, default: '' },
  },
  setup(props) {
    return () => {
      if (!props.d) return null
      const arrow = props.d.up ? '▲' : '▼'
      const cls = props.d.up ? 'delta-up' : 'delta-dn'
      const labelPart = props.label ? h('span', { class: 'delta-label' }, ` ${props.label}`) : null
      return h('div', { class: ['stat-delta', cls] }, [
        h('span', { class: 'delta-arrow' }, arrow + ' '),
        h('span', { class: 'delta-pct' }, props.d.pctStr),
        h('span', { class: 'delta-abs' }, `  ${props.d.absStr}`),
        labelPart,
      ])
    }
  },
})

export { StatDelta }
</script>

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

.stat-delta {
  display: flex;
  align-items: baseline;
  gap: 0;
  margin-top: 6px;
  font-size: 10px;
  font-variant-numeric: tabular-nums;
  line-height: 1;
  flex-wrap: wrap;
  column-gap: 3px;
}
.delta-up { color: var(--negative); }
.delta-dn { color: var(--positive); }
.delta-pct { font-weight: 600; }
.delta-abs { color: inherit; opacity: 0.7; }
.delta-label { font-size: 9px; opacity: 0.6; margin-left: 2px; }

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

.filter-note { font-size: 10px; color: var(--accent); margin-top: 6px; }
</style>
