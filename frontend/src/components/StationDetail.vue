<script setup lang="ts">
/**
 * The panel a click opens. Two kinds of station end up here:
 *
 *  - one of ours, with an annual record for the selected year (and possibly NRT);
 *  - an NRT-only site, which has no annual record at all and shows only the
 *    live-data section.
 *
 * The NRT block links out rather than plotting anything. That data is Level 1.5 —
 * preliminary, not quality-assured — while everything else in this dashboard is
 * Level 2, so the panel says so rather than letting the two sit side by side
 * looking equivalent.
 */
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useStationsStore } from '@/stores/stations'
import { useStationData, useNrtStations, useActrisFacilities } from '@/composables/useStationData'
import { VARIABLES } from '@/types'
import type { Variable } from '@/types'

const store = useStationsStore()
const { selectedStationId, selectedVariable, selectedYear } = storeToRefs(store)
const { stationsQuery } = useStationData()
const { data: nrt } = useNrtStations()
const { data: actris } = useActrisFacilities()

const station = computed(() =>
  (stationsQuery.data.value ?? []).find((s) => s.id === selectedStationId.value) ?? null,
)

const nrtEntry = computed(() =>
  selectedStationId.value ? (nrt.value?.stations?.[selectedStationId.value] ?? null) : null,
)

/** Title and position work for both kinds: ours if we have it, else NRT's copy. */
const displayName = computed(() => station.value?.name ?? nrtEntry.value?.name ?? selectedStationId.value ?? '')
const lat = computed(() => station.value?.lat ?? nrtEntry.value?.lat ?? null)
const lon = computed(() => station.value?.lon ?? nrtEntry.value?.lon ?? null)

const isNrtOnly = computed(() => station.value === null && nrtEntry.value !== null)

/** ACTRIS facility registry entry. Null when the station has no record there. */
const facility = computed(() =>
  selectedStationId.value ? (actris.value?.facilities?.[selectedStationId.value] ?? null) : null,
)

const nrtVariableLabels = computed(() =>
  (nrtEntry.value?.variables ?? []).map((v: Variable) => VARIABLES[v]?.shortLabel ?? v),
)

/** Does the live data cover the variable currently being viewed? */
const nrtHasSelected = computed(() =>
  (nrtEntry.value?.variables ?? []).includes(selectedVariable.value),
)

function close() {
  store.selectedStationId = null
}

function coord(value: number, positive: string, negative: string) {
  return `${Math.abs(value).toFixed(3)}°${value >= 0 ? positive : negative}`
}
</script>

<template>
  <div v-if="selectedStationId" class="detail" role="dialog" :aria-label="`Station ${displayName}`">
    <button class="detail-close" type="button" aria-label="Close station details" @click="close">×</button>

    <div class="detail-name">
      {{ displayName && displayName !== selectedStationId ? displayName : selectedStationId }}
    </div>
    <div class="detail-id">
      <span class="mono">{{ selectedStationId }}</span>
      <span v-if="station?.country"> · {{ station.country }}</span>
      <span v-if="isNrtOnly" class="detail-tag">near-real-time only</span>
    </div>
    <div v-if="lat !== null && lon !== null" class="detail-coords">
      {{ coord(lat, 'N', 'S') }}, {{ coord(lon, 'E', 'W') }}
    </div>

    <!-- Our own record -->
    <div v-if="station" class="detail-block">
      <div class="detail-label">{{ selectedYear }} · {{ VARIABLES[selectedVariable].shortLabel }}</div>
      <div v-if="station.mean !== null" class="detail-figures">
        <div>
          <div class="detail-sub">Annual mean</div>
          <div class="detail-val">
            {{ station.mean.toFixed(1) }}<span class="detail-unit">{{ station.unit }}</span>
          </div>
        </div>
        <div v-if="station.delta_pct !== null">
          <div class="detail-sub">vs prev. year</div>
          <div :class="['detail-val', station.delta_pct > 0 ? 'up' : 'dn']">
            {{ station.delta_pct > 0 ? '▲' : '▼' }} {{ Math.abs(station.delta_pct).toFixed(1) }}%
          </div>
        </div>
      </div>
      <div v-else class="detail-none">No data for this year</div>
      <div v-if="station.networks" class="detail-networks">{{ station.networks.split(',').join(' · ') }}</div>
    </div>
    <div v-else-if="isNrtOnly" class="detail-block">
      <div class="detail-none">
        Not in this dashboard’s Level 2 record — it appears here only because it reports live data.
      </div>
    </div>

    <!-- ACTRIS facility registry -->
    <div v-if="facility" class="detail-block">
      <div class="detail-label">ACTRIS facility</div>
      <div v-if="facility.altitude_m !== null" class="detail-alt">
        {{ Math.round(facility.altitude_m) }} m above sea level
      </div>
      <div v-if="facility.labelling_status" class="detail-status">
        Labelling: <span class="detail-status-val">{{ facility.labelling_status }}</span>
      </div>
      <a
        v-if="facility.uri"
        class="detail-link detail-link--actris"
        :href="facility.uri"
        target="_blank"
        rel="noopener noreferrer"
      >Open in the ACTRIS Data Portal ↗</a>
    </div>

    <!-- Live data -->
    <div v-if="nrtEntry" class="detail-block detail-nrt">
      <div class="detail-label detail-label--live">
        <span class="live-dot" />Live data available
      </div>
      <div class="detail-nrt-vars">
        {{ nrtVariableLabels.join(' · ') }}
        <span v-if="!nrtHasSelected" class="detail-nrt-note">
          (not {{ VARIABLES[selectedVariable].shortLabel }})
        </span>
      </div>
      <a class="detail-link" :href="nrtEntry.url" target="_blank" rel="noopener noreferrer">
        Open at EBAS near-real-time ↗
      </a>
      <p class="detail-caveat">
        Hourly, rolling window, provided by NILU. Level 1.5 — preliminary and not
        quality-assured, unlike the Level 2 annual means shown here. The two are not
        directly comparable.
      </p>
    </div>
    <div v-else class="detail-block">
      <div class="detail-none">No near-real-time data for this station.</div>
    </div>
  </div>
