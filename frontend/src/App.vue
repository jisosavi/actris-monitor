<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import ControlPanel from '@/components/ControlPanel.vue'
import StatsCards from '@/components/StatsCards.vue'
import StationMap from '@/components/StationMap.vue'
import RankingChart from '@/components/RankingChart.vue'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { useStationsStore } from '@/stores/stations'
import { useWarmupStatus } from '@/composables/useStationData'
import { VARIABLES } from '@/types'

const store = useStationsStore()
const { selectedYear, selectedVariable } = storeToRefs(store)
const varMeta = computed(() => VARIABLES[selectedVariable.value])

const warmupQuery = useWarmupStatus()
const warmup = computed(() => warmupQuery.data.value)
</script>

<template>
  <div class="shell">
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
        <div v-if="warmup && !warmup.complete" class="warmup-indicator">
          <span class="warmup-dot" />
          <span class="warmup-label">Caching {{ warmup.done }}/{{ warmup.total }}</span>
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

    <!-- Main body -->
    <div class="body">
      <aside class="sidebar">
        <ControlPanel />
        <Separator class="my-3" />
        <StatsCards />
      </aside>

      <div class="content">
        <div class="map-area">
          <StationMap />
        </div>
        <div class="ranking-area">
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

/* ── Content ── */
.content { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.map-area { flex: 1; min-height: 0; position: relative; }
.ranking-area { height: 240px; flex-shrink: 0; background: var(--surface); border-top: 1px solid var(--border); }
</style>
