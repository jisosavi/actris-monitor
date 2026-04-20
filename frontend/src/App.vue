<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import ControlPanel from '@/components/ControlPanel.vue'
import StatsCards from '@/components/StatsCards.vue'
import StationMap from '@/components/StationMap.vue'
import RankingChart from '@/components/RankingChart.vue'
import { useStationsStore } from '@/stores/stations'
import { VARIABLES } from '@/types'

const store = useStationsStore()
const { selectedYear, selectedVariable } = storeToRefs(store)
const varMeta = computed(() => VARIABLES[selectedVariable.value])
</script>

<template>
  <div class="shell">
    <!-- Header -->
    <header class="header">
      <div class="header-brand">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" class="brand-icon">
          <circle cx="12" cy="12" r="10" stroke="#00d4ff" stroke-width="1.5" />
          <circle cx="12" cy="12" r="5" stroke="#7c3aed" stroke-width="1.5" />
          <circle cx="12" cy="12" r="1.5" fill="#00d4ff" />
        </svg>
        <span class="brand-name">ACTRIS Monitor</span>
        <span class="brand-sub">Aerosol In-Situ Network</span>
      </div>
      <div class="header-badges">
        <span class="badge badge--year">{{ selectedYear }}</span>
        <span class="badge badge--var">{{ varMeta.shortLabel }}</span>
        <span class="badge badge--unit">{{ varMeta.unit }}</span>
      </div>
      <div class="header-right">
        <a
          href="https://www.actris.eu"
          target="_blank"
          rel="noopener"
          class="header-link"
        >actris.eu ↗</a>
      </div>
    </header>

    <!-- Main body -->
    <div class="body">
      <!-- Left sidebar -->
      <aside class="sidebar">
        <ControlPanel />
        <div class="sidebar-divider" />
        <StatsCards />
      </aside>

      <!-- Map + ranking -->
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
  gap: 20px;
  height: 52px;
  padding: 0 20px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  z-index: 100;
}

.header-brand {
  display: flex;
  align-items: center;
  gap: 10px;
}
.brand-icon { flex-shrink: 0; }
.brand-name {
  font-size: 15px;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: var(--text);
  white-space: nowrap;
}
.brand-sub {
  font-size: 11px;
  color: var(--text-muted);
  white-space: nowrap;
  padding-left: 6px;
  border-left: 1px solid var(--border);
  margin-left: 2px;
}

.header-badges {
  display: flex;
  gap: 6px;
  margin-left: auto;
}
.badge {
  font-size: 11px;
  font-weight: 600;
  padding: 3px 9px;
  border-radius: 4px;
  font-variant-numeric: tabular-nums;
}
.badge--year { background: rgba(0, 212, 255, 0.12); color: var(--accent); border: 1px solid rgba(0, 212, 255, 0.25); }
.badge--var  { background: rgba(124, 58, 237, 0.12); color: #a78bfa; border: 1px solid rgba(124, 58, 237, 0.25); font-family: Georgia, serif; font-style: italic; }
.badge--unit { background: rgba(100, 116, 139, 0.1); color: var(--text-muted); border: 1px solid var(--border); font-family: monospace; }

.header-right { margin-left: 12px; }
.header-link { font-size: 11px; color: var(--text-muted); text-decoration: none; }
.header-link:hover { color: var(--accent); }

/* ── Body ── */
.body {
  display: flex;
  flex: 1;
  min-height: 0;
}

/* ── Sidebar ── */
.sidebar {
  width: 260px;
  flex-shrink: 0;
  background: var(--surface);
  border-right: 1px solid var(--border);
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  padding-top: 12px;
}
.sidebar-divider {
  height: 1px;
  background: var(--border);
  margin: 12px 0;
}

/* ── Content area ── */
.content {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.map-area {
  flex: 1;
  min-height: 0;
  position: relative;
}
.ranking-area {
  height: 240px;
  flex-shrink: 0;
}
</style>
