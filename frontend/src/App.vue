<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { storeToRefs } from 'pinia'
import ControlPanel from '@/components/ControlPanel.vue'
import StatsCards from '@/components/StatsCards.vue'
import StationMap from '@/components/StationMap.vue'
import RankingChart from '@/components/RankingChart.vue'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { useStationsStore } from '@/stores/stations'
import { useFetchProgress, useDbStatus } from '@/composables/useStationData'
import { VARIABLES } from '@/types'
import FirstRunModal from '@/components/FirstRunModal.vue'
import AdminPanel from '@/components/AdminPanel.vue'

const store = useStationsStore()
const { selectedYear, selectedVariable, showDataSetup } = storeToRefs(store)
const varMeta = computed(() => VARIABLES[selectedVariable.value])

const { data: job } = useFetchProgress()

/**
 * Drag the ranking panel's top edge to trade space with the map.
 *
 * The layout is already a flex column, so only this height is owned here — the
 * map takes whatever is left. The chart follows on its own: `v-chart` is mounted
 * with `autoresize`, which watches the container rather than the window.
 */
const RANKING_DEFAULT = 240
const RANKING_MIN = 120          // below this the bars and their labels collide
const RANKING_MAX_FRACTION = 0.7 // leave the map recognisably a map

function loadRankingHeight(): number {
  try {
    const stored = Number(localStorage.getItem('rankingHeight'))
    if (Number.isFinite(stored) && stored >= RANKING_MIN) return stored
  } catch {
    // Private windows and blocked site data throw here; the default is fine.
  }
  return RANKING_DEFAULT
}

const rankingHeight = ref(loadRankingHeight())
const isDragging = ref(false)

function clampHeight(px: number): number {
  return Math.min(Math.max(px, RANKING_MIN), window.innerHeight * RANKING_MAX_FRACTION)
}

function onDragMove(event: PointerEvent) {
  // The panel is bottom-anchored, so its height is the distance from the pointer
  // to the bottom of the window.
  rankingHeight.value = clampHeight(window.innerHeight - event.clientY)
}

function stopDragging() {
  if (!isDragging.value) return
  isDragging.value = false
  document.body.style.userSelect = ''
  window.removeEventListener('pointermove', onDragMove)
  window.removeEventListener('pointerup', stopDragging)
  try {
    localStorage.setItem('rankingHeight', String(Math.round(rankingHeight.value)))
  } catch {
    // Not being able to remember the size is not worth breaking the drag over.
  }
}

function startDragging() {
  isDragging.value = true
  // Without this a drag selects the header text it passes over.
  document.body.style.userSelect = 'none'
  window.addEventListener('pointermove', onDragMove)
  window.addEventListener('pointerup', stopDragging)
}

function resetRankingHeight() {
  rankingHeight.value = RANKING_DEFAULT
  try {
    localStorage.removeItem('rankingHeight')
  } catch {
    // As above.
  }
}

onBeforeUnmount(stopDragging)
const { data: dbStatus } = useDbStatus()

const showFirstRun = computed(() => dbStatus.value?.is_empty === true || showDataSetup.value)
const isFetching = computed(() => job.value?.status === 'running')
</script>

