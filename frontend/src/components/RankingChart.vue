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
import { useStationData, useFilteredStations } from '@/composables/useStationData'
import { VARIABLES } from '@/types'
import type { Station } from '@/types'

use([BarChart, GridComponent, TooltipComponent, DataZoomComponent, CanvasRenderer])

const store = useStationsStore()
const { rankingMode, selectedVariable, networkFilter } = storeToRefs(store)
const { stationsQuery } = useStationData()
const filteredStations = useFilteredStations()

const unit = computed(() => VARIABLES[selectedVariable.value].unit)

const sorted = computed<Station[]>(() => {
  const data = filteredStations.value.filter((s) => s.mean !== null)
  if (rankingMode.value === 'delta') {
    return [...data]
      .filter((s) => s.delta_pct !== null)
      .sort((a, b) => (b.delta_pct ?? 0) - (a.delta_pct ?? 0))
  }
  return [...data].sort((a, b) => (b.mean ?? 0) - (a.mean ?? 0))
})

const VISIBLE = 10

function measureMaxLabelWidth(labels: string[], fontSize = 11): number {
  const canvas = document.createElement('canvas')
  const ctx = canvas.getContext('2d')!
  ctx.font = `${fontSize}px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`
  return Math.ceil(Math.max(80, ...labels.map((l) => ctx.measureText(l).width)) + 12)
}

const option = computed(() => {
  const stations = sorted.value
  const names = stations.map((s) =>
    s.name && s.name !== s.id ? `${s.name} / ${s.id}` : s.id,
  )
  const labelWidth = measureMaxLabelWidth(names)
  const values =
    rankingMode.value === 'concentration'
      ? stations.map((s) => s.mean ?? 0)
      : stations.map((s) => s.delta_pct ?? 0)

  const isConcentration = rankingMode.value === 'concentration'
  const n = stations.length
  const filterActive = networkFilter.value.length > 0

  const reversedStations = [...stations].reverse()
  const reversedValues = [...values].reverse()

  const seriesData = reversedStations.map((s, i) => {
    const v = reversedValues[i]!
    const unknown = filterActive && !s.networks
    if (unknown) {
      return { value: v, itemStyle: { color: 'rgba(100, 116, 139, 0.45)', borderRadius: [0, 3, 3, 0] } }
    }
    if (isConcentration) return v
    return {
      value: v,
      itemStyle: {
        color: v > 0
          ? { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{ offset: 0, color: '#f43f5e' }, { offset: 1, color: '#fb7185' }] }
          : { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{ offset: 0, color: '#10b981' }, { offset: 1, color: '#34d399' }] },
        borderRadius: [0, 3, 3, 0],
      },
    }
  })

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
        const station = stations[n - 1 - (p.dataIndex as number)]
        if (!station) return p.name as string
        const val = isConcentration
          ? `${(p.value as number).toFixed(1)} ${unit.value}`
          : `${(p.value as number) > 0 ? '+' : ''}${(p.value as number).toFixed(1)}%`
        const delta =
          station.delta_pct != null
            ? `<br/><span style="color:${station.delta_pct > 0 ? '#f43f5e' : '#10b981'}">${station.delta_pct > 0 ? '▲' : '▼'} ${Math.abs(station.delta_pct).toFixed(1)}% YoY</span>`
            : ''
        const label = station.name && station.name !== station.id
          ? `${station.name} / ${station.id}`
          : station.id
        const unknownNet = filterActive && !station.networks
          ? '<br/><span style="color:#64748b;font-size:10px;font-style:italic">Network affiliation unknown</span>'
          : ''
        return `<b>${label}</b><br/>${val}${delta}${unknownNet}`
      },
    },
    grid: { left: labelWidth + 8, right: 30, top: 6, bottom: 6, containLabel: false },
    dataZoom: [
      {
        type: 'inside',
        yAxisIndex: 0,
        startValue: Math.max(0, n - VISIBLE),
        endValue: n - 1,
        zoomOnMouseWheel: false,
        moveOnMouseWheel: true,
        moveOnMouseMove: false,
        filterMode: 'empty',
      },
      {
        type: 'slider',
        yAxisIndex: 0,
        startValue: Math.max(0, n - VISIBLE),
        endValue: n - 1,
        width: 14,
        right: 4,
        top: 6,
        bottom: 6,
        brushSelect: false,
        filterMode: 'empty',
        showDetail: false,
        showDataShadow: false,
        fillerColor: 'rgba(48, 49, 147, 0.25)',
        borderColor: 'rgba(48, 49, 147, 0.15)',
        handleStyle: { color: '#303193', borderColor: '#303193' },
        moveHandleStyle: { color: '#303193', opacity: 0.6 },
      },
    ],
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
        data: seriesData,
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
