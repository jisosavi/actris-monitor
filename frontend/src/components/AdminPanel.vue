<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { Button } from '@/components/ui/button'
import { useStationsStore } from '@/stores/stations'

const store = useStationsStore()
const { showDataSetup } = storeToRefs(store)

const REPOSITORY_URL = 'https://github.com/jisosavi/actris-monitor'
</script>

<template>
  <div class="admin-panel">
    <Button size="sm" variant="outline" class="panel-btn" @click="showDataSetup = true">
      Data Setup
    </Button>
    <Button
      as="a"
      size="sm"
      variant="outline"
      class="panel-btn"
      :href="REPOSITORY_URL"
      target="_blank"
      rel="noopener noreferrer"
    >
      About this app ↗
    </Button>
  </div>
</template>

<style scoped>
/* Pinned to the bottom of the scrolling sidebar. Two stacked buttons push the
   sidebar's content past its height on a 1000px window, and without this both
   scroll out of sight — including Data Setup, which used to be visible. */
.admin-panel {
  position: sticky;
  bottom: 0;
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  background: var(--surface);
  border-top: 1px solid var(--border);
}
.panel-btn { width: 100%; font-size: 11px; }
/* The second button is an anchor, which does not inherit the button's centring. */
a.panel-btn { display: inline-flex; align-items: center; justify-content: center; text-decoration: none; }
</style>
