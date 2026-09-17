<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, shallowRef } from 'vue'
import maplibregl from 'maplibre-gl'
import { MapboxOverlay } from '@deck.gl/mapbox'
import { ScatterplotLayer } from '@deck.gl/layers'
import { storeToRefs } from 'pinia'
import { useStationsStore } from '@/stores/stations'
import { useStationData, useFilteredStations, useNrtStations } from '@/composables/useStationData'
import StationDetail from '@/components/StationDetail.vue'
import type { Station, NrtStation } from '@/types'

const mapContainer = ref<HTMLDivElement | null>(null)
const map = shallowRef<maplibregl.Map | null>(null)
const overlay = shallowRef<MapboxOverlay | null>(null)

const store = useStationsStore()
const { rankingMode, hoveredStation, networkFilter, selectedStationId } = storeToRefs(store)
const { stationsQuery } = useStationData()
const filteredStations = useFilteredStations()
const { data: nrt } = useNrtStations()

/** Station ids with live data — drives the badge on markers we already show. */
const nrtIds = computed(() => new Set(Object.keys(nrt.value?.stations ?? {})))

const hoveredHasNrt = computed(() =>
  hoveredStation.value ? nrtIds.value.has(hoveredStation.value.id) : false,
)

/**
 * Sites that report live data but appear nowhere in our own record.
 *
 * `known` comes from the backend, which compares against every station we hold in
 * any year. Subtracting the *selected year's* stations here instead would draw our
 * own stations as unknown sites whenever they have no data for that year — and in
 * an empty year, the whole NRT network would appear as extra markers.
 *
 * They are drawn from a different dataset and must stay out of every aggregate —
 * the ranking chart, the network statistics and the colour scale all read
 * `filteredStations`, which these never enter.
 */
type NrtOnlyStation = NrtStation & { id: string }

const nrtOnlyStations = computed<NrtOnlyStation[]>(() =>
  Object.entries(nrt.value?.stations ?? {})
    .filter(([, entry]) => !entry.known)
    .map(([id, entry]) => ({ id, ...entry })),
)

function select(id: string | null) {
  // Clicking the pinned station again, or the empty map, clears the panel.
  store.selectedStationId = store.selectedStationId === id ? null : id
}

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

