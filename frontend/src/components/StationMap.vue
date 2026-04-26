<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, shallowRef } from 'vue'
import maplibregl from 'maplibre-gl'
import { MapboxOverlay } from '@deck.gl/mapbox'
import { ScatterplotLayer } from '@deck.gl/layers'
import { storeToRefs } from 'pinia'
import { useStationsStore } from '@/stores/stations'
import { useStationData } from '@/composables/useStationData'
import type { Station } from '@/types'

const mapContainer = ref<HTMLDivElement | null>(null)
const map = shallowRef<maplibregl.Map | null>(null)
const overlay = shallowRef<MapboxOverlay | null>(null)

const store = useStationsStore()
const { rankingMode, hoveredStation } = storeToRefs(store)
const { stationsQuery } = useStationData()

const elapsed = ref(0)
const lastLoadTime = ref<number | null>(null)
const dataTimestamp = ref<string | null>(null)
let timerInterval: ReturnType<typeof setInterval> | null = null
let fetchStart = 0

watch(() => stationsQuery.isFetching.value, (fetching) => {
  if (fetching) {
    elapsed.value = 0
    fetchStart = Date.now()
    timerInterval = setInterval(() => {
      elapsed.value = Math.floor((Date.now() - fetchStart) / 1000)
    }, 1000)
  } else {
    if (timerInterval) { clearInterval(timerInterval); timerInterval = null }
    if (fetchStart > 0) lastLoadTime.value = Math.floor((Date.now() - fetchStart) / 1000)
  }
})

watch(() => stationsQuery.data.value, (data) => {
  if (data?.length) {
    dataTimestamp.value = new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
  }
})

function lerp(a: number, b: number, t: number) { return a + (b - a) * t }

function concColor(v: number, lo: number, hi: number): [number, number, number, number] {
  const t = Math.max(0, Math.min(1, (v - lo) / (hi - lo || 1)))
  if (t < 0.5) {
    const s = t * 2
    return [Math.round(lerp(48, 230, s)), Math.round(lerp(49, 160, s)), Math.round(lerp(147, 0, s)), 220]
  }
  const s = (t - 0.5) * 2
  return [Math.round(lerp(230, 191, s)), Math.round(lerp(160, 48, s)), Math.round(lerp(0, 48, s)), 220]
}

function deltaColor(d: number | null): [number, number, number, number] {
  if (d === null) return [140, 150, 170, 120]
  const intensity = Math.min(1, Math.abs(d) / 40)
  return d > 0
    ? [Math.round(lerp(220, 191, intensity)), Math.round(lerp(60, 48, intensity)), Math.round(lerp(60, 48, intensity)), 230]
    : [Math.round(lerp(30, 26, intensity)), Math.round(lerp(160, 122, intensity)), Math.round(lerp(80, 82, intensity)), 230]
}

function buildLayer(stations: Station[]) {
  const values = stations.map((s) => s.mean ?? 0).filter((v) => v > 0)
  const lo = Math.min(...values)
  const hi = Math.max(...values)

  const noData = stations.filter((s) => s.mean === null)
  console.log('No-data stations:', noData.length, noData.map(s => s.id))

  // Hollow layer for stations with no data for the selected year
  const noDataLayer = new ScatterplotLayer<Station>({
    id: 'stations-nodata',
    data: noData,
    getPosition: (d) => [d.lon, d.lat],
    getRadius: 20000,
    getFillColor: [0, 0, 0, 0],
    getLineColor: [150, 160, 180, 200],
    getLineWidth: 2000,
    lineWidthMinPixels: 2,
    radiusMinPixels: 6,
    radiusMaxPixels: 14,
    filled: true,
    stroked: true,
    pickable: true,
    onHover: ({ object }) => {
      store.hoveredStation = (object as Station) ?? null
    },
  })

  const dataLayer = new ScatterplotLayer<Station>({
    id: 'stations',
    data: stations.filter((s) => s.mean !== null),
    getPosition: (d) => [d.lon, d.lat],
    getRadius: (d) => {
      if (!d.mean || d.mean <= 0) return 20000
      const t = Math.max(0, Math.min(1, (d.mean - lo) / (hi - lo || 1)))
      return 18000 + t * 70000
    },
    getFillColor: (d) =>
      rankingMode.value === 'delta'
        ? deltaColor(d.delta_pct)
        : d.mean
        ? concColor(d.mean, lo, hi)
        : [100, 116, 139, 160],
    getLineColor: [255, 255, 255, 60],
    getLineWidth: 1200,
    lineWidthMinPixels: 1,
    radiusMinPixels: 5,
    radiusMaxPixels: 36,
    pickable: true,
    onHover: ({ object }) => {
      store.hoveredStation = (object as Station) ?? null
    },
    updateTriggers: {
      getFillColor: rankingMode.value,
      getRadius: rankingMode.value,
    },
  })

  return [noDataLayer, dataLayer]
}

