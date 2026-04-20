<script setup lang="ts">
import { computed, ref } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { storeToRefs } from 'pinia'
import { useStationsStore } from '@/stores/stations'
import { useStationData } from '@/composables/useStationData'
import { VARIABLES } from '@/types'
import type { Station } from '@/types'

use([BarChart, GridComponent, TooltipComponent, DataZoomComponent, CanvasRenderer])

const store = useStationsStore()
const { rankingMode, selectedVariable } = storeToRefs(store)
const { stationsQuery } = useStationData()

const unit = computed(() => VARIABLES[selectedVariable.value].unit)

const sorted = computed<Station[]>(() => {
  const data = stationsQuery.data.value ?? []
  if (rankingMode.value === 'delta') {
    return [...data]
      .filter((s) => s.delta_pct !== null)
      .sort((a, b) => (b.delta_pct ?? 0) - (a.delta_pct ?? 0))
  }
  return [...data].sort((a, b) => (b.mean ?? 0) - (a.mean ?? 0))
})

const MAX_VISIBLE = 20

const option = computed(() => {
  const stations = sorted.value.slice(0, MAX_VISIBLE)
  const names = stations.map((s) => s.name)
  const values =
    rankingMode.value === 'concentration'
      ? stations.map((s) => s.mean ?? 0)
      : stations.map((s) => s.delta_pct ?? 0)

  const isConcentration = rankingMode.value === 'concentration'

  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: 'rgba(15, 24, 41, 0.95)',
      borderColor: '#1e3052',
      textStyle: { color: '#e2e8f0', fontSize: 12 },
      formatter: (params: any[]) => {
        const p = params[0]
        const station = stations[p.dataIndex as number]
        if (!station) return p.name as string
        const val = isConcentration
          ? `${(p.value as number).toFixed(1)} ${unit.value}`
          : `${(p.value as number) > 0 ? '+' : ''}${(p.value as number).toFixed(1)}%`
        const delta =
          station.delta_pct != null
            ? `<br/><span style="color:${station.delta_pct > 0 ? '#f43f5e' : '#10b981'}">${station.delta_pct > 0 ? '▲' : '▼'} ${Math.abs(station.delta_pct).toFixed(1)}% YoY</span>`
            : ''
        return `<b>${p.name as string}</b><br/>${val}${delta}`
      },
    },
    grid: { left: 6, right: 20, top: 6, bottom: 30, containLabel: true },
    xAxis: {
      type: 'value',
      axisLine: { lineStyle: { color: '#1e3052' } },
      splitLine: { lineStyle: { color: '#1e3052', type: 'dashed' } },
      axisLabel: {
        color: '#64748b',
        fontSize: 10,
        formatter: isConcentration
          ? (v: number) => (v >= 1000 ? `${(v / 1000).toFixed(0)}k` : String(v))
          : (v: number) => `${v}%`,
      },
    },
    yAxis: {
      type: 'category',
      data: [...names].reverse(),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: '#94a3b8', fontSize: 11 },
    },
    series: [
      {
        type: 'bar',
        data: isConcentration
          ? [...values].reverse()
          : [...values].reverse().map((v) => ({
              value: v,
              itemStyle: {
                color:
                  v > 0
                    ? { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{ offset: 0, color: '#f43f5e' }, { offset: 1, color: '#fb7185' }] }
                    : { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{ offset: 0, color: '#10b981' }, { offset: 1, color: '#34d399' }] },
              },
            })),
        itemStyle: isConcentration
          ? {
              color: {
                type: 'linear',
                x: 0, y: 0, x2: 1, y2: 0,
                colorStops: [
                  { offset: 0, color: '#0284c7' },
                  { offset: 1, color: '#7c3aed' },
                ],
              },
              borderRadius: [0, 3, 3, 0],
            }
          : { borderRadius: [0, 3, 3, 0] },
        barMaxWidth: 18,
        emphasis: { itemStyle: { opacity: 0.85 } },
      },
    ],
  }
})
</script>

<template>
  <div class="ranking-panel">
    <div class="panel-header">
      <span class="panel-title">Station Ranking</span>
      <div class="toggle-group">
        <button
          :class="['tog', rankingMode === 'concentration' && 'tog--on']"
          @click="rankingMode = 'concentration'"
        >
          By concentration
        </button>
        <button
          :class="['tog', rankingMode === 'delta' && 'tog--on']"
          @click="rankingMode = 'delta'"
        >
          By annual change
        </button>
      </div>
    </div>

    <div v-if="stationsQuery.isFetching.value && !stationsQuery.data.value" class="chart-loading">
      Loading stations…
    </div>
    <v-chart
      v-else
      class="chart"
      :option="option"
      :autoresize="true"
    />
  </div>
</template>

<style scoped>
.ranking-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--surface);
  border-top: 1px solid var(--border);
  overflow: hidden;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.panel-title {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
}

.toggle-group { display: flex; gap: 4px; }
.tog {
  padding: 4px 10px;
  font-size: 11px;
  background: transparent;
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s;
}
.tog:hover { color: var(--text); border-color: var(--accent); }
.tog--on {
  background: rgba(0, 212, 255, 0.1);
  border-color: var(--accent);
  color: var(--accent);
  font-weight: 600;
}

.chart { flex: 1; min-height: 0; }

.chart-loading {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: var(--text-muted);
}
</style>
