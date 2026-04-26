<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useStationsStore } from '@/stores/stations'
import { useDbStatus } from '@/composables/useStationData'
import { VARIABLES, YEAR_MIN, YEAR_MAX } from '@/types'
import type { Variable } from '@/types'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

const store = useStationsStore()
const { selectedYear, selectedVariable, rankingMode, networkFilter } = storeToRefs(store)
const { data: dbStatus } = useDbStatus()

const NETWORKS = ['ACTRIS', 'EMEP', 'GAW-WDCA'] as const

function toggleNetwork(net: string) {
  const idx = networkFilter.value.indexOf(net)
  if (idx >= 0) networkFilter.value.splice(idx, 1)
  else networkFilter.value.push(net)
}

const variables = Object.entries(VARIABLES) as [Variable, (typeof VARIABLES)[Variable]][]
const years = Array.from({ length: YEAR_MAX - YEAR_MIN + 1 }, (_, i) => YEAR_MAX - i)
const varKeys = Object.keys(VARIABLES) as Variable[]

const coverageSet = computed(() => {
  const s = new Set<string>()
  for (const { year, variable } of dbStatus.value?.coverage ?? [])
    s.add(`${year}:${variable}`)
  return s
})

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function onYearChange(val: any) {
  if (val != null) selectedYear.value = Number(val)
}
</script>

<template>
  <div class="control-panel">
    <div class="section-label">Year</div>
    <Select :model-value="String(selectedYear)" @update:model-value="onYearChange">
      <SelectTrigger class="select-trigger">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          <SelectItem
            v-for="y in years"
            :key="y"
            :value="String(y)"
            :text-value="String(y)"
          >
            <div class="year-option">
              <span>{{ y }}</span>
              <div class="year-cov">
                <span
                  v-for="v in varKeys"
                  :key="v"
                  :class="['cov-pip', coverageSet.has(`${y}:${v}`) && 'cov-pip--on']"
                  :data-var="v === 'N' ? 'N' : v === 'scattering' ? 'S' : 'A'"
                  :title="VARIABLES[v].label"
                />
              </div>
            </div>
          </SelectItem>
        </SelectGroup>
      </SelectContent>
    </Select>

    <div class="section-label mt-5">Variable</div>
    <div class="var-list">
      <button
        v-for="[key, meta] in variables"
        :key="key"
        :class="['var-btn', selectedVariable === key && 'var-btn--active']"
        @click="selectedVariable = key"
      >
        <span class="var-symbol">{{ meta.shortLabel }}</span>
        <span class="var-text">
          <span class="var-name">{{ meta.label }}</span>
          <span class="var-unit">{{ meta.unit }}</span>
        </span>
      </button>
    </div>

    <div class="section-label mt-5">Map colour</div>
    <div class="toggle-group">
      <Button
        :variant="rankingMode === 'concentration' ? 'default' : 'outline'"
        size="sm"
        class="toggle-btn"
        @click="rankingMode = 'concentration'"
      >
        Concentration
      </Button>
      <Button
        :variant="rankingMode === 'delta' ? 'default' : 'outline'"
        size="sm"
        class="toggle-btn"
        @click="rankingMode = 'delta'"
      >
        Annual change
      </Button>
    </div>

    <div class="section-label mt-5">Network</div>
    <div class="net-filter">
      <button
        v-for="net in NETWORKS"
        :key="net"
        :class="['net-btn', networkFilter.includes(net) && 'net-btn--on']"
        @click="toggleNetwork(net)"
      >
        {{ net }}
      </button>
    </div>
    <div v-if="networkFilter.length > 0" class="net-hint">
      Showing {{ networkFilter.join(' + ') }} stations only
    </div>
  </div>
</template>

<style scoped>
.control-panel {
  padding: 16px;
  display: flex;
  flex-direction: column;
}

.section-label {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
  margin-bottom: 8px;
}

.select-trigger {
  width: 100%;
  background: var(--surface);
  border-color: var(--border);
  color: var(--text);
}


.var-list { display: flex; flex-direction: column; gap: 5px; }

.var-btn {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text-muted);
  cursor: pointer;
  text-align: left;
  transition: all 0.15s ease;
  width: 100%;
  font-family: inherit;
}
.var-btn:hover {
  border-color: var(--accent);
  color: var(--text);
  background: var(--accent-light);
}
.var-btn--active {
  border-color: var(--accent);
  background: var(--accent-light);
  color: var(--text);
}

.var-symbol {
  font-family: Georgia, serif;
  font-style: italic;
  font-size: 14px;
  color: var(--accent);
  width: 28px;
  flex-shrink: 0;
  text-align: center;
}

.var-text { display: flex; flex-direction: column; }
.var-name { font-size: 12px; line-height: 1.3; }
.var-unit { font-size: 10px; color: var(--text-muted); margin-top: 1px; font-family: monospace; }

.toggle-group { display: flex; gap: 6px; }
.toggle-btn { flex: 1; font-size: 11px; }

.net-filter { display: flex; flex-direction: column; gap: 4px; }
.net-btn {
  padding: 7px 12px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text-muted);
  font-size: 11px;
  font-family: inherit;
  cursor: pointer;
  text-align: left;
  transition: all 0.15s;
}
.net-btn:hover { border-color: var(--accent); color: var(--text); }
.net-btn--on {
  border-color: var(--accent);
  background: var(--accent-light);
  color: var(--accent);
  font-weight: 600;
}
.net-hint {
  font-size: 10px;
  color: var(--accent);
  margin-top: 2px;
}
</style>