function refresh(stations: Station[]) {
  if (!overlay.value) return
  overlay.value.setProps({ layers: buildLayer(stations) })
}

onMounted(() => {
  if (!mapContainer.value) return

  map.value = new maplibregl.Map({
    container: mapContainer.value,
    style: 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json',
    center: [15, 54],
    zoom: 3.5,
    minZoom: 0.5,
    maxZoom: 14,
    attributionControl: false,
  })

  map.value.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right')
  map.value.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
  map.value.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-right')

  overlay.value = new MapboxOverlay({ interleaved: false, layers: [] })
  map.value.addControl(overlay.value as unknown as maplibregl.IControl)

  watch(
    () => stationsQuery.data.value,
    (stations) => { if (stations?.length) refresh(stations) },
    { immediate: true },
  )

  watch(rankingMode, () => {
    if (stationsQuery.data.value?.length) refresh(stationsQuery.data.value)
  })
})

onUnmounted(() => {
  if (timerInterval) clearInterval(timerInterval)
  overlay.value?.finalize()
  map.value?.remove()
})
</script>

<template>
  <div class="map-wrap">
    <div ref="mapContainer" class="map-canvas" />

    <!-- Hover tooltip -->
    <Transition name="fade">
      <div v-if="hoveredStation" class="tooltip">
        <div class="tooltip-name">
          {{ hoveredStation.name && hoveredStation.name !== hoveredStation.id
            ? `${hoveredStation.name} / ${hoveredStation.id}`
            : hoveredStation.id }}
        </div>
        <div class="tooltip-country">{{ hoveredStation.country }}</div>
        <div v-if="hoveredStation.mean !== null" class="tooltip-row">
          <div>
            <div class="tooltip-sub">Annual mean</div>
            <div class="tooltip-val">
              {{ hoveredStation.mean?.toFixed(1) ?? '—' }}
              <span class="tooltip-unit">{{ hoveredStation.unit }}</span>
            </div>
          </div>
          <div v-if="hoveredStation.delta_pct !== null">
            <div class="tooltip-sub">vs prev. year</div>
            <div
              :class="['tooltip-val tooltip-delta', hoveredStation.delta_pct > 0 ? 'delta-up' : 'delta-dn']"
            >
              {{ hoveredStation.delta_pct > 0 ? '▲' : '▼' }}
              {{ Math.abs(hoveredStation.delta_pct).toFixed(1) }}%
            </div>
          </div>
        </div>
        <div v-else class="tooltip-nodata">No data for selected year</div>
        <div v-if="hoveredStation.mean !== null" class="tooltip-coverage">
          Coverage {{ (hoveredStation.data_coverage * 100).toFixed(0) }}%
        </div>
      </div>
    </Transition>

    <!-- Legend -->
    <div class="legend">
      <div class="legend-label">
        {{ rankingMode === 'concentration' ? 'Concentration' : 'Annual change' }}
      </div>
      <div :class="['legend-bar', rankingMode === 'delta' ? 'legend-bar--delta' : 'legend-bar--conc']" />
      <div class="legend-ticks">
        <span v-if="rankingMode === 'concentration'">Low</span>
        <span v-else style="color: var(--positive)">Decrease</span>
        <span v-if="rankingMode === 'concentration'">High</span>
        <span v-else style="color: var(--negative)">Increase</span>
      </div>
      <div v-if="dataTimestamp" class="legend-timestamp">Updated {{ dataTimestamp }}</div>
    </div>

    <!-- Loading veil -->
    <Transition name="veil">
      <div v-if="stationsQuery.isFetching.value" class="loading-veil">
        <div class="loading-box">
          <div class="spinner" />
          <div class="loading-msg">
            <span v-if="!stationsQuery.data.value">Fetching from EBAS THREDDS…</span>
            <span v-else>Updating…</span>
          </div>
          <div class="loading-timer">{{ elapsed }}s</div>
          <div v-if="lastLoadTime !== null" class="loading-prev">
            Last time: {{ lastLoadTime }}s
          </div>
          <div v-if="!stationsQuery.data.value" class="loading-sub">
            First load takes 30–90 s while data is fetched from remote servers. Results are cached for 24 h.
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.map-wrap { position: relative; width: 100%; height: 100%; }
.map-canvas { width: 100%; height: 100%; }

