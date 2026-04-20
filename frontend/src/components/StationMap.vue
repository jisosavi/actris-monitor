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

function lerp(a: number, b: number, t: number) { return a + (b - a) * t }

function concColor(v: number, lo: number, hi: number): [number, number, number, number] {
  const t = Math.max(0, Math.min(1, (v - lo) / (hi - lo || 1)))
  if (t < 0.5) {
    const s = t * 2
    return [Math.round(lerp(0, 250, s)), Math.round(lerp(212, 180, s)), Math.round(lerp(255, 0, s)), 210]
  }
  const s = (t - 0.5) * 2
  return [Math.round(lerp(250, 255, s)), Math.round(lerp(180, 40, s)), 0, 210]
}

function deltaColor(d: number | null): [number, number, number, number] {
  if (d === null) return [100, 116, 139, 160]
  const intensity = Math.min(1, Math.abs(d) / 40)
  return d > 0
    ? [Math.round(lerp(200, 244, intensity)), Math.round(lerp(40, 63, intensity * 0.2)), Math.round(lerp(80, 94, intensity * 0.2)), 220]
    : [Math.round(lerp(30, 16, intensity)), Math.round(lerp(140, 185, intensity)), Math.round(lerp(100, 129, intensity)), 220]
}

function buildLayer(stations: Station[]) {
  const values = stations.map((s) => s.mean ?? 0).filter((v) => v > 0)
  const lo = Math.min(...values)
  const hi = Math.max(...values)

  return new ScatterplotLayer<Station>({
    id: 'stations',
    data: stations,
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
}

function refresh(stations: Station[]) {
  if (!overlay.value) return
  overlay.value.setProps({ layers: [buildLayer(stations)] })
}

onMounted(() => {
  if (!mapContainer.value) return

  map.value = new maplibregl.Map({
    container: mapContainer.value,
    style: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
    center: [15, 54],
    zoom: 3.5,
    minZoom: 2,
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
        <div class="tooltip-name">{{ hoveredStation.name }}</div>
        <div class="tooltip-country">{{ hoveredStation.country }} · {{ hoveredStation.id }}</div>
        <div class="tooltip-row">
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
        <div class="tooltip-coverage">
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
    </div>

    <!-- Loading veil -->
    <Transition name="veil">
      <div v-if="stationsQuery.isFetching.value" class="loading-veil">
        <div class="spinner" />
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
  background: rgba(7, 13, 26, 0.92);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px 14px;
  backdrop-filter: blur(10px);
  pointer-events: none;
  z-index: 10;
  min-width: 170px;
}
.tooltip-name { font-size: 14px; font-weight: 600; color: var(--accent); margin-bottom: 2px; }
.tooltip-country { font-size: 11px; color: var(--text-muted); margin-bottom: 10px; }
.tooltip-row { display: flex; gap: 20px; }
.tooltip-sub { font-size: 10px; color: var(--text-muted); margin-bottom: 2px; }
.tooltip-val { font-size: 16px; font-weight: 700; font-variant-numeric: tabular-nums; }
.tooltip-unit { font-size: 10px; color: var(--text-muted); }
.tooltip-delta { font-size: 14px; }
.delta-up { color: var(--negative); }
.delta-dn { color: var(--positive); }
.tooltip-coverage { font-size: 10px; color: var(--text-muted); margin-top: 8px; }

.legend {
  position: absolute;
  bottom: 48px;
  left: 14px;
  background: rgba(7, 13, 26, 0.85);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  backdrop-filter: blur(10px);
  z-index: 10;
  min-width: 150px;
}
.legend-label { font-size: 10px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: var(--text-muted); margin-bottom: 6px; }
.legend-bar { height: 8px; border-radius: 4px; }
.legend-bar--conc { background: linear-gradient(to right, #00d4ff, #fab40a, #ff2832); }
.legend-bar--delta { background: linear-gradient(to right, #10b981, #94a3b8, #f43f5e); }
.legend-ticks { display: flex; justify-content: space-between; margin-top: 4px; font-size: 10px; color: var(--text-muted); }

.loading-veil {
  position: absolute;
  inset: 0;
  background: rgba(7, 13, 26, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.spinner {
  width: 36px; height: 36px;
  border: 3px solid rgba(0, 212, 255, 0.15);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.fade-enter-active, .fade-leave-active { transition: opacity 0.18s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
.veil-enter-active, .veil-leave-active { transition: opacity 0.3s ease; }
.veil-enter-from, .veil-leave-to { opacity: 0; }
</style>