</template>

<style scoped>
.detail {
  position: absolute;
  top: 14px;
  left: 14px;
  width: 260px;
  max-height: calc(100% - 28px);
  overflow-y: auto;
  background: rgba(255, 255, 255, 0.98);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px 16px;
  backdrop-filter: blur(10px);
  z-index: 15;
  box-shadow: 0 6px 22px rgba(48, 49, 147, 0.14);
}

.detail-close {
  position: absolute;
  top: 6px;
  right: 8px;
  border: 0;
  background: none;
  font-size: 20px;
  line-height: 1;
  color: var(--text-muted);
  cursor: pointer;
  padding: 2px 4px;
  border-radius: 4px;
}
.detail-close:hover { color: var(--text); }
.detail-close:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }

.detail-name { font-size: 14px; font-weight: 600; color: var(--accent); padding-right: 18px; }
.detail-id { font-size: 11px; color: var(--text-muted); margin-top: 2px; }
.mono { font-family: monospace; }
.detail-tag {
  display: inline-block;
  margin-left: 6px;
  padding: 1px 6px;
  border-radius: 999px;
  background: rgba(14, 157, 184, 0.12);
  color: #0b7f96;
  font-size: 9.5px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.detail-coords {
  font-size: 10px;
  color: var(--text-muted);
  font-family: monospace;
  font-variant-numeric: tabular-nums;
  margin-top: 2px;
}

.detail-block { margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--border); }
.detail-label {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.07em;
  text-transform: uppercase;
  color: var(--text-muted);
  margin-bottom: 8px;
}
.detail-figures { display: flex; gap: 22px; }
.detail-sub { font-size: 10px; color: var(--text-muted); margin-bottom: 2px; }
.detail-val { font-size: 17px; font-weight: 700; font-variant-numeric: tabular-nums; color: var(--text); }
.detail-unit { font-size: 10px; color: var(--text-muted); margin-left: 3px; }
.up { color: var(--negative); font-size: 15px; }
.dn { color: var(--positive); font-size: 15px; }
.detail-none { font-size: 11px; color: var(--text-muted); font-style: italic; line-height: 1.5; }
.detail-networks { font-size: 10px; color: var(--text-muted); margin-top: 8px; }

.detail-alt { font-size: 12px; color: var(--text); font-variant-numeric: tabular-nums; }
.detail-status { font-size: 12px; color: var(--text); margin-top: 3px; }
.detail-status-val { font-weight: 600; }
.detail-link--actris { color: var(--accent); }
.detail-link--actris:focus-visible { outline: 2px solid var(--accent); }

.detail-label--live { display: flex; align-items: center; gap: 6px; color: #0b7f96; }
.live-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #0e9db8;
  animation: live-pulse 1.8s ease-in-out infinite;
}
@keyframes live-pulse {
  0%, 100% { opacity: 0.35; }
  50% { opacity: 1; }
}
@media (prefers-reduced-motion: reduce) {
  .live-dot { animation: none; opacity: 1; }
}
.detail-nrt-vars { font-size: 12px; color: var(--text); font-family: Georgia, serif; font-style: italic; }
.detail-nrt-note { font-style: normal; font-family: inherit; font-size: 10px; color: var(--text-muted); }
.detail-link {
  display: inline-block;
  margin-top: 10px;
  font-size: 12px;
  font-weight: 600;
  color: #0b7f96;
  text-decoration: none;
}
.detail-link:hover { text-decoration: underline; }
.detail-link:focus-visible { outline: 2px solid #0e9db8; outline-offset: 2px; border-radius: 2px; }
.detail-caveat { font-size: 10px; color: var(--text-muted); line-height: 1.5; margin: 8px 0 0; }
</style>