.tooltip {
  position: absolute;
  top: 14px;
  left: 14px;
  background: rgba(255, 255, 255, 0.97);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px 14px;
  backdrop-filter: blur(10px);
  pointer-events: none;
  z-index: 10;
  min-width: 170px;
  box-shadow: 0 4px 16px rgba(48, 49, 147, 0.10);
}
.tooltip-name { font-size: 14px; font-weight: 600; color: var(--accent); margin-bottom: 2px; }
.tooltip-country { font-size: 11px; color: var(--text-muted); margin-bottom: 10px; }
.tooltip-row { display: flex; gap: 20px; }
.tooltip-sub { font-size: 10px; color: var(--text-muted); margin-bottom: 2px; }
.tooltip-val { font-size: 16px; font-weight: 700; font-variant-numeric: tabular-nums; color: var(--text); }
.tooltip-unit { font-size: 10px; color: var(--text-muted); }
.tooltip-delta { font-size: 14px; }
.delta-up { color: var(--negative); }
.delta-dn { color: var(--positive); }
.tooltip-nodata { font-size: 11px; color: var(--text-muted); margin-top: 4px; font-style: italic; }
.tooltip-coverage { font-size: 10px; color: var(--text-muted); margin-top: 8px; }

.legend {
  position: absolute;
  bottom: 48px;
  left: 14px;
  background: rgba(255, 255, 255, 0.95);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  backdrop-filter: blur(10px);
  z-index: 10;
  min-width: 150px;
  box-shadow: 0 2px 8px rgba(48, 49, 147, 0.08);
}
.legend-label { font-size: 10px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: var(--text-muted); margin-bottom: 6px; }
.legend-bar { height: 8px; border-radius: 4px; }
.legend-bar--conc { background: linear-gradient(to right, #303193, #e6a000, #bf3030); }
.legend-bar--delta { background: linear-gradient(to right, #1a7a52, #c8ccd8, #bf3030); }
.legend-ticks { display: flex; justify-content: space-between; margin-top: 4px; font-size: 10px; color: var(--text-muted); }
.legend-timestamp { margin-top: 7px; font-size: 10px; color: var(--text-muted); opacity: 0.7; }

.loading-veil {
  position: absolute;
  inset: 0;
  background: rgba(238, 241, 247, 0.80);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.loading-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
  padding: 28px 32px;
  background: rgba(255, 255, 255, 0.97);
  border: 1px solid var(--border);
  border-radius: 14px;
  max-width: 320px;
  text-align: center;
  box-shadow: 0 8px 32px rgba(48, 49, 147, 0.12);
}
.spinner {
  width: 36px; height: 36px;
  border: 3px solid rgba(48, 49, 147, 0.15);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}
.loading-msg {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}
.loading-timer {
  font-size: 28px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: var(--accent);
  line-height: 1;
}
.loading-prev {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: -4px;
}
.loading-sub {
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.5;
}
@keyframes spin { to { transform: rotate(360deg); } }

.fade-enter-active, .fade-leave-active { transition: opacity 0.18s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
.veil-enter-active, .veil-leave-active { transition: opacity 0.3s ease; }
.veil-enter-from, .veil-leave-to { opacity: 0; }
</style>