<template>
  <div class="shell">
    <!-- First-run modal when DB is empty -->
    <FirstRunModal v-if="showFirstRun" />

    <!-- Header -->
    <header class="header">
      <div class="header-brand">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" class="brand-icon">
          <circle cx="12" cy="12" r="10" stroke="#303193" stroke-width="1.8" />
          <circle cx="12" cy="12" r="5"  stroke="#303193" stroke-width="1.8" stroke-dasharray="3 2" />
          <circle cx="12" cy="12" r="1.8" fill="#303193" />
        </svg>
        <span class="brand-name">ACTRIS Monitor</span>
        <Separator orientation="vertical" class="h-4 mx-1" />
        <span class="brand-sub">Aerosol In-Situ Network</span>
      </div>

      <div class="header-badges">
        <Badge variant="outline" class="badge-year">{{ selectedYear }}</Badge>
        <Badge variant="outline" class="badge-var">{{ varMeta.shortLabel }}</Badge>
        <Badge variant="outline" class="badge-unit">{{ varMeta.unit }}</Badge>
      </div>

      <Transition name="warmup-fade">
        <div v-if="isFetching" class="warmup-indicator">
          <span class="warmup-dot" />
          <span class="warmup-label">Fetching {{ job?.done }}/{{ job?.total }}</span>
        </div>
      </Transition>

      <div class="header-right">
        <a href="https://www.actris.eu" target="_blank" rel="noopener" class="header-link">
          actris.eu ↗
        </a>
        <Separator orientation="vertical" class="h-4 mx-3" />
        <a href="https://ebas.nilu.no" target="_blank" rel="noopener" class="header-link">
          EBAS ↗
        </a>
      </div>
    </header>

    <!-- Main body — only when DB has data -->
    <div v-if="dbStatus && !dbStatus.is_empty" class="body">
      <aside class="sidebar">
        <ControlPanel />
        <Separator class="my-3" />
        <StatsCards />
        <div class="sidebar-spacer" />
        <Separator />
        <AdminPanel />
      </aside>

      <div class="content">
        <div class="map-area">
          <StationMap />
        </div>
        <div
          class="ranking-resize"
          :class="isDragging && 'ranking-resize--active'"
          role="separator"
          aria-orientation="horizontal"
          aria-label="Resize the station ranking"
          title="Drag to resize · double-click to reset"
          @pointerdown.prevent="startDragging"
          @dblclick="resetRankingHeight"
        />
        <div class="ranking-area" :style="{ height: rankingHeight + 'px' }">
          <RankingChart />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  flex-direction: column;
  height: 100vh;
  width: 100vw;
  overflow: hidden;
  background: var(--bg);
}

/* ── Header ── */
.header {
  display: flex;
  align-items: center;
  gap: 16px;
  height: 52px;
  padding: 0 20px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  z-index: 100;
  box-shadow: 0 1px 3px rgba(48, 49, 147, 0.06);
}

.header-brand { display: flex; align-items: center; gap: 8px; }

.brand-icon { flex-shrink: 0; }

.brand-name {
  font-size: 15px;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: var(--accent);
  white-space: nowrap;
}

.brand-sub {
  font-size: 11px;
  color: var(--text-muted);
  white-space: nowrap;
}

.header-badges {
  display: flex;
  gap: 6px;
  margin-left: auto;
}

.badge-year {
  font-variant-numeric: tabular-nums;
  color: var(--accent);
  border-color: rgba(48, 49, 147, 0.3);
  background: rgba(48, 49, 147, 0.06);
  font-weight: 600;
}
.badge-var {
  font-family: Georgia, serif;
  font-style: italic;
  color: var(--text);
  border-color: var(--border);
}
.badge-unit {
  font-family: monospace;
  color: var(--text-muted);
  border-color: var(--border);
}

.warmup-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-left: 8px;
}
.warmup-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--accent);
  opacity: 0.7;
  animation: warmup-pulse 1.4s ease-in-out infinite;
  flex-shrink: 0;
}
.warmup-label {
  font-size: 11px;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
@keyframes warmup-pulse {
  0%, 100% { opacity: 0.25; transform: scale(0.9); }
  50%       { opacity: 0.8;  transform: scale(1.1); }
}
.warmup-fade-enter-active, .warmup-fade-leave-active { transition: opacity 0.4s ease; }
.warmup-fade-enter-from, .warmup-fade-leave-to { opacity: 0; }

.header-right {
  display: flex;
  align-items: center;
  margin-left: 8px;
}
.header-link {
  font-size: 11px;
  color: var(--text-muted);
  text-decoration: none;
  transition: color 0.15s;
}
.header-link:hover { color: var(--accent); }

/* ── Body ── */
.body { display: flex; flex: 1; min-height: 0; }

/* ── Sidebar ── */
.sidebar {
  width: 268px;
  flex-shrink: 0;
  background: var(--surface);
  border-right: 1px solid var(--border);
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  padding-top: 4px;
  box-shadow: 1px 0 4px rgba(48, 49, 147, 0.04);
}

.sidebar-spacer { flex: 1; }

/* ── Content ── */
.content { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.map-area { flex: 1; min-height: 0; position: relative; }
.ranking-area { flex-shrink: 0; background: var(--surface); border-top: 1px solid var(--border); }

/* A 7px grab strip standing in for the panel's top border: thin enough not to
   read as a divider, thick enough to hit without aiming. */
.ranking-resize {
  height: 7px;
  flex-shrink: 0;
  cursor: row-resize;
  background: var(--border);
  transition: background 0.15s ease;
}
.ranking-resize:hover,
.ranking-resize--active { background: var(--accent); }
</style>
