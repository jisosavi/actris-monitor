<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { useStationsStore } from '@/stores/stations'
import { VARIABLES, YEAR_MIN, YEAR_MAX } from '@/types'
import type { Variable } from '@/types'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

const store = useStationsStore()
const { selectedYear, selectedVariable, rankingMode } = storeToRefs(store)

const variables = Object.entries(VARIABLES) as [Variable, (typeof VARIABLES)[Variable]][]
const years = Array.from({ length: YEAR_MAX - YEAR_MIN + 1 }, (_, i) => YEAR_MAX - i)

function onYearChange(val: string) {
  selectedYear.value = Number(val)
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
        <SelectItem v-for="y in years" :key="y" :value="String(y)">{{ y }}</SelectItem>
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
</style>
