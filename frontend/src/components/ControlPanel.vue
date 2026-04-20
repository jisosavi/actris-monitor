<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { useStationsStore } from '@/stores/stations'
import { VARIABLES, YEAR_MIN, YEAR_MAX } from '@/types'
import type { Variable } from '@/types'

const store = useStationsStore()
const { selectedYear, selectedVariable, rankingMode } = storeToRefs(store)

const variables = Object.entries(VARIABLES) as [Variable, (typeof VARIABLES)[Variable]][]

const years = Array.from({ length: YEAR_MAX - YEAR_MIN + 1 }, (_, i) => YEAR_MAX - i)
</script>

<template>
  <div class="control-panel">
    <div class="section-label">Year</div>
    <select v-model="selectedYear" class="select-field">
      <option v-for="y in years" :key="y" :value="y">{{ y }}</option>
    </select>

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
      <button
        :class="['toggle-btn', rankingMode === 'concentration' && 'toggle-btn--active']"
        @click="rankingMode = 'concentration'"
      >
        Concentration
      </button>
      <button
        :class="['toggle-btn', rankingMode === 'delta' && 'toggle-btn--active']"
        @click="rankingMode = 'delta'"
      >
        Annual change
      </button>
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
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-muted);
  margin-bottom: 8px;
}

.select-field {
  width: 100%;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text);
  padding: 8px 12px;
  font-size: 14px;
  cursor: pointer;
  outline: none;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2364748b' stroke-width='2'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 10px center;
}
.select-field:focus { border-color: var(--accent); }

.var-list { display: flex; flex-direction: column; gap: 6px; }

.var-btn {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text-muted);
  cursor: pointer;
  text-align: left;
  transition: all 0.15s ease;
  width: 100%;
}
.var-btn:hover { border-color: var(--accent); color: var(--text); }
.var-btn--active {
  border-color: var(--accent);
  background: rgba(0, 212, 255, 0.08);
  color: var(--text);
}

.var-symbol {
  font-family: 'Georgia', serif;
  font-style: italic;
  font-size: 14px;
  color: var(--accent);
  width: 28px;
  flex-shrink: 0;
  text-align: center;
}
.var-btn--active .var-symbol { color: var(--accent); }

.var-text { display: flex; flex-direction: column; }
.var-name { font-size: 12px; line-height: 1.3; }
.var-unit { font-size: 10px; color: var(--text-muted); margin-top: 1px; font-family: monospace; }

.toggle-group { display: flex; gap: 6px; }
.toggle-btn {
  flex: 1;
  padding: 7px 8px;
  font-size: 11px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s ease;
}
.toggle-btn:hover { border-color: var(--accent); color: var(--text); }
.toggle-btn--active {
  background: rgba(0, 212, 255, 0.12);
  border-color: var(--accent);
  color: var(--accent);
  font-weight: 600;
}
</style>