const isNoData = computed(() => {
  if (stationsQuery.isFetching.value) return false
  if (stationsQuery.isError.value) return true
  const data = stationsQuery.data.value
  if (data === undefined) return false
  // `every` is already true for an empty array, so no length check is needed.
  return data.every(s => s.mean === null)
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
    onClick: ({ object }) => {
      if (object) select((object as Station).id)
      return true
    },
  })

  // Live-data-only sites. Cyan is deliberately outside both colour scales
  // (blue→amber→red for concentration, green→grey→red for change) and distinct
  // from the grey hollow rings, so it reads as a different kind of thing rather
  // than another state of the same thing.
  const nrtOnlyLayer = new ScatterplotLayer<NrtOnlyStation>({
    id: 'stations-nrt-only',
    data: nrtOnlyStations.value,
    getPosition: (d) => [d.lon, d.lat],
    getRadius: 16000,
    getFillColor: [14, 157, 184, 190],
    getLineColor: [255, 255, 255, 220],
    getLineWidth: 2400,
    lineWidthMinPixels: 2,
    radiusMinPixels: 5,
    radiusMaxPixels: 11,
    filled: true,
    stroked: true,
    pickable: true,
    onClick: ({ object }) => {
      if (object) select((object as NrtOnlyStation).id)
      return true
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
    getFillColor: (d) => {
      if (networkFilter.value.length > 0 && !d.networks) return [140, 148, 165, 120]
      return rankingMode.value === 'delta'
        ? deltaColor(d.delta_pct)
        : d.mean
        ? concColor(d.mean, lo, hi)
        : [100, 116, 139, 160]
    },
    getLineColor: (d) =>
      networkFilter.value.length > 0 && !d.networks
        ? [140, 148, 165, 80]
        : [255, 255, 255, 60],
    getLineWidth: 1200,
    lineWidthMinPixels: 1,
    radiusMinPixels: 5,
    radiusMaxPixels: 36,
    pickable: true,
    onHover: ({ object }) => {
      store.hoveredStation = (object as Station) ?? null
    },
    onClick: ({ object }) => {
      if (object) select((object as Station).id)
      return true
    },
    updateTriggers: {
      getFillColor: [rankingMode.value, networkFilter.value.length],
      getLineColor: networkFilter.value.length,
      getRadius: rankingMode.value,
    },
  })

  // NRT-only sites sit under our own markers: where a site is both, ours wins.
  return [nrtOnlyLayer, noDataLayer, dataLayer]
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

  overlay.value = new MapboxOverlay({
    interleaved: false,
    layers: [],
    // Without this the cursor stays a grab hand over every marker, and nothing
    // suggests the stations can be clicked at all.
    getCursor: ({ isHovering, isDragging }) =>
      isDragging ? 'grabbing' : isHovering ? 'pointer' : 'grab',
    // Fires only when no layer handled the click — a layer's onClick returns true
    // and stops here — so this is the "clicked empty map" case.
    onClick: (info) => {
      if (!info.object) store.selectedStationId = null
    },
  })
  map.value.addControl(overlay.value as unknown as maplibregl.IControl)

  watch(
    filteredStations,
    (stations) => { refresh(stations ?? []) },
    { immediate: true },
  )

  watch(rankingMode, () => {
    refresh(filteredStations.value ?? [])
  })

  // The NRT query resolves after the first render, so the layers have to be
  // rebuilt when it lands or the live-data markers never appear.
  watch(nrtOnlyStations, () => {
    refresh(filteredStations.value ?? [])
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

    <!-- Pinned station details. Takes the tooltip's corner, so the tooltip yields. -->
    <StationDetail />

    <!-- Hover tooltip -->
    <Transition name="fade">
      <div v-if="hoveredStation && !selectedStationId" class="tooltip">
        <div class="tooltip-name">
          {{ hoveredStation.name && hoveredStation.name !== hoveredStation.id
            ? `${hoveredStation.name} / ${hoveredStation.id}`
            : hoveredStation.id }}
        </div>
        <div class="tooltip-country">{{ hoveredStation.country }}</div>
        <div class="tooltip-coords">
          {{ hoveredStation.lat >= 0 ? hoveredStation.lat.toFixed(3) + '°N' : Math.abs(hoveredStation.lat).toFixed(3) + '°S' }},
          {{ hoveredStation.lon >= 0 ? hoveredStation.lon.toFixed(3) + '°E' : Math.abs(hoveredStation.lon).toFixed(3) + '°W' }}
        </div>
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
        <div v-if="networkFilter.length > 0 && !hoveredStation.networks" class="tooltip-unknown-net">
          Network affiliation unknown
        </div>
        <div
          v-if="hoveredStation.mean !== null && hoveredStation.observed_fraction !== null"
          class="tooltip-coverage"
        >
          {{ (hoveredStation.observed_fraction * 100).toFixed(0) }}% of the year observed
        </div>
        <div v-if="hoveredHasNrt" class="tooltip-live">
          <span class="tooltip-live-dot" />LIVE data available
        </div>
        <div class="tooltip-hint">Click the station for details →</div>
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
      <div v-if="nrtOnlyStations.length" class="legend-nrt">
        <span class="legend-nrt-dot" />Live data only
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

    <!-- No data veil -->
    <Transition name="veil">
      <div v-if="isNoData" class="nodata-veil">
        <div class="nodata-box">
          <div class="nodata-icon">○</div>
          <div class="nodata-msg">No data available for this year</div>
          <div class="nodata-sub">Select a different year or use the Data panel to fetch it.</div>
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
.tooltip-country { font-size: 11px; color: var(--text-muted); margin-bottom: 2px; }
.tooltip-coords { font-size: 10px; color: var(--text-muted); font-variant-numeric: tabular-nums; margin-bottom: 10px; font-family: monospace; }
.tooltip-row { display: flex; gap: 20px; }
.tooltip-sub { font-size: 10px; color: var(--text-muted); margin-bottom: 2px; }
.tooltip-val { font-size: 16px; font-weight: 700; font-variant-numeric: tabular-nums; color: var(--text); }
.tooltip-unit { font-size: 10px; color: var(--text-muted); }
.tooltip-delta { font-size: 14px; }
.delta-up { color: var(--negative); }
.delta-dn { color: var(--positive); }
.tooltip-nodata { font-size: 11px; color: var(--text-muted); margin-top: 4px; font-style: italic; }
.tooltip-unknown-net { font-size: 10px; color: var(--text-muted); margin-top: 6px; font-style: italic; }
.tooltip-coverage { font-size: 10px; color: var(--text-muted); margin-top: 8px; }
.tooltip-live {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 8px;
  font-size: 10px;
  font-weight: 600;
  color: #0b7f96;
}
.tooltip-live-dot { width: 6px; height: 6px; border-radius: 50%; background: #0e9db8; }
.tooltip-hint {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px solid var(--border);
  font-size: 10px;
  font-weight: 600;
  color: var(--accent);
  letter-spacing: 0.02em;
}

.legend-nrt {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 7px;
  font-size: 10px;
  color: var(--text-muted);
}
.legend-nrt-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #0e9db8;
  border: 1.5px solid #fff;
  box-shadow: 0 0 0 1px rgba(14, 157, 184, 0.35);
  flex-shrink: 0;
}

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

.nodata-veil {
  position: absolute;
  inset: 0;
  background: rgba(238, 241, 247, 0.80);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.nodata-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 28px 32px;
  background: rgba(255, 255, 255, 0.97);
  border: 1px solid var(--border);
  border-radius: 14px;
  max-width: 300px;
  text-align: center;
  box-shadow: 0 8px 32px rgba(48, 49, 147, 0.10);
}
.nodata-icon {
  font-size: 32px;
  color: var(--text-muted);
  line-height: 1;
  opacity: 0.5;
}
.nodata-msg {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}
.nodata-sub {
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.5;
}

.fade-enter-active, .fade-leave-active { transition: opacity 0.18s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
.veil-enter-active, .veil-leave-active { transition: opacity 0.3s ease; }
.veil-enter-from, .veil-leave-to { opacity: 0; }
</style>
